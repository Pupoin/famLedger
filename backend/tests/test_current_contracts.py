"""Regression coverage for current authentication and linked financial data."""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlmodel import select
from models import Account, AccountShare, Family, OIDCIdentity, RefundAllocation, SSOProvider, Transaction, User
from routes import v1_oidc


@pytest.mark.parametrize('policy,email,status', [
    ({'allow_jit': True, 'allowed_domains': ['EXAMPLE.COM']}, 'new@example.com', 302),
    ({'allow_jit': False}, 'new@example.com', 403),
    ({'allowed_domains': ['other.com']}, 'new@example.com', 403),
    ({'allowed_domains': 'example.com', 'default_role': 'member'}, 'new@example.com', 302),
    ({'allowed_domains': 7}, 'new@example.com', 400),
])
def test_oidc_first_login_uses_json_policy(client, db, oidc_flow, policy, email, status):
    flow = oidc_flow(policy=policy, userinfo_update={"email": email})
    name, username = flow.provider.name, flow.username
    provider = flow.provider
    response = client.get(flow.path, follow_redirects=False)
    assert response.status_code == status
    user = db.exec(select(User).where(User.username == username)).first()
    if status == 302:
        assert user and user.role == 'member' and user.family_id is None
        assert client.get('/api/auth/me').json()['username'] == username
    else:
        assert user is None
    for identity in db.exec(select(OIDCIdentity).where(OIDCIdentity.provider == name)).all():
        db.delete(identity)
    db.delete(provider)
    db.commit()


def test_refund_status_hides_original_after_share_revocation(auth_client_a, db):
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    family = Family(name='Revoked refund access')
    db.add(family)
    db.flush()
    alice.family_id = bob.family_id = family.id
    db.add_all([alice, bob])
    accounts = [Account(name='Refund', owner_id=alice.id, family_id=family.id, account_type='checking'),
                Account(name='Private original', owner_id=bob.id, family_id=family.id, account_type='checking')]
    db.add_all(accounts)
    db.flush()
    original = Transaction(account_id=accounts[1].id, transacted_at=date.today(), amount=Decimal('100'), narration='PRIVATE MERCHANT')
    db.add(original)
    db.flush()
    refund = Transaction(account_id=accounts[0].id, transacted_at=date.today(), amount=Decimal('10'),
                         narration='Refund', transaction_type='refund', refund_of_transaction_id=original.id)
    db.add(refund)
    db.flush()
    allocation = RefundAllocation(refund_transaction_id=refund.id, original_transaction_id=original.id,
                                  allocated_amount=Decimal('10'))
    share = AccountShare(account_id=accounts[1].id, user_id=alice.id, permission='read_only')
    db.add_all([allocation, share])
    db.commit()
    path = f'/api/v1/refunds/{refund.id}/status'
    assert auth_client_a.get(path).json()['original_transaction']['narration'] == 'PRIVATE MERCHANT'
    db.delete(share)
    db.commit()
    result = auth_client_a.get(path)
    assert result.status_code == 200
    assert result.json()['is_linked'] is True
    assert result.json()['original_transaction'] is None
    assert result.json()['allocations'] == []
    assert str(original.id) not in result.text and 'PRIVATE MERCHANT' not in result.text

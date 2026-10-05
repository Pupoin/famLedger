"""Private accounts require explicit access, including for system administrators."""
import pytest
from sqlmodel import select

from models import Account, AccountShare, Family, User


@pytest.mark.parametrize('role', ['member', 'owner', 'admin'])
def test_management_list_and_direct_requests_require_explicit_access(auth_client_a, db, role):
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    family = Family(name='Account visibility')
    foreign_family = Family(name='Other family')
    db.add_all([family, foreign_family]); db.flush()
    alice.family_id = bob.family_id = family.id
    alice.role = role
    db.add_all([alice, bob]); db.flush()
    owned = Account(name='My private card', family_id=family.id, owner_id=alice.id, account_type='checking')
    private = Account(name='Other private card', family_id=family.id, owner_id=bob.id, account_type='checking')
    foreign = Account(name='Foreign card', family_id=foreign_family.id, owner_id=bob.id, account_type='checking')
    shared = {
        permission: Account(name=permission, family_id=family.id, owner_id=bob.id, account_type='checking')
        for permission in ('read_only', 'read_write', 'full_control')
    }
    db.add_all([owned, private, foreign, *shared.values()]); db.flush()
    for permission, account in shared.items():
        db.add(AccountShare(account_id=account.id, user_id=alice.id, permission=permission))
    # A stale or forged cross-family share must not grant account-management access.
    db.add(AccountShare(account_id=foreign.id, user_id=alice.id, permission='full_control'))
    db.commit()
    expected = {str(account.id) for account in [owned, *shared.values()]}
    def matrix():
        response = auth_client_a.get('/api/v1/accounts/shares/matrix')
        assert response.status_code == 200, response.text
        return {row['account_id']: row for row in response.json()['accounts']}
    assert set(matrix()) == expected
    listing = auth_client_a.get('/api/v1/accounts').json()['accounts']
    assert {row['id'] for row in listing} == expected
    for account in [private, foreign]:
        assert auth_client_a.get(f'/api/v1/accounts/{account.id}').status_code == 403
        assert auth_client_a.get(f'/api/v1/accounts/{account.id}/shares').status_code == 403
        assert auth_client_a.patch(f'/api/v1/accounts/{account.id}', json={'name': 'Unauthorized'}).status_code == 403
        assert auth_client_a.put(f'/api/v1/accounts/{account.id}/shares', json={'members': [{
            'user_id': str(alice.id), 'shared': True, 'permission': 'full_control',
        }]}).status_code == 403
    for permission, account in shared.items():
        row = matrix()[str(account.id)]
        assert row['can_manage'] is (permission == 'full_control')
        assert row['can_manage_shares'] is (permission == 'full_control')
        detail = auth_client_a.get(f'/api/v1/accounts/{account.id}/shares')
        assert detail.status_code == 200
        assert detail.json()['can_manage'] is (permission == 'full_control')
        if permission != 'full_control':
            for method in ('PATCH', 'PUT'):
                assert auth_client_a.request(method, f'/api/v1/accounts/{account.id}/shares', json={
                    'members': [{'user_id': str(alice.id), 'shared': True, 'permission': 'full_control'}],
                }).status_code == 403
            assert auth_client_a.patch(f'/api/v1/accounts/{account.id}', json={'name': 'Unauthorized'}).status_code == 403
    removed = shared['read_only']
    share = db.exec(select(AccountShare).where(AccountShare.account_id == removed.id, AccountShare.user_id == alice.id)).one()
    db.delete(share); db.commit()
    assert str(removed.id) not in matrix()
    assert auth_client_a.get(f'/api/v1/accounts/{removed.id}/shares').status_code == 403
    db.expire_all()
    assert db.get(Account, private.id).name == 'Other private card'
    for permission, account in shared.items():
        assert db.get(Account, account.id).name == permission

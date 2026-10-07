"""Personal sidebar preferences preserve financial data and require balance confirmation."""
from datetime import date
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from models import Account, AccountShare, ExchangeRateSnapshot, Family, Transaction, User, UserPreference
from services.schema import sync_schema


def create_account(client, **options):
    response = client.post('/api/v1/accounts', json={
        'name': 'Sidebar account', 'account_type': 'checking', 'currency': 'CNY', 'balance': '0', **options,
    })
    assert response.status_code == 200, response.text
    return uuid.UUID(response.json()['id'])


def visibility(client, account, hidden=True, confirmed=False):
    return client.patch(f'/api/v1/accounts/{account}/sidebar', json={
        'hidden': hidden, 'confirm_nonzero_balance': confirmed,
    })


def read_visibility(client, account):
    listed = client.get('/api/v1/accounts')
    assert listed.status_code == 200, listed.text
    row = next(a for a in listed.json()['accounts'] if a['id'] == str(account))
    matrix = client.get('/api/v1/accounts/shares/matrix')
    assert matrix.status_code == 200, matrix.text
    managed = next(a for a in matrix.json()['accounts'] if a['account_id'] == str(account))
    assert managed['hidden_in_sidebar'] == row['hidden_in_sidebar']
    return row


def test_zero_balance_hide_restore_is_persistent_and_idempotent(auth_client_a, db):
    account_id = create_account(auth_client_a)
    assert read_visibility(auth_client_a, account_id)['hidden_in_sidebar'] is False
    for _ in range(2):
        result = visibility(auth_client_a, account_id)
        assert result.status_code == 200, result.text
        assert read_visibility(auth_client_a, account_id)['hidden_in_sidebar'] is True
    preferences = db.exec(select(UserPreference).where(UserPreference.username == 'alice')).one()
    db.refresh(preferences)
    assert preferences.hidden_sidebar_accounts == [str(account_id)]
    assert visibility(auth_client_a, account_id, hidden=False).status_code == 200
    assert read_visibility(auth_client_a, account_id)['hidden_in_sidebar'] is False
    db.refresh(preferences)
    assert preferences.hidden_sidebar_accounts == []


@pytest.mark.parametrize('account_type,expected', [('checking', '-25.0000'), ('credit_card', '25.0000')])
def test_nonzero_confirmation_uses_transactions_not_stored_balance(auth_client_a, db, account_type, expected):
    quote_day = date.today()
    db.add(ExchangeRateSnapshot(requested_date=quote_day, base_currency='EUR', effective_date=quote_day,
                               rates={'EUR': '1', 'USD': '1.1', 'CNY': '7.9', 'CAD': '1.5'}))
    db.commit()
    account_id = create_account(auth_client_a, account_type=account_type, currency='USD')
    row = Transaction(account_id=account_id, transacted_at=date(2026, 10, 1),
                      narration='Actual expense', amount=Decimal('25'), currency='USD', transaction_type='expense')
    db.add(row); db.commit()
    account = db.get(Account, account_id)
    assert account.balance == 0
    db.refresh(row)
    before = row.model_dump()
    result = visibility(auth_client_a, account_id)
    assert result.status_code == 409, result.text
    assert result.json()['detail'] == {'code': 'balance_confirmation_required', 'balance': expected, 'currency': 'USD'}
    assert read_visibility(auth_client_a, account_id)['hidden_in_sidebar'] is False
    assert visibility(auth_client_a, account_id, confirmed=True).status_code == 200
    hidden = read_visibility(auth_client_a, account_id)
    assert hidden['hidden_in_sidebar'] and Decimal(hidden['balance']) == Decimal(expected)
    db.refresh(row); db.refresh(account)
    assert row.model_dump() == before and account.balance == 0 and account.is_active
    assert hidden['report_included'] is True
    assert visibility(auth_client_a, account_id, hidden=False).status_code == 200


def test_read_only_shared_account_can_be_hidden_independently(auth_client_a, auth_client_b, db):
    account_id = create_account(auth_client_a)
    account = db.get(Account, account_id)
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    bob.family_id = account.family_id
    db.add(bob)
    share = AccountShare(account_id=account_id, user_id=bob.id, permission='read_only')
    db.add(share); db.commit()
    shared_row = read_visibility(auth_client_b, account_id)
    owner = db.get(User, account.owner_id)
    assert shared_row['owner_username'] == owner.username == 'alice'
    assert shared_row['owner'] == (owner.display_name or owner.username)
    assert visibility(auth_client_b, account_id).status_code == 200
    assert read_visibility(auth_client_b, account_id)['hidden_in_sidebar'] is True
    assert read_visibility(auth_client_a, account_id)['hidden_in_sidebar'] is False
    assert auth_client_b.patch(f'/api/v1/accounts/{account_id}', json={'name': 'Unauthorized edit'}).status_code == 403
    db.refresh(share); db.refresh(account)
    assert share.permission == 'read_only' and account.name == 'Sidebar account'


def test_private_or_foreign_accounts_cannot_be_hidden(auth_client_a, auth_client_b, db):
    account_id = create_account(auth_client_a)
    assert visibility(auth_client_b, account_id, confirmed=True).status_code == 404
    account = db.get(Account, account_id)
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    bob.family_id = account.family_id; db.add(bob); db.commit()
    assert visibility(auth_client_b, account_id, confirmed=True).status_code == 404
    foreign = Family(name='Other family'); db.add(foreign); db.flush()
    bob.family_id = foreign.id; db.add(bob)
    db.add(AccountShare(account_id=account_id, user_id=bob.id, permission='full_control')); db.commit()
    assert visibility(auth_client_b, account_id, confirmed=True).status_code == 404
    assert visibility(auth_client_a, uuid.uuid4()).status_code == 404
    assert read_visibility(auth_client_a, account_id)['hidden_in_sidebar'] is False


def test_primary_card_confirmation_includes_child_balance(auth_client_a, db):
    parent_id = create_account(auth_client_a, account_type='credit_card')
    child_id = create_account(auth_client_a, account_type='credit_card', parent_account_id=str(parent_id), name='Child')
    db.add(Transaction(account_id=child_id, transacted_at=date(2026, 10, 1),
                       narration='Child card expense', amount=Decimal('40'), currency='CNY', transaction_type='expense')); db.commit()
    response = visibility(auth_client_a, parent_id)
    assert response.status_code == 409, response.text
    assert Decimal(response.json()['detail']['balance']) == 40


def test_sidebar_preference_migrates_existing_sqlite_rows():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE userpreference (id INTEGER PRIMARY KEY, username VARCHAR(100) NOT NULL)'))
        connection.execute(text("INSERT INTO userpreference(id, username) VALUES(1, 'old-user')"))
    sync_schema(engine=engine, metadata=UserPreference.metadata)
    with Session(engine) as session:
        row = session.exec(select(UserPreference).where(UserPreference.username == 'old-user')).one()
        assert row.hidden_sidebar_accounts == []
    engine.dispose()

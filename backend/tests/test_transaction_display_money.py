"""Original list money and preference detail money must not revalue the ledger."""
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import update
from sqlmodel import select

from models import ExchangeRateSnapshot, Transaction, TransactionSplit
from test_fixed_booking import DAY, create, fail_quotes, quote
from test_fix104_regressions import setup_accounts


def test_original_list_and_fixed_bank_detail(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db)
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('bank booking needs no lookup'))
    posted = create(auth_client_a, accounts[0], settlement_amount='705', settlement_currency='CNY').json()
    detail = auth_client_a.get(f"/api/v1/transactions/{posted['id']}").json()
    assert detail['display_currency'] == 'CNY'
    assert Decimal(detail['display_amount']) == Decimal('705')
    assert Decimal(detail['original_amount']) == Decimal('100') and detail['original_currency'] == 'USD'
    listing = auth_client_a.get('/api/v1/transactions', params={'account_id': str(accounts[0].id)}).json()
    row = next(t for t in listing['items'] if t['id'] == posted['id'])
    assert Decimal(row['original_amount']) == 100 and row['original_currency'] == 'USD'
    assert Decimal(row['amount']) == 705 and row['currency'] == 'CNY'


def test_preference_detail_uses_transaction_day_not_today(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db, currency='USD')
    quote(db)
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('use stored historical quote'))
    posted = create(auth_client_a, accounts[0]).json()
    uri = f"/api/v1/transactions/{posted['id']}"
    detail = auth_client_a.get(uri).json()
    assert Decimal(detail['display_amount']) == 700 and detail['display_currency'] == 'CNY'
    assert detail['display_exchange_rate_date'] == DAY.isoformat()
    assert detail['display_exchange_rate_base_currency'] == 'USD'
    assert Decimal(detail['display_exchange_rate']) == 7
    assert auth_client_a.put('/api/user-preferences', json={'currency': 'USD'}).status_code == 200
    detail = auth_client_a.get(uri).json()
    assert Decimal(detail['display_amount']) == 100 and detail['display_currency'] == 'USD'
    stored = db.get(Transaction, UUID(posted['id']))
    db.refresh(stored)
    assert stored.amount == 100 and stored.currency == 'USD'
    balance = auth_client_a.get(f'/api/v1/accounts/{accounts[0].id}').json()
    assert Decimal(balance['account']['balance']) == -100


def test_display_conversion_preserves_actual_bank_booking(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db)
    quote(db)
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('quote already cached'))
    posted = create(auth_client_a, accounts[0], settlement_amount='705', settlement_currency='CNY').json()
    assert auth_client_a.put('/api/user-preferences', json={'currency': 'EUR'}).status_code == 200
    detail = auth_client_a.get(f"/api/v1/transactions/{posted['id']}").json()
    assert detail['display_currency'] == 'EUR'
    assert Decimal(detail['display_amount']) == Decimal('100.7143')
    assert detail['display_exchange_rate_base_currency'] == 'CNY'
    assert Decimal(detail['amount']) == 705 and Decimal(detail['original_amount']) == 100


def test_unavailable_quote_keeps_detail_readable_without_false_currency(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db, currency='USD')
    monkeypatch.setattr('services.report_currency.requests.get', fail_quotes)
    posted = create(auth_client_a, accounts[0]).json()
    response = auth_client_a.get(f"/api/v1/transactions/{posted['id']}")
    assert response.status_code == 200
    detail = response.json()
    assert detail['display_amount'] is None and detail['display_currency'] == 'CNY'
    assert detail['display_money_error'] and detail['display_exchange_rate'] is None
    assert Decimal(detail['amount']) == 100 and detail['currency'] == 'USD'
    assert len(db.exec(select(Transaction)).all()) == 1


def test_new_display_quote_is_saved_and_reused(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db, currency='USD')
    posted = create(auth_client_a, accounts[0]).json()
    calls = []

    class QuoteResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {'base': 'EUR', 'date': DAY.isoformat(), 'rates': {'USD': 1, 'CNY': 7}}

    def fetch(*args, **kwargs):
        calls.append(args[0])
        return QuoteResponse()

    monkeypatch.setattr('services.report_currency.requests.get', fetch)
    for _ in range(2):
        response = auth_client_a.get(f"/api/v1/transactions/{posted['id']}")
        assert response.status_code == 200 and Decimal(response.json()['display_amount']) == 700
    assert calls == [f'https://api.frankfurter.app/{DAY.isoformat()}']
    assert db.get(ExchangeRateSnapshot, (DAY, 'EUR')) is not None
    stored = db.get(Transaction, UUID(posted['id']))
    assert stored.amount == 100 and stored.currency == 'USD'


def test_legacy_detail_does_not_invent_original_money(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db, currency='USD')
    quote(db)
    posted = create(auth_client_a, accounts[0]).json()
    db.execute(update(Transaction).where(Transaction.id == UUID(posted['id'])).values(original_amount=None, original_currency=None))
    db.commit()
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('use saved quote'))
    detail = auth_client_a.get(f"/api/v1/transactions/{posted['id']}").json()
    assert detail['needs_money_review'] and detail['original_amount'] is None
    assert Decimal(detail['display_amount']) == 700 and detail['display_currency'] == 'CNY'
    db.expire_all()
    assert db.get(Transaction, UUID(posted['id'])).original_amount is None


def test_permission_checked_before_any_display_fx(auth_client_a, auth_client_b, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db, currency='USD')
    posted = create(auth_client_a, accounts[0]).json()
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('private detail must not fetch quotes'))
    response = auth_client_b.get(f"/api/v1/transactions/{posted['id']}")
    assert response.status_code in (403, 404)


@pytest.mark.parametrize('amount, parts, cny, expected', [
    ('100', ['40', '60'], '7', '700'),
    ('0.0005', ['0.0001'] * 5, '0.5', '0.0003'),
])
def test_splits_use_same_preference_rate_and_conserve_display_total(auth_client_a, db, monkeypatch, amount, parts, cny, expected):
    _, _, _, accounts = setup_accounts(db, currency='USD')
    quote(db, cny=cny)
    posted = create(auth_client_a, accounts[0], amount=amount).json()
    txn = db.get(Transaction, UUID(posted['id']))
    txn.is_split = True
    db.add(txn)
    db.add_all([TransactionSplit(transaction_id=txn.id, amount=Decimal(value)) for value in parts])
    db.commit()
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('same cached rate'))
    detail = auth_client_a.get(f"/api/v1/transactions/{posted['id']}").json()
    assert Decimal(detail['display_amount']) == Decimal(expected)
    assert sum(Decimal(s['display_amount']) for s in detail['splits']) == Decimal(expected)
    assert all(Decimal(s['display_amount']) >= 0 and s['display_currency'] == 'CNY' for s in detail['splits'])
    assert sum(Decimal(s['amount']) for s in detail['splits']) == Decimal(amount)
    assert all(s['currency'] == 'USD' for s in detail['splits'])
    assert sum(s.amount for s in db.exec(select(TransactionSplit)).all()) == Decimal(amount)

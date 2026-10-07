"""Progressive report reads preserve period, currency and authorization."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from models import Account, AccountShare, ExchangeRateSnapshot, Family, Transaction, User, UserPreference
from test_fix104_regressions import setup_accounts


@pytest.mark.parametrize('path', ['/api/v1/analytics/report?include_history=false', '/api/v1/analytics/history'])
def test_progressive_report_requires_login(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize('params', [
    {'period': 'bad'}, {'selected_month': '2026-13'},
    {'period': 'custom', 'start_date': 'invalid'},
    {'period': 'custom', 'start_date': '2026-09-10', 'end_date': '2026-09-01'},
])
def test_history_uses_same_date_validation(auth_client_a, params):
    assert auth_client_a.get('/api/v1/analytics/history', params=params).status_code == 422


@pytest.mark.parametrize('period', ['monthly', 'quarterly', 'ytd', '6m', 'custom', 'all'])
def test_progressive_foreign_currency_sections_equal_full_report(auth_client_a, db, period):
    _, alice, _, accounts = setup_accounts(db)
    day = date.today() - timedelta(days=3)
    original = Transaction(account_id=accounts[0].id, transacted_at=day, amount=Decimal(100),
                           currency='CNY', transaction_type='expense', narration='Recorded purchase')
    db.add(original); db.commit()
    db.add(Transaction(account_id=accounts[0].id, transacted_at=day + timedelta(days=1),
                       amount=Decimal(20), currency='CNY', transaction_type='refund',
                       narration='Recorded refund', refund_of_transaction_id=original.id))
    db.add(UserPreference(username=alice.username, currency='USD'))
    db.commit()
    # Quotes are deterministic, persisted, and cover all ledger/valuation dates.
    for offset in range(220):
        quote_day = date.today() - timedelta(days=offset)
        db.add(ExchangeRateSnapshot(requested_date=quote_day, effective_date=quote_day,
                                   rates={'EUR': '1', 'USD': '1', 'CNY': '2'}))
    db.commit()
    params = {'period': period}
    if period == 'custom':
        params.update(start_date=day.isoformat(), end_date=date.today().isoformat())
    core = auth_client_a.get('/api/v1/analytics/report', params={**params, 'include_history': 'false'})
    full = auth_client_a.get('/api/v1/analytics/report', params=params)
    history = auth_client_a.get('/api/v1/analytics/history', params=params)
    assert core.status_code == full.status_code == history.status_code == 200, (core.text, full.text, history.text)
    c, f, h = core.json(), full.json(), history.json()
    assert c['currency'] == h['currency'] == 'USD'
    assert c['kpis'] == f['kpis'] and c['activity'] == f['activity']
    assert c['net_worth']['current'] == f['net_worth']['current'] == -40
    assert h['trends'] == f['trends'] and h['net_worth']['trend'] == f['net_worth']['trend']
    assert c['date_range'] == h['date_range']
    for response in [core, full, history]:
        assert float(response.headers['Server-Timing'].split('dur=')[1]) >= 0


def test_history_private_and_foreign_tenants_stay_isolated_when_shares_change(auth_client_a, db):
    family, alice, bob, accounts = setup_accounts(db)
    private = Account(name='Private', family_id=family.id, owner_id=bob.id, account_type='checking')
    elsewhere = Family(name='Elsewhere')
    db.add_all([private, elsewhere]); db.flush()
    stranger = User(username='stranger', display_name='Stranger', password_hash='unused', family_id=elsewhere.id)
    db.add(stranger); db.flush()
    foreign = Account(name='Foreign', family_id=elsewhere.id, owner_id=stranger.id, account_type='checking')
    db.add(foreign); db.flush()
    for account, amount in [(accounts[0], 100), (private, 1000), (foreign, 10000)]:
        db.add(Transaction(account_id=account.id, transacted_at=date.today(), amount=Decimal(amount),
                           currency='CNY', transaction_type='expense', narration='Private purchase'))
    db.commit()
    def history_total():
        response = auth_client_a.get('/api/v1/analytics/history')
        assert response.status_code == 200, response.text
        data = response.json()
        assert sum(row['expense'] for row in data['trends']['monthly_breakdown']) != 11100
        return data['net_worth']['trend'][-1]['value']
    assert history_total() == -100
    share = AccountShare(account_id=private.id, user_id=alice.id, permission='read_only')
    db.add(share); db.commit()
    assert history_total() == -1100
    db.delete(share); db.commit()
    assert history_total() == -100

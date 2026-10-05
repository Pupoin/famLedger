"""Balance totals include every authorized account, independently of spending filters."""
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select

from models import Account, AccountShare, ExchangeRateSnapshot, User


def add_account(client, amount, account_type='loan', name='Loan', **changes):
    response = client.post('/api/v1/accounts', json={
        'name': name, 'account_type': account_type, 'balance': str(amount),
        'institution_name': 'Test bank', **changes,
    })
    assert response.status_code == 200, response.text
    return UUID(response.json()['id'])


@pytest.mark.parametrize('excluded_by', ['inactive', 'exclude_from_reports', 'share_preference'])
def test_nine_shared_loans_sum_to_107600_everywhere(auth_client_a, auth_client_b, db, excluded_by):
    amounts = [5400, 5400, 5400, 12000, 12000, 25000, 12000, 25000, 5400]
    ids = [add_account(auth_client_a, amount, name=f'Loan {index}') for index, amount in enumerate(amounts)]
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    bob.family_id = db.get(Account, ids[0]).family_id
    db.add(bob)
    for account_id, amount in zip(ids, amounts):
        account = db.get(Account, account_id)
        share = AccountShare(account_id=account_id, user_id=bob.id, permission='read_only')
        if amount == 5400:
            if excluded_by == 'inactive':
                account.is_active = False
            elif excluded_by == 'exclude_from_reports':
                account.exclude_from_reports = True
            else:
                share.include_in_finances = False
        db.add_all([account, share])
    db.commit()
    listing = auth_client_b.get('/api/v1/accounts')
    assert listing.status_code == 200, listing.text
    rows = listing.json()['accounts']
    assert len(rows) == 9 and sum(Decimal(row['balance']) for row in rows) == 107600
    assert sum(Decimal(row['report_own_balance']) for row in rows) == 107600
    overview = auth_client_b.get('/api/v1/dashboard/summary').json()
    report = auth_client_b.get('/api/v1/analytics/report').json()
    assert overview['balance_sheet']['total_liabilities'] == report['net_worth']['liabilities_total'] == 107600
    assert report['net_worth']['loan_total'] == 107600
    assert overview['balance_sheet']['total_assets'] == report['net_worth']['assets_total'] == 0
    assert overview['outflows']['total'] == report['kpis']['total_expense'] == 0
    groups = overview['balance_sheet']['by_institution']['liabilities']['groups']
    assert groups[0]['total'] == 107600 and len(groups[0]['accounts']) == 9


def test_asset_totals_include_cash_property_vehicle_and_investment(auth_client_a, db):
    assets = [('checking', 1000), ('investment', 2000), ('real_estate', 3000), ('vehicle', 4000), ('other_asset', 500)]
    ids = [add_account(auth_client_a, amount, kind, name=kind) for kind, amount in assets]
    for account_id in ids:
        account = db.get(Account, account_id)
        account.is_active = False
        account.exclude_from_reports = True
        db.add(account)
    db.commit()
    overview = auth_client_a.get('/api/v1/dashboard/summary').json()['balance_sheet']
    report = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
    assert overview['total_assets'] == report['assets_total'] == 10500
    assert overview['total_liabilities'] == report['liabilities_total'] == 0
    assert report['current'] == 10500


def test_other_liabilities_are_not_mislabelled_as_credit_cards(auth_client_a, db):
    add_account(auth_client_a, 100, 'credit_card')
    add_account(auth_client_a, 200, 'loan')
    add_account(auth_client_a, 300, 'other_liability')
    report = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
    assert report['liabilities_total'] == 600
    assert report['credit_total'] == 100 and report['loan_total'] == 500


def test_all_balance_totals_still_exclude_private_accounts_for_admin(auth_client_a, auth_client_b, db):
    shared = add_account(auth_client_a, 100)
    private = add_account(auth_client_a, 99999)
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    bob.family_id = db.get(Account, shared).family_id
    bob.role = 'admin'
    db.add(bob)
    db.add(AccountShare(account_id=shared, user_id=bob.id, permission='read_only'))
    db.commit()
    overview = auth_client_b.get('/api/v1/dashboard/summary').json()['balance_sheet']
    report = auth_client_b.get('/api/v1/analytics/report').json()['net_worth']
    assert overview['total_liabilities'] == report['liabilities_total'] == 100
    returned = [row['id'] for group in overview['by_type']['liabilities']['groups'] for row in group['accounts']]
    assert str(shared) in returned and str(private) not in returned


def test_archived_subcard_is_counted_once_even_when_excluded_from_spending(auth_client_a, db):
    primary_id = add_account(auth_client_a, 100, 'credit_card', name='Primary')
    child_id = add_account(auth_client_a, 200, 'credit_card', name='Child', parent_account_id=str(primary_id))
    child = db.get(Account, child_id)
    child.is_active = False
    child.exclude_from_reports = True
    db.add(child); db.commit()
    detail = auth_client_a.get(f'/api/v1/accounts/{primary_id}').json()
    assert Decimal(detail['account']['balance']) == 300
    listing = auth_client_a.get('/api/v1/accounts').json()['accounts']
    assert sum(Decimal(row['report_own_balance']) for row in listing) == 300
    overview = auth_client_a.get('/api/v1/dashboard/summary').json()['balance_sheet']
    report = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
    assert overview['total_liabilities'] == report['liabilities_total'] == 300


def test_all_balance_totals_convert_foreign_accounts_to_display_currency(auth_client_a, db, monkeypatch):
    ids = [add_account(auth_client_a, 10, currency='USD'), add_account(auth_client_a, 40),
           add_account(auth_client_a, 20, 'real_estate', currency='EUR')]
    for account_id in ids:
        account = db.get(Account, account_id)
        account.is_active = False
        account.exclude_from_reports = True
        db.add(account)
    db.add(ExchangeRateSnapshot(requested_date=date.today(), effective_date=date.today(),
                               rates={'EUR': '1', 'USD': '1', 'CNY': '7'}))
    db.commit()
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('use cached rates'))
    overview = auth_client_a.get('/api/v1/dashboard/summary').json()['balance_sheet']
    report = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
    assert overview['total_assets'] == report['assets_total'] == 140
    assert overview['total_liabilities'] == report['liabilities_total'] == 110
    assert overview['net_worth'] == report['current'] == 30
    rows = auth_client_a.get('/api/v1/accounts').json()['accounts']
    assert sum(Decimal(row['report_own_balance']) for row in rows if row['classification'] == 'liability') == 110


def test_overpaid_credit_and_negative_asset_keep_their_sign(auth_client_a):
    add_account(auth_client_a, -100, 'checking')
    add_account(auth_client_a, 300, 'investment')
    add_account(auth_client_a, -20, 'credit_card')
    add_account(auth_client_a, 40)
    overview = auth_client_a.get('/api/v1/dashboard/summary').json()['balance_sheet']
    report = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
    assert overview['total_assets'] == report['assets_total'] == 200
    assert overview['total_liabilities'] == report['liabilities_total'] == 20
    assert overview['net_worth'] == report['current'] == 180

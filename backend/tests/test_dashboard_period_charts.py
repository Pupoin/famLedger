"""Period, scope and accounting regressions for overview charts."""
from datetime import date, timedelta
from decimal import Decimal
import uuid

import pytest
from sqlmodel import select

from models import Account, AccountShare, ExchangeRateSnapshot, Family, Transaction
from test_fix104_regressions import setup_accounts


@pytest.mark.parametrize('refund_only', [False, True])
def test_calendar_refund_intensity_tracks_magnitude_and_matches_spending(auth_client_a, db, refund_only):
    _, _, _, accounts = setup_accounts(db)
    start = date(2026, 9, 1)
    amounts = [1, 5, 10, 25, 50, 100, 200, 1000]
    for index, amount in enumerate(amounts):
        db.add(Transaction(account_id=accounts[0].id, transacted_at=start + timedelta(days=index),
                           amount=Decimal(amount), currency='CNY', transaction_type='refund', narration='net refund'))
        if not refund_only:
            db.add(Transaction(account_id=accounts[0].id, transacted_at=start + timedelta(days=index + 8),
                               amount=Decimal(amount), currency='CNY', transaction_type='expense', narration='purchase'))
    # Refunds offset same-day spending before the day is assigned an intensity.
    offset_day = start + timedelta(days=16)
    for kind in ('expense', 'refund'):
        db.add(Transaction(account_id=accounts[0].id, transacted_at=offset_day,
                           amount=Decimal(75), currency='CNY', transaction_type=kind, narration='offset'))
    db.commit()
    params = {'start_date': start.isoformat(), 'end_date': offset_day.isoformat()}
    summary = auth_client_a.get('/api/v1/dashboard/summary', params={**params, 'period': 'custom'})
    expanded = auth_client_a.get('/api/v1/dashboard/spending-calendar', params={**params, 'minimum_weeks': 4})
    assert summary.status_code == expanded.status_code == 200
    for calendar in [summary.json()['spending_calendar'], expanded.json()]:
        cells = {cell['date']: cell for week in calendar['weeks'] for cell in week}
        refunds = [cells[(start + timedelta(days=index)).isoformat()] for index in range(8)]
        levels = [cell['level'] for cell in refunds]
        assert set(levels) == {1, 2, 3, 4}
        assert levels == sorted(levels)
        assert [cell['amount'] for cell in refunds] == [-amount for amount in amounts]
        assert all(cell['is_refund'] for cell in refunds)
        if not refund_only:
            for index, refund in enumerate(refunds):
                purchase = cells[(start + timedelta(days=index + 8)).isoformat()]
                assert purchase['level'] == refund['level']
                assert not purchase['is_refund']
        assert cells[offset_day.isoformat()]['level'] == 0
        assert cells[offset_day.isoformat()]['amount'] == 0
        assert all(cell['level'] == 0 for cell in cells.values() if cell['outside'])


@pytest.mark.parametrize('period,start,end', [
    ('monthly', date(2026, 9, 1), date(2026, 9, 30)),
    ('quarterly', date(2026, 7, 1), date(2026, 9, 30)),
    ('ytd', date(2026, 1, 1), date(2026, 9, 30)),
    ('6m', date(2026, 4, 1), date(2026, 9, 30)),
    ('custom', date(2026, 9, 14), date(2026, 10, 1)),
    ('custom', date(2026, 9, 14), date(2026, 9, 14)),
])
def test_period_totals_and_calendar_follow_selected_period(auth_client_a, db, period, start, end):
    family, alice, bob, accounts = setup_accounts(db)
    liability = Account(name='Card', family_id=family.id, owner_id=alice.id,
                        account_type='credit_card', classification='liability', currency='CNY')
    private = Account(name='Private', family_id=family.id, owner_id=bob.id, account_type='checking', currency='CNY')
    db.add_all([liability, private]); db.flush()
    days = [date(2026, 1, 15), date(2026, 4, 1), date(2026, 7, 31), date(2026, 8, 2),
            date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 14), date(2026, 9, 30), date(2026, 10, 1)]
    for i, day in enumerate(days, 1):
        for kind, amount in [('expense', i * 10), ('income', 50), ('refund', 2), ('transfer', 8000)]:
            db.add(Transaction(account_id=accounts[0].id, transacted_at=day,
                               amount=Decimal(amount), currency='CNY', transaction_type=kind, narration=f'merchant-{day}'))
        db.add(Transaction(account_id=accounts[0].id, transacted_at=day, amount=Decimal(9000),
                           excluded_from_stats=True, narration='excluded', currency='CNY'))
        db.add(Transaction(account_id=liability.id, transacted_at=day, amount=Decimal(7000),
                           transaction_type='income', narration='repayment', currency='CNY'))
        db.add(Transaction(account_id=private.id, transacted_at=day, amount=Decimal(99999),
                           narration='private-merchant', currency='CNY'))
    db.commit()
    response = auth_client_a.get('/api/v1/dashboard/summary', params={
        'period': period, 'selected_month': '2026-09', 'start_date': start.isoformat(), 'end_date': end.isoformat()})
    assert response.status_code == 200, response.text
    data = response.json()
    selected = [(i, day) for i, day in enumerate(days, 1) if start <= day <= end]
    gross = sum(i * 10 for i, _ in selected)
    expense, income = gross - len(selected) * 2, len(selected) * 50
    assert data['period_dates'] == {'start': start.isoformat(), 'end': end.isoformat()}
    cells = [cell for week in data['spending_calendar']['weeks'] for cell in week]
    inside = [cell for cell in cells if not cell['outside']]
    assert [cell['date'] for cell in inside] == [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    assert all(cell['amount'] == 0 and cell['description'] == '' for cell in cells if cell['outside'])
    assert sum(cell['amount'] for cell in cells) == expense
    bars = data['money_in_out']['last_12_months']
    assert len(bars) == 12
    assert data['money_in_out']['last_6_months'] == bars[-6:]
    for bar in bars:
        monthly = [(i, day) for i, day in enumerate(days, 1) if bar['start_date'] <= day.isoformat() <= bar['end_date']]
        assert bar['expense'] == sum(i * 10 - 2 for i, _ in monthly)
        assert bar['income'] == len(monthly) * 50
    assert data['outflows']['total'] == data['money_in_out']['expenses'] == expense
    assert data['money_in_out']['income'] == income
    assert sum(source['amount'] for source in data['cashflow']['income_sources']) == income
    assert sum(destination['amount'] for destination in data['cashflow']['expense_destinations']) == expense
    assert sum(category['amount'] for category in data['outflows']['categories']) == expense
    assert sum(account['amount'] for account in data['outflows']['by_account']) == expense
    assert sum(merchant['amount'] for merchant in data['merchants']['treemap']) == gross
    assert sum(merchant['amount'] for merchant in data['merchants']['ranking']) == gross
    assert not any('private-merchant' in cell['description'] for cell in cells)


def test_calendar_and_trend_convert_once_and_keep_cross_year_months(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db, 'USD')
    for day in [date(2025, 12, 31), date(2026, 1, 1), date.today()]:
        db.add(ExchangeRateSnapshot(requested_date=day, effective_date=day, rates={'EUR':'1', 'USD':'1', 'CNY':'8'}))
    for day in [date(2025, 12, 31), date(2026, 1, 1)]:
        db.add(Transaction(account_id=accounts[0].id, transacted_at=day, amount=Decimal(10), currency='USD', narration='USD purchase'))
    db.commit()
    response = auth_client_a.get('/api/v1/dashboard/summary?period=custom&start_date=2025-12-31&end_date=2026-01-01')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['currency'] == 'CNY'
    assert sum(c['amount'] for week in data['spending_calendar']['weeks'] for c in week) == 160
    assert [b['ym'] for b in data['money_in_out']['last_12_months'][-2:]] == ['2025-12', '2026-01']
    assert [b['expense'] for b in data['money_in_out']['last_12_months'][-2:]] == [80, 80]
    assert data['outflows']['total'] == 160


@pytest.mark.parametrize('account_filter', ['private', 'missing', 'shared-owner'])
def test_calendar_and_trend_preserve_account_and_member_scope(auth_client_a, db, account_filter):
    family, _, bob, accounts = setup_accounts(db)
    private = Account(name='Private', family_id=family.id, owner_id=bob.id, account_type='checking', currency='CNY')
    db.add(private); db.flush()
    day = date(2026, 9, 10)
    db.add_all([Transaction(account_id=private.id, transacted_at=day, amount=Decimal(999), currency='CNY', narration='bob'),
                Transaction(account_id=accounts[0].id, transacted_at=day, amount=Decimal(12), currency='CNY', narration='alice')])
    params = {'period':'monthly', 'selected_month':'2026-09'}
    expected = 0
    if account_filter == 'shared-owner':
        alice_id = accounts[0].owner_id
        db.add(AccountShare(account_id=private.id, user_id=alice_id, include_in_finances=True))
        params['user'] = 'bob'; expected = 999
    else:
        params['account_id'] = str(private.id if account_filter == 'private' else uuid.uuid4())
    db.commit()
    response = auth_client_a.get('/api/v1/dashboard/summary', params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert sum(c['amount'] for week in data['spending_calendar']['weeks'] for c in week) == expected
    assert sum(b['expense'] for b in data['money_in_out']['last_12_months']) == expected
    assert data['outflows']['total'] == expected


def test_all_history_calendar_starts_at_first_visible_activity(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    day = date(2019, 12, 31)
    db.add(Transaction(account_id=accounts[0].id, transacted_at=day, amount=Decimal(12), currency='CNY', narration='old activity'))
    db.commit()
    response = auth_client_a.get('/api/v1/dashboard/summary?period=ALL')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['spending_calendar']['period_dates']['start'] == day.isoformat()
    assert len(data['money_in_out']['last_12_months']) == 12
    assert sum(c['amount'] for w in data['spending_calendar']['weeks'] for c in w) == 12


def test_expanded_calendar_loads_real_history_without_changing_other_totals(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    for day, amount, kind in [(date(2025, 12, 16), 30, 'expense'),
                              (date(2026, 1, 1), 12, 'expense'),
                              (date(2026, 1, 2), 2, 'refund'),
                              (date(2026, 1, 5), 999, 'expense')]:
        db.add(Transaction(account_id=accounts[0].id, transacted_at=day,
                           amount=Decimal(amount), currency='CNY', transaction_type=kind, narration='real spending'))
    db.commit()
    params = {'start_date': '2026-01-01', 'end_date': '2026-01-04', 'minimum_weeks': 3}
    response = auth_client_a.get('/api/v1/dashboard/spending-calendar', params=params)
    assert response.status_code == 200, response.text
    calendar = response.json()
    assert calendar['period_dates'] == {'start': '2025-12-15', 'end': '2026-01-04'}
    assert len(calendar['weeks']) == 3
    cells = {c['date']: c for week in calendar['weeks'] for c in week}
    assert cells['2025-12-16']['amount'] == 30
    assert cells['2026-01-02']['amount'] == -2
    assert sum(c['amount'] for c in cells.values()) == 40
    summary = auth_client_a.get('/api/v1/dashboard/summary', params={**params, 'period': 'custom'}).json()
    assert summary['outflows']['total'] == 10
    assert summary['period_dates'] == {'start': '2026-01-01', 'end': '2026-01-04'}


def test_expanded_calendar_preserves_private_shared_family_and_account_boundaries(auth_client_a, db):
    family, alice, bob, accounts = setup_accounts(db)
    foreign_family = Family(name='Other family')
    db.add(foreign_family); db.flush()
    private = Account(name='Private', family_id=family.id, owner_id=bob.id, currency='CNY', account_type='checking')
    shared = Account(name='Shared', family_id=family.id, owner_id=bob.id, currency='CNY', account_type='checking')
    excluded = Account(name='Excluded', family_id=family.id, owner_id=alice.id, currency='CNY', account_type='checking', exclude_from_reports=True)
    foreign = Account(name='Foreign', family_id=foreign_family.id, owner_id=bob.id, currency='CNY', account_type='checking')
    db.add_all([private, shared, excluded, foreign]); db.flush()
    db.add_all([AccountShare(account_id=shared.id, user_id=alice.id, include_in_finances=True),
                AccountShare(account_id=foreign.id, user_id=alice.id, include_in_finances=True)])
    for account, amount in [(accounts[0], 10), (private, 999), (shared, 20), (excluded, 9999), (foreign, 99999)]:
        db.add(Transaction(account_id=account.id, transacted_at=date(2025, 12, 16),
                           amount=Decimal(amount), currency='CNY', narration=account.name))
    db.add(Transaction(account_id=accounts[0].id, transacted_at=date(2025, 12, 16),
                       amount=Decimal(999), currency='CNY', excluded_from_stats=True, narration='excluded'))
    db.commit()
    params = {'start_date':'2026-01-01', 'end_date':'2026-01-04', 'minimum_weeks':3}
    def total(extra):
        response = auth_client_a.get('/api/v1/dashboard/spending-calendar', params={**params, **extra})
        assert response.status_code == 200, response.text
        return sum(c['amount'] for week in response.json()['weeks'] for c in week)
    assert total({}) == 30
    assert total({'user':'bob'}) == 20
    assert total({'account_id':str(private.id)}) == 0
    assert total({'account_id':str(foreign.id)}) == 0
    assert total({'account_id':str(shared.id)}) == 20
    share = db.exec(select(AccountShare).where(AccountShare.account_id == shared.id)).one()
    share.include_in_finances = False
    db.add(share); db.commit()
    assert total({}) == 10


def test_expanded_calendar_keeps_long_range_and_converts_historical_currency(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db, 'USD')
    day = date(2025, 12, 16)
    db.add(ExchangeRateSnapshot(requested_date=day, effective_date=day, rates={'EUR':'1', 'USD':'1', 'CNY':'8'}))
    db.add(Transaction(account_id=accounts[0].id, transacted_at=day, amount=Decimal(10), currency='USD', narration='USD purchase'))
    # Neither income nor transfers require historical FX to render spending.
    db.add(Transaction(account_id=accounts[0].id, transacted_at=date(2025, 12, 17), amount=Decimal(10),
                       currency='USD', transaction_type='transfer', narration='USD transfer'))
    db.commit()
    response = auth_client_a.get('/api/v1/dashboard/spending-calendar', params={
        'start_date':'2025-01-01', 'end_date':'2026-01-04', 'minimum_weeks':3})
    assert response.status_code == 200, response.text
    calendar = response.json()
    assert calendar['start_date'] == '2025-01-01'
    assert calendar['currency'] == 'CNY'
    assert sum(c['amount'] for week in calendar['weeks'] for c in week) == 80


@pytest.mark.parametrize('extra', [
    {'minimum_weeks':0}, {'minimum_weeks':521}, {'start_date':'bad'},
    {'start_date':'2026-01-05'}, {'account_id':'bad'},
])
def test_expanded_calendar_rejects_invalid_ranges(auth_client_a, extra):
    params = {'start_date':'2026-01-01', 'end_date':'2026-01-04', **extra}
    assert auth_client_a.get('/api/v1/dashboard/spending-calendar', params=params).status_code == 422


def test_expanded_calendar_for_user_without_family_is_empty(auth_client_a):
    response = auth_client_a.get('/api/v1/dashboard/spending-calendar', params={
        'start_date':'2026-01-01', 'end_date':'2026-01-04', 'minimum_weeks':3})
    assert response.status_code == 200, response.text
    assert sum(c['amount'] for week in response.json()['weeks'] for c in week) == 0

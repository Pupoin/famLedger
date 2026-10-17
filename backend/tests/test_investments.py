"""Dated market values must conserve cashflows without becoming spending/income."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select

from models import Account, AccountShare, Family, Transaction, Transfer, User, ExchangeRateSnapshot
from services.investments import investment_summary
from services.report_currency import ReportCurrency
from test_transaction_edit_and_delete import accounts, activity, balance


@pytest.fixture
def portfolio(db, accounts):
    account = accounts[0]
    account.account_type = 'investment'
    db.add(account)
    activity(db, account, 'income', 1000, transacted_at=date(2026, 9, 1), occurred_at=datetime(2026, 9, 1, 2),
             excluded_from_stats=True, extra={'source': 'account_opening', 'is_initial': True})
    return account


def valuation(client, account, target, day=10, hour=10):
    return client.post(f'/api/v1/accounts/{account.id}/reconcile-balance', json={
        'reconciliation_type': 'investment', 'new_balance': str(target),
        'occurred_at': f'2026-09-{day:02d}T{hour:02d}:00:00+08:00'})


def summary(db, account, start=date(2026, 9, 1), end=date(2026, 9, 30), accounts=None):
    return investment_summary(db, accounts or [account], start, end, ReportCurrency(db, currency='CNY'))


def row_for(db, response):
    assert response.status_code == 200, response.text
    db.expire_all()
    return db.get(Transaction, UUID(response.json()['transaction_id']))


def test_gain_loss_and_zero_change_preserve_original_values_and_budget_isolation(auth_client_a, db, portfolio):
    first = row_for(db, valuation(auth_client_a, portfolio, 1100))
    second = row_for(db, valuation(auth_client_a, portfolio, 1050, 11))
    third = row_for(db, valuation(auth_client_a, portfolio, 1050, 12))
    assert first.amount == first.original_amount == 100 and first.extra['direction'] == 'increase'
    assert second.amount == second.original_amount == 50 and second.extra['direction'] == 'decrease'
    assert third.amount == 0 and third.excluded_from_stats
    assert balance(db, portfolio) == 1050
    # A zero change is a valuation observation, not an omitted activity.
    detail = auth_client_a.get(f'/api/v1/transactions/{third.id}')
    assert detail.status_code == 200, detail.text
    assert Decimal(detail.json()['display_amount']) == 0
    value = summary(db, portfolio)
    assert value['period_return'] == value['total_return'] == value['period_gain'] == 50


def test_historical_insert_edit_delete_reflows_later_values(auth_client_a, db, portfolio):
    first = row_for(db, valuation(auth_client_a, portfolio, 1100, 10))
    second = row_for(db, valuation(auth_client_a, portfolio, 1200, 20))
    dividend = activity(db, portfolio, 'income', 40)
    db.refresh(first); db.refresh(second)
    assert first.amount == 60 and second.amount == 100
    assert balance(db, portfolio) == 1200
    value = summary(db, portfolio)
    assert value['period_gain'] == 160 and value['cash_income'] == 40 and value['period_return'] == 200
    response = auth_client_a.patch(f'/api/v1/transactions/{dividend.id}', json={'amount': '70'})
    assert response.status_code == 200, response.text
    db.refresh(first)
    assert first.amount == 30
    response = auth_client_a.delete(f'/api/v1/transactions/{dividend.id}')
    assert response.status_code == 200, response.text
    db.refresh(first); db.refresh(second)
    assert first.amount == second.amount == 100
    assert balance(db, portfolio) == 1200


def test_delete_anchor_recalculates_next_and_delete_latest_restores_cash_balance(auth_client_a, db, portfolio):
    first = row_for(db, valuation(auth_client_a, portfolio, 1100, 10))
    second = row_for(db, valuation(auth_client_a, portfolio, 1200, 20))
    assert auth_client_a.delete(f'/api/v1/transactions/{first.id}').status_code == 200
    db.refresh(second)
    assert second.amount == 200 and balance(db, portfolio) == 1200
    assert auth_client_a.delete(f'/api/v1/transactions/{second.id}').status_code == 200
    assert balance(db, portfolio) == 1000
    assert summary(db, portfolio)['period_return'] is None


def test_backdating_values_and_correction_use_instant_not_current_balance(auth_client_a, db, portfolio):
    later = row_for(db, valuation(auth_client_a, portfolio, 1300, 20))
    earlier = row_for(db, valuation(auth_client_a, portfolio, 1100, 10))
    db.refresh(later)
    assert earlier.amount == 100 and later.amount == 200
    # Moving/editing an earlier valuation keeps later target values fixed.
    response = auth_client_a.patch(f'/api/v1/transactions/{earlier.id}', json={
        'valuation_amount': '1150', 'occurred_at': '2026-09-12T10:00:00+08:00'})
    assert response.status_code == 200, response.text
    db.refresh(later)
    assert later.amount == 150 and balance(db, portfolio) == 1300
    assert summary(db, portfolio, end=date(2026, 9, 11))['portfolio_value'] == 1000


def test_duplicate_same_instant_updates_one_anchor_and_same_day_uses_time(auth_client_a, db, portfolio):
    first = row_for(db, valuation(auth_client_a, portfolio, 1100))
    repeated = row_for(db, valuation(auth_client_a, portfolio, 1120))
    assert first.id == repeated.id
    second = row_for(db, valuation(auth_client_a, portfolio, 1150, hour=12))
    assert second.amount == 30
    response = auth_client_a.patch(f'/api/v1/transactions/{second.id}', json={'occurred_at': '2026-09-10T10:00:00+08:00'})
    assert response.status_code == 409, response.text
    assert balance(db, portfolio) == 1150


@pytest.mark.parametrize('payload', [
    {'amount':'999'}, {'transaction_type':'income'}, {'excluded_from_stats':False},
    {'currency':'USD'}, {'category_id':None}, {'is_reimbursable':True},
])
def test_derived_gain_cannot_be_edited_as_cashflow(auth_client_a, db, portfolio, payload):
    row = row_for(db, valuation(auth_client_a, portfolio, 1100))
    response = auth_client_a.patch(f'/api/v1/transactions/{row.id}', json=payload)
    assert response.status_code == 400, response.text
    assert balance(db, portfolio) == 1100


def test_valuation_cannot_be_changed_through_reimbursement_or_forged_post(auth_client_a, db, portfolio):
    row = row_for(db, valuation(auth_client_a, portfolio, 1100))
    assert auth_client_a.patch(f'/api/v1/transactions/{row.id}/reimbursement', json={'excluded_from_stats':False}).status_code == 400
    response = auth_client_a.post('/api/v1/transactions', json={'account':str(portfolio.id), 'amount':'100',
        'currency':'CNY', 'transaction_type':'income', 'narration':'forged value',
        'transacted_at':'2026-09-09', 'extra':{'source':'investment_valuation','target_balance':'9999'}})
    assert response.status_code == 400, response.text


@pytest.mark.parametrize('target', ['-1', 'NaN', 'Infinity', '1000000000000000'])
def test_invalid_targets_are_rejected(auth_client_a, db, portfolio, target):
    response = valuation(auth_client_a, portfolio, target)
    assert response.status_code == 422, response.text
    assert balance(db, portfolio) == 1000


def test_future_and_before_opening_values_are_rejected(auth_client_a, db, portfolio):
    response = auth_client_a.post(f'/api/v1/accounts/{portfolio.id}/reconcile-balance', json={
        'reconciliation_type':'investment', 'new_balance':'2000', 'occurred_at':'2999-01-01T00:00:00+08:00'})
    assert response.status_code == 422
    assert valuation(auth_client_a, portfolio, 1000, day=1, hour=9).status_code == 422
    assert balance(db, portfolio) == 1000


def test_moving_opening_past_a_value_cannot_add_the_opening_twice(auth_client_a, db, portfolio):
    row_for(db, valuation(auth_client_a, portfolio, 1100))
    opening=db.exec(select(Transaction).where(Transaction.account_id==portfolio.id, Transaction.transaction_type=='income')).one()
    response=auth_client_a.patch(f'/api/v1/transactions/{opening.id}', json={'occurred_at':'2026-09-15T10:00:00+08:00'})
    assert response.status_code == 422, response.text
    assert balance(db, portfolio) == 1100


def test_permissions_and_account_type_are_enforced(auth_client_a, auth_client_b, db, accounts, portfolio):
    response = valuation(auth_client_b, portfolio, 9999)
    assert response.status_code == 403
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    db.add(AccountShare(account_id=portfolio.id, user_id=bob.id, permission='read_only')); db.commit()
    assert valuation(auth_client_b, portfolio, 9999).status_code == 403
    share = db.exec(select(AccountShare).where(AccountShare.account_id==portfolio.id)).one()
    share.permission='read_write'; db.add(share); db.commit()
    row_for(db, valuation(auth_client_b, portfolio, 1100))
    accounts[1].name='Investment securities'; db.add(accounts[1]); db.commit()
    assert valuation(auth_client_a, accounts[1], 1000).status_code == 400
    other = Family(name='Other household'); db.add(other); db.flush()
    bob.family_id=other.id; db.add(bob); db.commit()
    assert valuation(auth_client_b, portfolio, 9999).status_code == 403


def test_missing_values_are_not_reported_as_zero_return_and_first_value_is_a_baseline(auth_client_a, db, accounts):
    account=accounts[0]; account.account_type='investment'; db.add(account); db.commit()
    assert summary(db, account)['period_return'] is None
    row=row_for(db, valuation(auth_client_a, account, 10000))
    assert row.extra['valuation_baseline'] is True
    value=summary(db, account)
    assert value['portfolio_value'] == 10000 and value['period_return'] is None and value['period_gain'] == 0
    row_for(db, valuation(auth_client_a, account, 11000, day=20))
    assert summary(db, account)['period_gain'] == 1000
    assert summary(db, account, start=date(2026,9,11))['period_return'] == 1000


def test_internal_portfolio_transfers_not_counted_as_deposits_or_withdrawals(auth_client_a, db, accounts, portfolio):
    other=accounts[1]; other.account_type='investment'; db.add(other); db.commit()
    outgoing=activity(db, portfolio, 'transfer', 200, extra={'direction':'outflow'})
    incoming=activity(db, other, 'transfer', 200, extra={'direction':'inflow'})
    pair=Transfer(family_id=portfolio.family_id, outflow_transaction_id=outgoing.id, inflow_transaction_id=incoming.id, amount=Decimal(200))
    db.add(pair); db.flush(); outgoing.transfer_id=incoming.transfer_id=pair.id
    db.add_all([outgoing,incoming]); db.commit()
    row_for(db, valuation(auth_client_a, portfolio, 900))
    row_for(db, valuation(auth_client_a, other, 250))
    value=summary(db, portfolio, accounts=[portfolio,other])
    assert value['period_deposit'] == value['period_withdrawal'] == 0
    assert value['period_return'] == 150 and value['portfolio_value'] == 1150
    assert summary(db, portfolio)['period_withdrawal'] == 200


def test_reports_agree_and_float_gain_does_not_spend_budget_or_become_income(auth_client_a, db, portfolio):
    row_for(db, valuation(auth_client_a, portfolio, 1100))
    activity(db, portfolio, 'income', 30, transacted_at=date(2026,9,11), occurred_at=datetime(2026,9,11,2))
    activity(db, portfolio, 'expense', 10, transacted_at=date(2026,9,12), occurred_at=datetime(2026,9,12,2))
    row_for(db, valuation(auth_client_a, portfolio, 1070, day=20))
    query='?period=monthly&selected_month=2026-09'
    dashboard=auth_client_a.get('/api/v1/dashboard/summary'+query)
    analytics=auth_client_a.get('/api/v1/analytics/report'+query)
    budget=auth_client_a.get('/api/v1/budgets/summary?month=2026-09')
    assert dashboard.status_code == analytics.status_code == budget.status_code == 200, (dashboard.text,analytics.text,budget.text)
    sections=[dashboard.json()['investment'],analytics.json()['investments'],budget.json()['investment']]
    for value in sections:
        assert value['period_return'] == 70 and value['period_gain'] == 50
        assert value['portfolio_value'] == 1070 and value['cash_income'] == 30 and value['cash_cost'] == 10
    assert budget.json()['total_spent'] == 10 and budget.json()['earned_income'] == 30


def test_private_and_cross_family_portfolios_do_not_leak_through_new_summaries(auth_client_a, auth_client_b, db, portfolio):
    row_for(db, valuation(auth_client_a, portfolio, 1234))
    bob=db.exec(select(User).where(User.username=='bob')).one()
    urls=[('/api/v1/dashboard/summary?selected_month=2026-09','investment'),
          ('/api/v1/analytics/report?selected_month=2026-09','investments'),
          ('/api/v1/budgets/summary?month=2026-09','investment')]
    for url,section in urls:
        response=auth_client_b.get(url)
        assert response.status_code == 200, response.text
        assert response.json()[section]['has_accounts'] is False
    # Read-only sharing permits viewing values, including inactive/report-excluded accounts.
    portfolio.is_active=False; portfolio.exclude_from_reports=True
    db.add(portfolio); db.add(AccountShare(account_id=portfolio.id,user_id=bob.id,permission='read_only')); db.commit()
    for url,section in urls:
        response=auth_client_b.get(url)
        assert response.status_code == 200, response.text
        assert response.json()[section]['portfolio_value'] == 1234
    family=Family(name='Another tenant'); db.add(family); db.flush()
    bob.family_id=family.id; db.add(bob); db.commit()
    for url,section in urls:
        response=auth_client_b.get(url)
        assert response.status_code == 200, response.text
        assert response.json()[section]['has_accounts'] is False


def test_ordinary_balance_correction_is_not_an_investment_gain(auth_client_a, db, portfolio):
    activity(db, portfolio, 'adjustment', 50, extra={'direction':'increase'}, excluded_from_stats=True)
    row_for(db, valuation(auth_client_a, portfolio, 1150))
    assert summary(db, portfolio)['period_return'] == 100
    assert balance(db, portfolio) == 1150


def test_legacy_negative_adjustment_matches_the_account_ledger(auth_client_a, db, portfolio):
    activity(db, portfolio, 'adjustment', 50, narration='Correction (-50)', extra=None, excluded_from_stats=True)
    row=row_for(db, valuation(auth_client_a, portfolio, 1150))
    assert row.amount == 200 and balance(db,portfolio)==1150
    assert summary(db,portfolio)['period_return']==200


def test_historical_fx_values_follow_dates_and_do_not_call_exchange_gain_market_gain(auth_client_a, db, portfolio):
    # Fixed native ledger value; report currency conversion uses cached historical quotes.
    db.add_all([ExchangeRateSnapshot(requested_date=date(2026,9,1),effective_date=date(2026,9,1),base_currency='EUR',rates={'EUR':1,'CNY':10,'USD':2}),
        ExchangeRateSnapshot(requested_date=date(2026,9,10),effective_date=date(2026,9,10),base_currency='EUR',rates={'EUR':1,'CNY':10,'USD':3}),
        ExchangeRateSnapshot(requested_date=date(2026,9,30),effective_date=date(2026,9,30),base_currency='EUR',rates={'EUR':1,'CNY':10,'USD':4})]); db.commit()
    row_for(db, valuation(auth_client_a, portfolio, 1100))
    value=investment_summary(db,[portfolio],date(2026,9,2),date(2026,9,30),ReportCurrency(db,currency='USD'))
    assert value['period_gain'] == 30 and value['portfolio_value'] == 440
    assert value['opening_value'] == 200 and value['period_return'] == 30

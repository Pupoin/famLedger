from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select

from models import Account, AccountShare, Family, InvestmentSetting, Transaction, User
from models import ExchangeRateSnapshot, Transfer
from services.investment_rates import xirr_log
from services.investments import investment_summary
from services.report_currency import ReportCurrency
from test_transaction_edit_and_delete import accounts, activity, balance

DAY = date(2024, 1, 1)


@pytest.fixture
def investment(db, accounts):
    account=accounts[0]; account.account_type='investment'; account.created_at=datetime(2024,1,1); db.add(account); db.commit()
    return account


def at(day, hour=10):
    return datetime.combine(day, time(hour), timezone(timedelta(hours=8))).isoformat()


def initialize(client, account, value=1000, day=DAY, **extra):
    return client.put(f'/api/v1/accounts/{account.id}/investment-settings', json={
        'mode':'baseline','target_balance':str(value),'occurred_at':at(day),**extra})


def observe(client, account, value, day, hour=10):
    response=client.post(f'/api/v1/accounts/{account.id}/reconcile-balance', json={
        'reconciliation_type':'investment','new_balance':str(value),'occurred_at':at(day,hour)})
    assert response.status_code==200,response.text
    return response


def report(db, account, start=DAY, end=None, accounts=None, currency='CNY'):
    db.expire_all()
    return investment_summary(db,accounts or [account],start,end or DAY+timedelta(days=730),ReportCurrency(db,currency=currency))['performance']


def test_two_year_single_investment_distinguishes_period_compound_and_simple(auth_client_a,db,investment):
    response=initialize(auth_client_a,investment,10000)
    assert response.status_code==200,response.text
    observe(auth_client_a,investment,12100,DAY+timedelta(days=730))
    data=report(db,investment)
    rates=data['period']['rates']
    assert rates['mwr']==rates['twr']==rates['dietz']==21
    assert rates['xirr']==rates['twr_annual']==10
    assert rates['simple_annual']==10.5
    assert data['period']['gain']==2100 and data['capital']['initial_value']==10000
    assert data['capital']['contributions']==0  # baseline market value is not historical contributed principal
    assert balance(db,investment)==12100


def test_short_period_does_not_display_an_inflated_annual_rate(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment).status_code==200
    end=DAY+timedelta(days=30)
    observe(auth_client_a,investment,1100,end)
    data=report(db,investment,end=end)['period']
    assert data['rates']['mwr']==data['rates']['twr']==10
    assert data['rates']['xirr'] is data['rates']['twr_annual'] is data['rates']['simple_annual'] is None
    assert data['reasons']['xirr']=='under_one_year'


def test_same_second_opening_microseconds_are_included_before_the_valuation(auth_client_a,db,investment):
    activity(db,investment,'income',1000,transacted_at=DAY,occurred_at=datetime(2024,1,1,2,0,0,900000),
             excluded_from_stats=True,extra={'source':'account_opening','is_initial':True})
    response=initialize(auth_client_a,investment)
    assert response.status_code==200,response.text
    assert balance(db,investment)==1000
    end=DAY+timedelta(days=365);observe(auth_client_a,investment,1100,end)
    assert report(db,investment,end=end)['period']['rates']['xirr']==10


@pytest.mark.parametrize('value_at_flow',[True,False])
def test_cashflow_dates_weight_mwr_and_exact_twr_needs_a_boundary_value(auth_client_a,db,investment,value_at_flow):
    assert initialize(auth_client_a,investment).status_code==200
    mid=DAY+timedelta(days=365); end=DAY+timedelta(days=730)
    activity(db,investment,'transfer',1000,transacted_at=mid,occurred_at=datetime.fromisoformat(at(mid)).astimezone(timezone.utc).replace(tzinfo=None),extra={'direction':'inflow'})
    if value_at_flow: observe(auth_client_a,investment,2200,mid)
    observe(auth_client_a,investment,2640,end)
    data=report(db,investment)['period']
    assert data['rates']['mwr']==44 and data['rates']['xirr']==20
    assert data['rates']['dietz']==pytest.approx(42.666667)
    assert data['rates']['simple_annual'] is None
    if value_at_flow:
        assert data['rates']['twr']==44 and data['rates']['twr_annual']==20
    else:
        assert data['rates']['twr'] is None and data['reasons']['twr']=='missing_flow_valuation'


def test_xirr_matches_microsoft_irregular_cashflow_example():
    import math
    cash=[(date(2008,1,1),-10000),(date(2008,3,1),2750),(date(2008,10,30),4250),
          (date(2009,2,15),3250),(date(2009,4,1),2750)]
    value,error=xirr_log(cash)
    assert error is None and math.expm1(value)==pytest.approx(0.373362535,abs=1e-8)


def test_multiple_irr_roots_are_not_resolved_by_arbitrarily_picking_one():
    result,error=xirr_log([(DAY,-100),(DAY+timedelta(days=365),230),(DAY+timedelta(days=730),-132)])
    assert result is None and error=='multiple_solutions'


def test_rates_require_initialization_but_carry_missing_boundary_values_with_explicit_estimates(auth_client_a,db,investment):
    data=report(db,investment)
    assert all(value is None for value in data['period']['rates'].values())
    assert data['period']['reasons']['mwr']=='not_initialized'
    assert initialize(auth_client_a,investment).status_code==200
    observe(auth_client_a,investment,1100,DAY+timedelta(days=30))
    data=report(db,investment,end=DAY+timedelta(days=60))
    assert data['period']['rates']['mwr']==10
    assert data['period']['closing_estimated'] and not data['period']['opening_estimated']
    assert data['period']['closing_reference_dates']==['2024-01-31']
    assert len(data['period_series'])==2 and data['period_series'][-1]['mwr']==10
    # A month without its own opening boundary uses the latest earlier value.
    end=DAY+timedelta(days=90); observe(auth_client_a,investment,1200,end)
    data=report(db,investment,start=DAY+timedelta(days=60),end=end)
    assert data['period']['rates']['mwr']==pytest.approx(9.090909)
    assert data['period']['opening_estimated'] and not data['period']['closing_estimated']
    assert data['period']['opening_reference_dates']==['2024-01-31']
    assert data['inception']['rates']['mwr']==20


def test_complete_history_creates_one_real_initial_capital_and_no_budget_income(auth_client_a,db,investment):
    response=auth_client_a.put(f'/api/v1/accounts/{investment.id}/investment-settings',json={
        'mode':'history','initial_amount':'1000','initial_occurred_at':at(DAY)})
    assert response.status_code==200,response.text
    observe(auth_client_a,investment,1100,DAY+timedelta(days=30))
    data=report(db,investment,end=DAY+timedelta(days=30))
    assert data['period']['rates']['mwr']==data['period']['rates']['twr']==10
    assert data['capital']['contributions']==1000 and data['capital']['initial_value']==0
    repeated=auth_client_a.put(f'/api/v1/accounts/{investment.id}/investment-settings',json={
        'mode':'history','initial_amount':'1000','initial_occurred_at':at(DAY)})
    assert repeated.status_code==409
    assert auth_client_a.put(f'/api/v1/accounts/{investment.id}/investment-settings',json={'mode':'history'}).status_code==200
    assert balance(db,investment)==1100
    budget=auth_client_a.get('/api/v1/budgets/summary?month=2024-01').json()
    assert budget['earned_income']==0 and budget['total_spent']==0


def test_missing_september_30_uses_prior_value_and_cash_without_writes_or_future_prices(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment,1000,date(2024,9,26)).status_code==200
    for day,kind,amount,extra in [
        (27,'transfer',200,{'direction':'inflow'}), (28,'income',30,{}),
        (29,'expense',10,{}), (30,'transfer',50,{'direction':'outflow'}),
    ]:
        activity(db,investment,kind,amount,transacted_at=date(2024,9,day),
                 occurred_at=datetime(2024,9,day,3),extra=extra)
    observe(auth_client_a,investment,1287,date(2024,10,17))
    observe(auth_client_a,investment,9999,date(2024,11,1))
    before={row.id:row.model_dump(mode='json') for row in db.exec(select(Transaction).where(Transaction.account_id==investment.id)).all()}
    data=report(db,investment,start=date(2024,10,1),end=date(2024,10,17))
    period=data['period']
    assert period['opening_value']==1170 and period['closing_value']==1287
    assert period['gain']==117 and period['rates']['mwr']==period['rates']['twr']==10
    assert period['estimated'] and period['opening_estimated'] and not period['closing_estimated']
    assert period['opening_reference_dates']==['2024-09-26']
    assert [row['date'] for row in data['period_series']]==['2024-10-17']
    assert data['period_series'][0]['estimated']
    after={row.id:row.model_dump(mode='json') for row in db.exec(select(Transaction).where(Transaction.account_id==investment.id)).all()}
    assert before==after  # In particular no synthetic September 30 valuation.


def test_reference_does_not_count_same_second_cash_in_a_valuation_twice(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment,1000,date(2024,9,20)).status_code==200
    activity(db,investment,'transfer',200,transacted_at=date(2024,9,26),
             occurred_at=datetime(2024,9,26,2,0,0,900000),extra={'direction':'inflow'})
    observe(auth_client_a,investment,1300,date(2024,9,26))
    activity(db,investment,'income',20,transacted_at=date(2024,9,29),occurred_at=datetime(2024,9,29,2))
    activity(db,investment,'expense',5,transacted_at=date(2024,9,30),occurred_at=datetime(2024,9,30,2))
    observe(auth_client_a,investment,'1446.50',date(2024,10,17))
    data=report(db,investment,start=date(2024,10,1),end=date(2024,10,17))['period']
    assert data['opening_value']==1315 and data['gain']==131.5
    assert data['rates']['mwr']==10 and data['opening_reference_dates']==['2024-09-26']


def test_history_before_first_valuation_can_use_recorded_capital_as_an_estimate(auth_client_a,db,investment):
    response=auth_client_a.put(f'/api/v1/accounts/{investment.id}/investment-settings',json={
        'mode':'history','initial_amount':'1000','initial_occurred_at':at(date(2024,9,1))})
    assert response.status_code==200,response.text
    activity(db,investment,'transfer',200,transacted_at=date(2024,9,20),
             occurred_at=datetime(2024,9,20,2),extra={'direction':'inflow'})
    observe(auth_client_a,investment,1320,date(2024,10,17))
    data=report(db,investment,start=date(2024,10,1),end=date(2024,10,17))['period']
    assert data['opening_value']==1200 and data['gain']==120 and data['rates']['mwr']==10
    assert data['opening_estimated'] and data['opening_from_cashflows']
    assert data['opening_reference_dates']==['2024-09-01']


def test_carried_native_value_uses_boundary_day_fx(auth_client_a,db,investment):
    previous,boundary,end=date(2024,9,26),date(2024,9,30),date(2024,10,17)
    for day,usd in [(previous,'2'),(boundary,'2.5'),(end,'3')]:
        db.add(ExchangeRateSnapshot(requested_date=day,effective_date=day,rates={'EUR':'1','CNY':'10','USD':usd}))
    db.commit()
    assert initialize(auth_client_a,investment,1000,previous).status_code==200
    observe(auth_client_a,investment,1000,end)
    data=report(db,investment,start=date(2024,10,1),end=end,currency='USD')['period']
    assert data['opening_value']==250 and data['closing_value']==300
    assert data['gain']==50 and data['rates']['mwr']==20 and data['estimated']


def test_baseline_edits_are_idempotent_and_ledger_deletion_is_reported(auth_client_a,db,investment):
    first=initialize(auth_client_a,investment).json()
    second=initialize(auth_client_a,investment,1050).json()
    assert first['baseline_transaction_id']==second['baseline_transaction_id']
    row_id=second['baseline_transaction_id']
    assert len(db.exec(select(Transaction).where(Transaction.account_id==investment.id)).all())==1
    assert auth_client_a.delete(f'/api/v1/transactions/{row_id}').status_code==200
    data=report(db,investment)
    assert data['period']['reasons']['mwr']=='baseline_deleted'


def test_changing_the_performance_start_keeps_historical_valuations(auth_client_a,db,investment):
    first=initialize(auth_client_a,investment).json()['baseline_transaction_id']
    mid=DAY+timedelta(days=30);end=DAY+timedelta(days=60)
    observe(auth_client_a,investment,1100,mid);observe(auth_client_a,investment,1210,end)
    response=initialize(auth_client_a,investment,1100,mid)
    assert response.status_code==200,response.text
    assert response.json()['baseline_transaction_id'] != first
    db.expire_all()
    assert db.get(Transaction,UUID(first)).extra['target_balance']=='1000.0000'
    assert len(db.exec(select(Transaction).where(Transaction.account_id==investment.id)).all())==3
    data=report(db,investment,end=end)
    assert data['inception']['rates']['mwr']==10
    assert balance(db,investment)==1210


def test_setup_is_full_control_only_and_private_accounts_do_not_leak(auth_client_a,auth_client_b,db,investment):
    assert initialize(auth_client_a,investment).status_code==200
    url=f'/api/v1/accounts/{investment.id}/investment-settings'
    assert auth_client_b.get(url).status_code==403
    bob=db.exec(select(User).where(User.username=='bob')).one()
    bob.role='admin';db.add(bob);db.commit()
    assert auth_client_b.get(url).status_code==403
    share=AccountShare(account_id=investment.id,user_id=bob.id,permission='read_only');db.add(share);db.commit()
    assert auth_client_b.get(url).status_code==200
    assert initialize(auth_client_b,investment).status_code==403
    share.permission='read_write';db.add(share);db.commit()
    assert initialize(auth_client_b,investment).status_code==403
    share.permission='full_control';db.add(share);db.commit()
    assert initialize(auth_client_b,investment).status_code==200
    family=Family(name='Another household');db.add(family);db.flush();bob.family_id=family.id;db.add(bob);db.commit()
    assert auth_client_b.get(url).status_code==403


def test_deleting_an_initialized_account_cleans_its_settings(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment).status_code==200
    account_id=investment.id
    response=auth_client_a.delete(f'/api/v1/accounts/{account_id}')
    assert response.status_code==200,response.text
    db.expire_all();assert db.get(InvestmentSetting,account_id) is None


def test_dividend_retained_in_value_is_counted_once_and_loss_is_supported(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment).status_code==200
    end=DAY+timedelta(days=30)
    activity(db,investment,'income',100,transacted_at=DAY+timedelta(days=10),occurred_at=datetime(2024,1,11,1))
    observe(auth_client_a,investment,1150,end)
    data=report(db,investment,end=end)
    assert data['period']['gain']==150 and data['period']['rates']['mwr']==15
    assert data['period_series'][0]['mwr']==0
    observe(auth_client_a,investment,800,end+timedelta(days=1))
    data=report(db,investment,end=end+timedelta(days=1))
    assert data['period']['rates']['mwr']==data['period']['rates']['twr']==-20


def test_all_money_lost_is_not_reported_as_zero_percent(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment).status_code==200
    end=DAY+timedelta(days=365);observe(auth_client_a,investment,0,end)
    data=report(db,investment,end=end)['period']
    assert data['rates']['mwr']==data['rates']['dietz']==data['rates']['twr']==-100
    assert data['rates']['xirr'] is None and data['reasons']['xirr']=='no_solution'


def test_withdrawals_do_not_require_dividing_by_net_principal(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment).status_code==200
    mid=DAY+timedelta(days=365);end=DAY+timedelta(days=730)
    activity(db,investment,'transfer',500,transacted_at=mid,occurred_at=datetime.fromisoformat(at(mid)).astimezone(timezone.utc).replace(tzinfo=None),extra={'direction':'outflow'})
    observe(auth_client_a,investment,700,mid);observe(auth_client_a,investment,840,end)
    data=report(db,investment)
    assert data['capital']['net_contributions']==-500
    assert data['period']['gain']==340
    assert data['period']['rates']['mwr']==data['period']['rates']['twr']==44
    assert data['period']['rates']['xirr']==20


def test_visible_portfolio_internal_transfers_cancel_and_native_account_rates_differ(auth_client_a,db,accounts,investment):
    other=accounts[1];other.account_type='investment';other.created_at=datetime(2024,1,1);db.add(other);db.commit()
    assert initialize(auth_client_a,investment).status_code==200
    assert initialize(auth_client_a,other,1000).status_code==200
    mid=DAY+timedelta(days=15);end=DAY+timedelta(days=30)
    out=activity(db,investment,'transfer',200,transacted_at=mid,occurred_at=datetime(2024,1,16,2),extra={'direction':'outflow'})
    incoming=activity(db,other,'transfer',200,transacted_at=mid,occurred_at=datetime(2024,1,16,2),extra={'direction':'inflow'})
    pair=Transfer(family_id=investment.family_id,outflow_transaction_id=out.id,inflow_transaction_id=incoming.id,amount=Decimal(200))
    db.add(pair);db.flush();out.transfer_id=incoming.transfer_id=pair.id;db.add_all([out,incoming]);db.commit()
    observe(auth_client_a,investment,900,end);observe(auth_client_a,other,1300,end)
    data=report(db,investment,end=end,accounts=[investment,other])
    assert data['capital']['contributions']==data['capital']['withdrawals']==0
    assert data['period']['gain']==200 and data['period']['rates']['mwr']==data['period']['rates']['twr']==10
    assert report(db,investment,end=end)['capital']['withdrawals']==200


def test_fx_is_included_in_display_currency_performance(auth_client_a,db,investment):
    end=DAY+timedelta(days=30)
    db.add_all([ExchangeRateSnapshot(requested_date=DAY,effective_date=DAY,rates={'EUR':'1','CNY':'10','USD':'2'}),
                ExchangeRateSnapshot(requested_date=end,effective_date=end,rates={'EUR':'1','CNY':'10','USD':'2.5'})]);db.commit()
    assert initialize(auth_client_a,investment).status_code==200
    observe(auth_client_a,investment,1000,end)
    data=report(db,investment,end=end,currency='USD')
    assert data['period']['gain']==50 and data['period']['rates']['mwr']==data['period']['rates']['twr']==25


def test_monthly_boundaries_and_deletion_recompute_rates_without_preserving_stale_points(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment).status_code==200
    jan_end=date(2024,1,31);feb_end=date(2024,2,29)
    first=observe(auth_client_a,investment,1100,jan_end)
    observe(auth_client_a,investment,1210,feb_end)
    data=report(db,investment,start=date(2024,2,1),end=feb_end)
    assert data['period']['rates']['mwr']==10 and data['inception']['rates']['mwr']==21
    assert auth_client_a.delete('/api/v1/transactions/'+first.json()['transaction_id']).status_code==200
    data=report(db,investment,start=date(2024,2,1),end=feb_end)
    assert data['period']['rates']['mwr']==21
    assert data['period']['opening_estimated']
    assert data['period']['opening_reference_dates']==['2024-01-01']
    assert data['inception']['rates']['mwr']==21
    assert len(data['inception_series'])==1


@pytest.mark.parametrize('payload',[
    {'mode':'invalid'}, {'mode':'baseline','target_balance':'-1','occurred_at':at(DAY)},
    {'mode':'baseline','target_balance':'1000','occurred_at':at(DAY),'initial_amount':'100'},
    {'mode':'history','target_balance':'1000'}, {'mode':'history','baseline_transaction_id':'forged'},
])
def test_invalid_setup_does_not_change_financial_data(auth_client_a,db,investment,payload):
    response=auth_client_a.put(f'/api/v1/accounts/{investment.id}/investment-settings',json=payload)
    assert response.status_code==422,response.text
    assert balance(db,investment)==0 and db.get(InvestmentSetting,investment.id) is None

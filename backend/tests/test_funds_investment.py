"""Money-in/out totals and drilldowns include P&L, without changing categories."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlmodel import select

from models import AccountShare, ExchangeRateSnapshot, Family, Transaction, User
from test_investments import portfolio
from test_transaction_edit_and_delete import accounts, activity


def flows(db, portfolio):
    gain=activity(db,portfolio,'adjustment',100,extra={'source':'investment_return','direction':'increase'})
    loss=activity(db,portfolio,'adjustment',40,extra={'source':'investment_return','direction':'decrease'})
    dividend=activity(db,portfolio,'income',30)
    fee=activity(db,portfolio,'expense',10)
    refund=activity(db,portfolio,'refund',2)
    return gain,loss,dividend,fee,refund


@pytest.mark.parametrize('name,kind,type_filter',[
    ('投资盈利','gain','income'),('投资盈利','gain',None),
    ('投资亏损','loss','expense,refund'),('Investment gains','gain','income'),
    ('Investment losses','loss','expense'),
])
def test_captured_broken_sankey_urls_select_pnl_without_categories(auth_client_a,auth_client_b,db,portfolio,name,kind,type_filter):
    rows=flows(db,portfolio)
    params={'category_name':name,'spending_net':'true','start_date':'2026-09-01','end_date':'2026-09-30',
            'account_id':str(portfolio.id)}
    if type_filter:params['transaction_type']=type_filter
    response=auth_client_a.get('/api/v1/transactions',params=params)
    assert response.status_code==200,response.text
    data=response.json()
    assert [row['id'] for row in data['items']]==[str(rows[0 if kind=='gain' else 1].id)]
    assert data['items'][0]['category_id'] is data['items'][0]['category_name'] is None
    assert data['funds_summary']['income' if kind=='gain' else 'expenses']==(100 if kind=='gain' else 40)
    assert auth_client_b.get('/api/v1/transactions',params=params).json()['items']==[]
    assert auth_client_a.get('/api/v1/transactions',params={**params,'start_date':'2026-09-10'}).json()['items']==[]
    assert auth_client_a.get('/api/v1/transactions',params={**params,'user':'bob'}).json()['items']==[]


def test_money_totals_and_months_include_gross_gains_losses_once(auth_client_a, db, portfolio):
    flows(db,portfolio)
    activity(db,portfolio,'transfer',500,extra={'direction':'inflow'})
    activity(db,portfolio,'adjustment',500,extra={'direction':'increase'},excluded_from_stats=True)
    data=auth_client_a.get('/api/v1/dashboard/summary?selected_month=2026-09').json()
    money=data['money_in_out']
    assert money['income']==130 and money['expenses']==48 and money['balance']==82
    assert money['cash_income']==30 and money['cash_expenses']==8
    assert money['investment_gain']==100 and money['investment_loss']==40 and money['includes_investment']
    bar=money['last_12_months'][-1]
    assert bar['ym']=='2026-09' and bar['income']==130 and bar['expense']==48
    assert bar['cash_income']==30 and bar['cash_expense']==8
    assert bar['investment_gain']==100 and bar['investment_loss']==40
    assert money['last_6_months']==money['last_12_months'][-6:]
    # Other spending charts and budget continue to exclude P&L.
    assert data['outflows']['total']==8
    budget=auth_client_a.get('/api/v1/budgets/summary?month=2026-09').json()
    assert budget['total_spent']==8 and budget['earned_income']==30


@pytest.mark.parametrize('kind,indices,income,expense',[('inflow',[0,2],130,0),('outflow',[1,3,4],0,48),('all',[0,1,2,3,4],130,48)])
def test_drilldowns_match_totals_and_do_not_include_openings_or_transfers(auth_client_a, db, portfolio, kind, indices, income, expense):
    rows=flows(db,portfolio)
    activity(db,portfolio,'transfer',999,extra={'direction':'inflow'})
    activity(db,portfolio,'income',888,excluded_from_stats=True)
    response=auth_client_a.get('/api/v1/transactions',params={'funds_flow':kind,'start_date':'2026-09-01','end_date':'2026-09-30'})
    assert response.status_code==200,response.text
    data=response.json()
    assert {row['id'] for row in data['items']}=={str(rows[index].id) for index in indices}
    assert data['funds_summary']=={'currency':'CNY','income':income,'expenses':expense,'balance':income-expense}
    assert sum(Decimal(row['funds_amount']) for row in data['items'])==income-expense
    for row in data['items']:
        if row['transaction_type']=='adjustment':
            assert row['category_id'] is row['category_name'] is None


def test_pnl_drilldown_summary_counts_all_pages_in_display_currency(auth_client_a, db, portfolio):
    gain,loss,*_=flows(db,portfolio)
    for kind,expected,total in [('gain',gain,100),('loss',loss,40)]:
        response=auth_client_a.get('/api/v1/transactions',params={'investment_activity':kind,'limit':1})
        assert response.status_code==200,response.text
        data=response.json()
        assert data['total_count']==1 and data['items'][0]['id']==str(expected.id)
        assert data['funds_summary']['income' if kind=='gain' else 'expenses']==total
    for _ in range(2):activity(db,portfolio,'adjustment',10,extra={'source':'investment_return','direction':'increase'})
    response=auth_client_a.get('/api/v1/transactions?investment_activity=gain&limit=1')
    assert response.status_code==200,response.text
    data=response.json()
    assert data['has_more'] and data['total_count']==3 and len(data['items'])==1
    assert data['funds_summary']['income']==120


def test_custom_period_summary_and_full_month_bars_keep_separate_boundaries(auth_client_a, db, portfolio):
    flows(db,portfolio)
    activity(db,portfolio,'adjustment',50,transacted_at=date(2026,9,20),occurred_at=datetime(2026,9,20,2),
             extra={'source':'investment_return','direction':'increase'})
    response=auth_client_a.get('/api/v1/dashboard/summary?period=custom&start_date=2026-09-01&end_date=2026-09-10')
    assert response.status_code==200,response.text
    money=response.json()['money_in_out']
    assert money['income']==130 and money['investment_gain']==100
    assert money['last_12_months'][-1]['income']==180 and money['last_12_months'][-1]['investment_gain']==150


def test_private_cross_family_and_readonly_scopes_match_existing_visibility(auth_client_a, auth_client_b, db, accounts, portfolio):
    gain,*_=flows(db,portfolio)
    assert auth_client_b.get('/api/v1/transactions?funds_flow=all').json()['items']==[]
    bob=db.exec(select(User).where(User.username=='bob')).one()
    db.add(AccountShare(account_id=portfolio.id,user_id=bob.id,permission='read_only'));db.commit()
    response=auth_client_b.get('/api/v1/transactions?investment_activity=gain')
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['id']==str(gain.id)
    portfolio.is_active=False;portfolio.exclude_from_reports=True;db.add(portfolio);db.commit()
    # Visible P&L stays available, cash flows follow report participation.
    response=auth_client_b.get('/api/v1/transactions?funds_flow=all')
    assert response.status_code==200,response.text
    assert response.json()['funds_summary']['income']==100 and response.json()['funds_summary']['expenses']==40
    family=Family(name='Foreign');db.add(family);db.flush();bob.family_id=family.id;db.add(bob);db.commit()
    assert auth_client_b.get('/api/v1/transactions?funds_flow=all').json()['items']==[]


def test_historical_fx_applies_once_to_gains_losses_and_drilldowns(auth_client_a, db, accounts):
    account=accounts[0];account.account_type='investment';account.currency='USD';db.add(account);db.commit()
    days=[date(2026,9,9),date(2026,9,30),date.today()]
    for day in set(days):db.add(ExchangeRateSnapshot(requested_date=day,effective_date=day,rates={'EUR':1,'USD':1,'CNY':8}))
    db.commit();flows(db,account)
    response=auth_client_a.get('/api/v1/dashboard/summary?selected_month=2026-09')
    assert response.status_code==200,response.text
    money=response.json()['money_in_out']
    assert money['income']==1040 and money['expenses']==384 and money['balance']==656
    response=auth_client_a.get('/api/v1/transactions?funds_flow=all')
    assert response.status_code==200,response.text
    assert response.json()['funds_summary']['income']==1040 and response.json()['funds_summary']['expenses']==384

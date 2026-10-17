"""A dated capital basis is metadata, never an edit or duplicate of real cash."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select

from models import Account, AccountShare, InvestmentSetting, Transaction, User
from services.investment_rates import account_ytd_returns, investment_group_ytd_returns
from services.investments import investment_summary
from services.report_currency import ReportCurrency
from test_investment_rates import investment, observe
from test_transaction_edit_and_delete import accounts, activity, balance, paired


def save(client, account, amount='800', at='2024-01-01T09:00:00+08:00', **extra):
    return client.put(f'/api/v1/accounts/{account.id}/investment-settings', json={
        'mode':'capital','capital_amount':amount,'capital_occurred_at':at,**extra})


def financial_rows(db, account_ids):
    db.expire_all()
    return {str(row.id):row.model_dump(mode='json') for row in db.exec(select(Transaction).where(Transaction.account_id.in_(account_ids))).all()}


def performance(db, account, start=date(2024,1,1), end=date(2024,1,31), members=None):
    return investment_summary(db,members or [account],start,end,ReportCurrency(db,currency='CNY'))['performance']


def opening(db, account, amount='1000', day=date(2024,1,16)):
    return activity(db,account,'income',amount,transacted_at=day,occurred_at=datetime.combine(day,datetime.min.time()),
                    excluded_from_stats=True,extra={'source':'account_opening','is_initial':True})


def test_earlier_capital_preserves_every_opening_field_and_balance(auth_client_a,db,investment):
    original=opening(db,investment)
    before=financial_rows(db,[investment.id]);before_balance=balance(db,investment)
    for _ in range(2):
        response=save(auth_client_a,investment)
        assert response.status_code==200,response.text
        assert response.json()['mode']=='capital' and Decimal(response.json()['capital_amount'])==800
        assert response.json()['capital_occurred_at'].startswith('2024-01-01T01:00:00')
        assert response.json()['initial_transaction']['id']==str(original.id)
    assert financial_rows(db,[investment.id])==before
    assert balance(db,investment)==investment.latest_balance==before_balance==1000
    result=performance(db,investment)
    assert result['inception']['rates']['mwr']==result['inception']['rates']['twr']==25
    assert result['inception']['gain']==200
    assert result['capital']['capital_basis']==800 and result['capital']['contributions']==0


def test_changing_only_the_basis_recomputes_returns_without_replaying_values(auth_client_a,db,investment):
    opening(db,investment)
    observe(auth_client_a,investment,1200,date(2024,1,31))
    before=financial_rows(db,[investment.id])
    assert save(auth_client_a,investment,'800').status_code==200
    assert performance(db,investment)['inception']['rates']['mwr']==50
    assert save(auth_client_a,investment,'1000').status_code==200
    result=performance(db,investment)
    assert result['inception']['rates']['mwr']==20 and result['inception']['gain']==200
    assert financial_rows(db,[investment.id])==before
    assert balance(db,investment)==1200


def test_no_ledger_is_created_even_with_an_unmaterialized_old_balance(auth_client_a,db,investment):
    investment.balance=Decimal(1000);investment.created_at=datetime(2024,2,1);db.add(investment);db.commit()
    assert save(auth_client_a,investment).status_code==200
    assert financial_rows(db,[investment.id])=={}
    assert balance(db,investment)==1000
    # A declared basis without observed market data is explicitly an estimate.
    result=performance(db,investment)['inception']
    assert result['closing_estimated'] and result['rates']['mwr']==0
    current=performance(db,investment,end=date.today())['inception']
    assert current['closing_value']==1000 and current['rates']['mwr']==25
    assert financial_rows(db,[investment.id])=={}


def test_post_basis_deposits_and_withdrawals_are_still_real_flows(auth_client_a,db,investment):
    opening(db,investment)
    deposit=date(2024,1,20);withdrawal=date(2024,1,25)
    activity(db,investment,'transfer',200,transacted_at=deposit,occurred_at=datetime(2024,1,20,2),extra={'direction':'inflow'})
    observe(auth_client_a,investment,1200,deposit)
    activity(db,investment,'transfer',100,transacted_at=withdrawal,occurred_at=datetime(2024,1,25,2),extra={'direction':'outflow'})
    observe(auth_client_a,investment,1100,withdrawal)
    observe(auth_client_a,investment,1200,date(2024,1,31))
    assert save(auth_client_a,investment).status_code==200
    result=performance(db,investment)
    assert result['capital']['capital_basis']==800
    assert result['capital']['contributions']==200 and result['capital']['withdrawals']==100
    assert result['inception']['gain']==300 and result['inception']['rates']['mwr']>0
    assert result['inception']['rates']['twr']==pytest.approx(36.363636)


def test_capital_basis_after_the_opening_uses_actual_prior_value_for_closing(auth_client_a,db,investment):
    opening(db,investment,day=date(2023,12,1))
    assert save(auth_client_a,investment).status_code==200
    result=performance(db,investment)['inception']
    assert result['closing_value']==1000 and result['gain']==200 and result['rates']['mwr']==25
    assert result['closing_estimated'] and result['closing_reference_dates']==['2023-12-01']


def test_first_recorded_valuation_can_supply_value_after_an_earlier_basis(auth_client_a,db,investment):
    observe(auth_client_a,investment,1000,date(2024,1,16))
    assert save(auth_client_a,investment).status_code==200
    result=performance(db,investment)['inception']
    assert result['rates']['mwr']==25 and result['reasons']['mwr'] is None
    assert result['gain']==200  # The ledger's first-value marker is no longer missing capital.


def test_sidebar_and_all_time_chart_use_the_basis_before_account_creation(auth_client_a,db,investment):
    opening(db,investment)
    assert save(auth_client_a,investment,at='2023-12-31T09:00:00+08:00').status_code==200
    result=account_ytd_returns(db,[investment],ReportCurrency(db,currency='CNY'),date(2024,1,31))[str(investment.id)]
    assert result['rate']==25
    response=auth_client_a.get(f'/api/v1/accounts/{investment.id}?period=ALL')
    assert response.status_code==200,response.text
    assert response.json()['chart']['start_iso']=='2023-12-31'
    early=performance(db,investment,start=date(2023,12,1),end=date(2023,12,15))
    assert early['period']['reasons']['mwr']=='before_start'


def test_internal_transfers_do_not_double_count_declared_portfolio_capital(auth_client_a,db,investment,accounts):
    other=accounts[1];other.account_type='investment';db.add(other);db.commit()
    opening(db,investment);opening(db,other)
    assert save(auth_client_a,investment,'1000').status_code==200
    assert save(auth_client_a,other,'1000').status_code==200
    out,incoming,pair=paired(db,accounts)
    # The pair is after the two declared bases, and remains internal to the group.
    result=investment_group_ytd_returns(db,{'all':[investment,other]},ReportCurrency(db,currency='CNY'),date(2026,9,30))['all']
    assert result['rate']==0
    assert performance(db,investment,end=date(2026,9,30),members=[investment,other])['capital']['capital_basis']==2000


@pytest.mark.parametrize('changes',[
    {'capital_amount':'0'}, {'capital_amount':'-1'}, {'capital_amount':None}, {'capital_occurred_at':None},
    {'capital_occurred_at':'2999-01-01T00:00:00+08:00'}, {'initial_amount':'100'}, {'target_balance':'100'},
    {'mode':'history'}, {'initial_transaction_id':'00000000-0000-4000-8000-000000000000'},
])
def test_invalid_basis_and_old_opening_editor_payloads_cannot_change_cash(auth_client_a,db,investment,changes):
    opening(db,investment)
    before=financial_rows(db,[investment.id])
    response=save(auth_client_a,investment,**({'amount':changes['capital_amount']} if 'capital_amount' in changes else {}),
                  **{key:value for key,value in changes.items() if key!='capital_amount'})
    assert response.status_code==422,response.text
    assert financial_rows(db,[investment.id])==before
    assert db.get(InvestmentSetting,investment.id) is None


def test_independent_basis_requires_full_control(auth_client_a,auth_client_b,db,investment):
    opening(db,investment)
    assert save(auth_client_b,investment).status_code==403
    bob=db.exec(select(User).where(User.username=='bob')).one()
    share=AccountShare(account_id=investment.id,user_id=bob.id,permission='read_write');db.add(share);db.commit()
    assert save(auth_client_b,investment).status_code==403
    share.permission='full_control';db.add(share);db.commit()
    before=financial_rows(db,[investment.id])
    assert save(auth_client_b,investment).status_code==200
    assert financial_rows(db,[investment.id])==before

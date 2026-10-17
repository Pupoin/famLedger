"""Sidebar returns preserve YTD math, dated observations and account access."""
from datetime import date, datetime

import pytest
from sqlmodel import select

from models import Account, AccountShare, Family, User
from services.investment_rates import account_ytd_returns, investment_group_ytd_returns
from services.report_currency import ReportCurrency
from test_investment_rates import initialize, observe, investment
from test_transaction_edit_and_delete import accounts, activity

START = date(2024, 1, 1)
END = date(2024, 1, 31)


def sidebar(db, rows, today=END):
    db.expire_all()
    return account_ytd_returns(db, rows, ReportCurrency(db, currency='CNY'), today)


@pytest.mark.parametrize('value,expected', [(1100, 10), (900, -10), (1000, 0)])
def test_sidebar_shows_period_return_not_annual_and_filters_by_type(auth_client_a, db, investment, accounts, value, expected):
    assert initialize(auth_client_a, investment, day=START).status_code == 200
    observe(auth_client_a, investment, value, END)
    bank = accounts[1]
    bank.name = '证券投资基金名称但实际是存款'
    db.add(bank); db.commit()
    result = sidebar(db, [investment, bank])
    assert set(result) == {str(investment.id)}
    item = result[str(investment.id)]
    assert item['rate'] == expected and item['year'] == 2024
    assert item['method'] == 'mwr' and item['as_of'] == END.isoformat()


def test_ytd_excludes_older_gains_and_does_not_pretend_the_last_value_is_today(auth_client_a, db, investment):
    assert initialize(auth_client_a, investment, day=date(2023, 7, 1)).status_code == 200
    observe(auth_client_a, investment, 2000, date(2023, 12, 31))
    observe(auth_client_a, investment, 2200, END)
    result = sidebar(db, [investment], date(2024, 2, 20))[str(investment.id)]
    assert result['rate'] == 10
    assert result['as_of'] == '2024-01-31'
    assert result['start'] == '2023-12-31'


def test_sidebar_distinguishes_missing_initialization_from_carried_value_estimates(auth_client_a, db, investment):
    result = sidebar(db, [investment])[str(investment.id)]
    assert result['rate'] is None and result['reason'] == 'not_initialized'
    assert initialize(auth_client_a, investment, day=date(2023, 7, 1)).status_code == 200
    observe(auth_client_a, investment, 1200, date(2023, 12, 31))
    result = sidebar(db, [investment])[str(investment.id)]
    assert result['rate'] == 0 and result['as_of'] is None
    assert result['reason'] is None and result['closing_estimated']
    assert result['closing_reference_dates'] == ['2023-12-31']
    # This year has a closing value but no prior-year-end observation.
    assert initialize(auth_client_a, investment, day=date(2023, 7, 1)).status_code == 200
    from models import Transaction
    old = db.exec(select(Transaction).where(Transaction.account_id == investment.id,
        Transaction.transacted_at == date(2023, 12, 31))).one()
    db.delete(old); db.commit()
    observe(auth_client_a, investment, 1300, END)
    result = sidebar(db, [investment])[str(investment.id)]
    assert result['rate'] == 30 and result['opening_estimated']
    assert result['opening_reference_dates'] == ['2023-07-01']


def test_sidebar_weights_deposits_like_account_details_and_includes_later_cash_as_an_estimate(auth_client_a, db, investment):
    assert initialize(auth_client_a, investment, day=START).status_code == 200
    activity(db, investment, 'transfer', 1000, transacted_at=date(2024, 1, 16),
        occurred_at=datetime(2024, 1, 16, 2), extra={'direction':'inflow'})
    activity(db, investment, 'income', 50, transacted_at=date(2024, 1, 20), occurred_at=datetime(2024, 1, 20, 2))
    observe(auth_client_a, investment, 2200, END)
    result = sidebar(db, [investment])[str(investment.id)]
    from services.investments import investment_summary
    details = investment_summary(db, [investment], START, END, ReportCurrency(db, currency='CNY'))
    assert result['rate'] == details['performance']['period']['rates']['mwr']
    assert 10 < result['rate'] < 20
    activity(db, investment, 'transfer', 100, transacted_at=END,
        occurred_at=datetime(2024, 1, 31, 12), extra={'direction':'inflow'})
    result = sidebar(db, [investment])[str(investment.id)]
    details = investment_summary(db, [investment], START, END, ReportCurrency(db, currency='CNY'))
    assert result['rate'] == details['performance']['period']['rates']['mwr']
    assert result['closing_estimated'] and result['closing_reference_dates'] == ['2024-01-31']
    assert details['performance']['period']['gain'] == 200


def test_batch_endpoint_includes_read_only_shares_but_no_private_or_foreign_accounts(auth_client_a, auth_client_b, db, investment):
    assert initialize(auth_client_a, investment, day=START).status_code == 200
    observe(auth_client_a, investment, 1100, END)
    url = '/api/v1/accounts/investment-returns'
    assert str(investment.id) in auth_client_a.get(url).json()['returns']
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    bob.role = 'admin'; db.add(bob); db.commit()
    assert auth_client_b.get(url).json()['returns'] == {}
    share = AccountShare(account_id=investment.id, user_id=bob.id, permission='read_only')
    db.add(share); db.commit()
    assert set(auth_client_b.get(url).json()['returns']) == {str(investment.id)}
    other = Family(name='Other tenant'); db.add(other); db.flush()
    # Even a corrupt cross-family share must not expose the foreign account.
    foreign = Account(name='Foreign investment', account_type='investment', family_id=other.id)
    db.add(foreign); db.flush()
    db.add(AccountShare(account_id=foreign.id, user_id=bob.id, permission='full_control')); db.commit()
    assert set(auth_client_b.get(url).json()['returns']) == {str(investment.id)}
    db.delete(share); db.commit()
    assert auth_client_b.get(url).json()['returns'] == {}


def test_batch_endpoint_requires_authentication(client):
    assert client.get('/api/v1/accounts/investment-returns').status_code == 401


def setup_second_investment(db, accounts):
    second = accounts[1]
    second.account_type = 'investment'
    second.created_at = datetime(2024, 1, 1)
    db.add(second); db.commit()
    return second


def test_group_return_uses_combined_cashflows_not_average_percentages(auth_client_a, db, investment, accounts):
    second = setup_second_investment(db, accounts)
    assert initialize(auth_client_a, investment, 1000, START).status_code == 200
    assert initialize(auth_client_a, second, 9000, START).status_code == 200
    observe(auth_client_a, investment, 1100, END)
    observe(auth_client_a, second, 9000, END)
    result = investment_group_ytd_returns(db, {'all':[investment,second]}, ReportCurrency(db,currency='CNY'), END)['all']
    assert result['rate'] == 1  # The individual rates are 10% and 0%.
    observe(auth_client_a, investment, 1210, date(2024, 2, 15))
    result = investment_group_ytd_returns(db, {'all':[investment,second]}, ReportCurrency(db,currency='CNY'), date(2024,2,28))['all']
    assert result['rate'] == 1 and result['as_of'] == END.isoformat()


def test_group_transfers_cancel_and_missing_profiles_do_not_report_partial_returns(auth_client_a, db, investment, accounts):
    second = setup_second_investment(db, accounts)
    assert initialize(auth_client_a, investment, 1000, START).status_code == 200
    missing = investment_group_ytd_returns(db, {'all':[investment,second]}, ReportCurrency(db,currency='CNY'), END)['all']
    assert missing['rate'] is None and missing['reason'] == 'not_initialized'
    assert initialize(auth_client_a, second, 1000, START).status_code == 200
    from models import Transfer
    out = activity(db,investment,'transfer',500,transacted_at=date(2024,1,16),occurred_at=datetime(2024,1,16,2),extra={'direction':'outflow'})
    incoming = activity(db,second,'transfer',500,transacted_at=date(2024,1,16),occurred_at=datetime(2024,1,16,2),extra={'direction':'inflow'})
    pair = Transfer(family_id=investment.family_id,outflow_transaction_id=out.id,inflow_transaction_id=incoming.id,amount=500)
    db.add(pair);db.flush();out.transfer_id=incoming.transfer_id=pair.id
    db.add_all([out,incoming]);db.commit()
    observe(auth_client_a,investment,550,END);observe(auth_client_a,second,1650,END)
    result = investment_group_ytd_returns(db, {'all':[investment,second]}, ReportCurrency(db,currency='CNY'), END)['all']
    assert result['rate'] == 10


def test_group_endpoint_validates_every_member_and_canonicalizes_keys(auth_client_a,auth_client_b,db,investment,accounts):
    second = setup_second_investment(db, accounts)
    url='/api/v1/accounts/investment-group-returns'
    raw=f'{second.id},{investment.id},{second.id}'
    key=','.join(sorted([str(second.id),str(investment.id)]))
    response=auth_client_a.get(url,params={'groups':raw})
    assert response.status_code==200,response.text
    assert set(response.json()['returns'])=={key}
    assert auth_client_b.get(url,params={'groups':raw}).status_code==403
    assert auth_client_a.get(url,params={'groups':str(accounts[2].id)}).status_code==403
    assert auth_client_a.get(url,params={'groups':'not-an-id'}).status_code==422
    assert auth_client_a.get(url).json()['returns']=={}


def test_transfer_before_the_other_accounts_baseline_does_not_create_a_false_loss(auth_client_a,db,investment,accounts):
    second=setup_second_investment(db,accounts)
    assert initialize(auth_client_a,investment,1000,START).status_code==200
    from models import Transfer
    out=activity(db,investment,'transfer',500,transacted_at=date(2024,1,16),occurred_at=datetime(2024,1,16,2),extra={'direction':'outflow'})
    incoming=activity(db,second,'transfer',500,transacted_at=date(2024,1,16),occurred_at=datetime(2024,1,16,2),extra={'direction':'inflow'})
    pair=Transfer(family_id=investment.family_id,outflow_transaction_id=out.id,inflow_transaction_id=incoming.id,amount=500)
    db.add(pair);db.flush();out.transfer_id=incoming.transfer_id=pair.id
    db.add_all([out,incoming]);db.commit()
    assert initialize(auth_client_a,second,500,date(2024,1,20)).status_code==200
    observe(auth_client_a,investment,500,END);observe(auth_client_a,second,500,END)
    result=investment_group_ytd_returns(db,{'all':[investment,second]},ReportCurrency(db,currency='CNY'),END)['all']
    assert result['rate']==0


def test_all_time_account_chart_uses_actual_history_including_before_2020(auth_client_a,db,investment):
    assert initialize(auth_client_a,investment,1000,date(2018,3,1)).status_code==200
    observe(auth_client_a,investment,1100,date(2019,3,1))
    response=auth_client_a.get(f'/api/v1/accounts/{investment.id}?period=ALL')
    assert response.status_code==200,response.text
    data=response.json()
    assert data['chart']['start_iso']=='2018-03-01'
    assert data['chart']['points'][0]['date']=='2018-03-01'
    assert data['metrics']['balance']==1100

"""Manually classified investment P&L conserves balances and reporting scope."""
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import select

from models import AccountShare, Category, Family, InvestmentSetting, Rule, Transaction, TransactionSplit, User
from services.rules.pipeline import RulePipeline
from test_investments import portfolio, summary, valuation, row_for
from test_transaction_edit_and_delete import accounts, activity, balance, paired


def convert(client, row, direction='gain', **fields):
    return client.patch(f'/api/v1/transactions/{row.id}', json={
        'transaction_type':'investment', 'investment_direction':direction, **fields})


@pytest.mark.parametrize('kind,direction,amount,expected', [('income','gain',100,1100),('expense','loss',50,950)])
def test_conversion_preserves_identity_and_money_but_removes_category(auth_client_a, db, portfolio, kind, direction, amount, expected):
    category=Category(family_id=portfolio.family_id,name='Return category',category_type=kind)
    db.add(category);db.commit()
    row=activity(db,portfolio,kind,amount,category_id=category.id,external_id=f'return-{direction}')
    before=balance(db,portfolio)
    response=convert(auth_client_a,row,direction)
    assert response.status_code==200,response.text
    data=response.json()
    assert data['id']==str(row.id) and data['external_id']==f'return-{direction}'
    assert data['category_id'] is data['category_name'] is data['category_icon'] is None
    assert data['transaction_type']=='adjustment' and data['excluded_from_stats'] is True
    assert balance(db,portfolio)==before==expected
    assert summary(db,portfolio)['period_gain']==(amount if direction=='gain' else -amount)
    items=auth_client_a.get('/api/v1/transactions',params={'category_name':'其他'}).json()['items']
    assert str(row.id) not in {item['id'] for item in items}


def test_edit_direction_amount_and_revert_to_cash_income(auth_client_a, db, portfolio):
    row=activity(db,portfolio,'income',100)
    assert convert(auth_client_a,row).status_code==200
    response=auth_client_a.patch(f'/api/v1/transactions/{row.id}',json={'investment_direction':'loss','amount':'25'})
    assert response.status_code==200,response.text
    assert balance(db,portfolio)==975
    response=auth_client_a.patch(f'/api/v1/transactions/{row.id}',json={'transaction_type':'income'})
    assert response.status_code==200,response.text
    assert balance(db,portfolio)==1025
    data=response.json()
    assert data['extra'].get('source')!='investment_return' and data['excluded_from_stats'] is False


def test_manual_return_is_measured_performance_not_an_unknown_balance_correction(auth_client_a, db, portfolio):
    db.add(InvestmentSetting(account_id=portfolio.id,mode='history'));db.commit()
    row=activity(db,portfolio,'income',100)
    assert convert(auth_client_a,row).status_code==200
    db.expire_all()
    data=summary(db,portfolio)
    assert data['performance']['period']['gain']==100
    assert data['performance']['period']['rates']['mwr']==10
    assert data['composition']=={'valuation_gain':100,'cash_income':0,'cash_cost':0,'total':100}


def test_later_absolute_value_replays_after_manual_gain_without_counting_twice(auth_client_a, db, portfolio):
    later=row_for(db,valuation(auth_client_a,portfolio,1200,day=20))
    row=activity(db,portfolio,'expense',50)
    assert convert(auth_client_a,row,'gain').status_code==200
    db.refresh(later)
    assert later.amount==150 and balance(db,portfolio)==1200
    assert summary(db,portfolio)['period_gain']==200
    assert auth_client_a.delete(f'/api/v1/transactions/{row.id}').status_code==200
    db.refresh(later)
    assert later.amount==200 and balance(db,portfolio)==1200


@pytest.mark.parametrize('extra', [{'category_id':'not-a-category'},{'is_reimbursable':True},
    {'excluded_from_stats':False},{'investment_direction':'unknown'}])
def test_return_metadata_cannot_be_used_as_spending_or_reimbursement(auth_client_a, db, portfolio, extra):
    row=activity(db,portfolio,'income',100)
    response=convert(auth_client_a,row,**extra)
    if extra=={'excluded_from_stats':False}:
        assert response.status_code==200 and response.json()['excluded_from_stats'] is True
    else:
        assert response.status_code in (400,422),response.text


def test_account_type_and_both_account_permissions_are_enforced(auth_client_a, auth_client_b, db, accounts, portfolio):
    bank=activity(db,accounts[1],'income',100)
    assert convert(auth_client_a,bank).status_code==400
    row=activity(db,portfolio,'income',100)
    assert convert(auth_client_b,row).status_code==403
    bob=db.exec(select(User).where(User.username=='bob')).one()
    share=AccountShare(account_id=portfolio.id,user_id=bob.id,permission='read_only')
    db.add(share);db.commit()
    assert convert(auth_client_b,row).status_code==403
    share.permission='read_write';db.add(share);db.commit()
    assert convert(auth_client_b,row).status_code==200
    # Existing returns cannot be moved to a non-investment account.
    response=auth_client_a.patch(f'/api/v1/transactions/{row.id}',json={'account_id':str(accounts[1].id)})
    assert response.status_code==400,response.text
    family=Family(name='Foreign');db.add(family);db.flush();bob.family_id=family.id;db.add(bob);db.commit()
    assert convert(auth_client_b,row).status_code==403


def test_opening_paired_refunded_and_split_transactions_require_unlinking(auth_client_a, db, accounts, portfolio):
    opening=db.exec(select(Transaction).where(Transaction.account_id==portfolio.id)).one()
    assert convert(auth_client_a,opening).status_code==400
    outgoing,_,_=paired(db,accounts)
    assert convert(auth_client_a,outgoing).status_code==400
    expense=activity(db,portfolio,'expense',100)
    activity(db,portfolio,'refund',10,refund_of_transaction_id=expense.id)
    assert convert(auth_client_a,expense).status_code==400
    split=activity(db,portfolio,'expense',100,is_split=True)
    db.add(TransactionSplit(transaction_id=split.id,amount=Decimal(100)));db.commit()
    assert convert(auth_client_a,split).status_code==400


def test_rules_and_reimbursement_cannot_reclassify_investment_returns(auth_client_a, db, portfolio):
    row=activity(db,portfolio,'income',100)
    assert convert(auth_client_a,row).status_code==200
    db.refresh(row)
    rule=Rule(family_id=portfolio.family_id,name='Match everything',conditions={'field':'amount','operator':'>','value':0},
              actions=[{'type':'exclude_from_statistics','value':False},{'type':'set_note','value':'Changed by rule'}])
    assert RulePipeline([rule],session=db).process_transaction(row)==[]
    assert auth_client_a.patch(f'/api/v1/transactions/{row.id}/reimbursement',json={'excluded_from_stats':False}).status_code==400
    # All ORM write paths preserve the no-category invariant.
    category=Category(family_id=portfolio.family_id,name='Other',category_type='expense');db.add(category);db.flush()
    row.category_id=category.id;row.excluded_from_stats=False;db.add(row);db.commit();db.refresh(row)
    assert row.category_id is None and row.excluded_from_stats is True


def test_reports_sankey_and_drilldowns_keep_pnl_out_of_income_spending_and_budget(auth_client_a, auth_client_b, db, portfolio):
    gain=activity(db,portfolio,'income',100);loss=activity(db,portfolio,'expense',40)
    assert convert(auth_client_a,gain).status_code==convert(auth_client_a,loss,'loss').status_code==200
    activity(db,portfolio,'income',30);activity(db,portfolio,'expense',10)
    report=auth_client_a.get('/api/v1/dashboard/summary?selected_month=2026-09')
    assert report.status_code==200,report.text
    data=report.json()
    assert data['money_in_out']['cash_income']==30 and data['money_in_out']['cash_expenses']==10
    assert data['money_in_out']['income']==130 and data['money_in_out']['expenses']==50
    assert data['investment']['period_gain']==60
    assert data['balance_sheet']['period']['change']==1080
    assert data['investment']['composition']['total']==80
    assert data['cashflow']['pool']['amount']==80 and data['cashflow']['includes_investment']
    assert [b['amount'] for b in data['cashflow']['income_sources'] if b.get('kind')=='investment']==[100]
    assert [b['amount'] for b in data['cashflow']['expense_destinations'] if b.get('kind')=='investment']==[40]
    budget=auth_client_a.get('/api/v1/budgets/summary?month=2026-09').json()
    assert budget['total_spent']==10 and budget['earned_income']==30
    for activity_kind,expected in [('gain',gain.id),('loss',loss.id)]:
        url=f'/api/v1/transactions?investment_activity={activity_kind}&start_date=2026-09-01&end_date=2026-09-30'
        response=auth_client_a.get(url)
        assert response.status_code==200,response.text
        assert [r['id'] for r in response.json()['items']]==[str(expected)]
        assert auth_client_b.get(url).json()['items']==[]


def test_inactive_shared_portfolio_drilldown_uses_same_visibility_as_summary(auth_client_b, db, portfolio):
    row=activity(db,portfolio,'adjustment',100,extra={'source':'investment_return','direction':'increase'})
    portfolio.is_active=False;portfolio.exclude_from_reports=True
    bob=db.exec(select(User).where(User.username=='bob')).one()
    db.add(portfolio);db.add(AccountShare(account_id=portfolio.id,user_id=bob.id,permission='read_only'));db.commit()
    response=auth_client_b.get('/api/v1/transactions?investment_activity=gain')
    assert response.status_code==200,response.text
    assert [r['id'] for r in response.json()['items']]==[str(row.id)]
    assert auth_client_b.get('/api/v1/transactions?investment_activity=gain&user=unknown').json()['items']==[]


def test_investment_transfer_drilldown_cancels_internal_legs_only_within_selected_portfolio(auth_client_a, db, accounts, portfolio):
    other=accounts[1];other.account_type='investment';db.add(other);db.commit()
    outgoing,incoming,_=paired(db,accounts)
    for kind,row,account in [('withdrawal',outgoing,portfolio),('deposit',incoming,other)]:
        response=auth_client_a.get(f'/api/v1/transactions?investment_activity={kind}')
        assert response.status_code==200,response.text
        assert response.json()['items']==[]
        response=auth_client_a.get(f'/api/v1/transactions?investment_activity={kind}&account_id={account.id}')
        assert response.status_code==200,response.text
        assert [r['id'] for r in response.json()['items']]==[str(row.id)]


def test_net_worth_period_respects_account_filter_and_legacy_negative_correction(auth_client_a, db, accounts, portfolio):
    activity(db,portfolio,'adjustment',50,narration='Correction (-50)',extra=None,excluded_from_stats=True)
    activity(db,accounts[1],'income',9999)
    response=auth_client_a.get(f'/api/v1/dashboard/summary?selected_month=2026-09&account_id={portfolio.id}')
    assert response.status_code==200,response.text
    data=response.json()
    assert data['balance_sheet']['net_worth']==950
    assert data['balance_sheet']['period']['closing']==950
    assert data['balance_sheet']['period']['change']==950
    assert data['investment']['portfolio_value']==950

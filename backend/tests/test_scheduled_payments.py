from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

import pytest
from sqlmodel import select

from models import Account, AccountShare, ScheduledOccurrence, ScheduledPlan, Transaction, User
from services.schedule_math import LoanConfig, occurrence_date, installment
from services.schedules import run_due


def account(client, name, kind='checking', amount='10000', currency='CNY'):
    response = client.post('/api/v1/accounts', json={'name':name,'account_type':kind,'balance':amount,'currency':currency})
    assert response.status_code == 200, response.text
    return response.json()['id']


def payload(source, target, kind='loan', **changes):
    body = dict(name='Schedule regression',kind=kind,account_id=source,destination_id=target,
                amount=100,currency='CNY',start_date='2024-01-31',frequency='monthly',interval=1,
                occurrence_limit=3,timezone_name='Asia/Shanghai',execution_mode='confirm')
    if kind == 'loan':
        body['loan'] = dict(term_months=12,interest_start_date='2023-12-31',fee=0,day_count='monthly',
            rates=[dict(effective_date='2023-12-31',annual_rate='12')],
            phases=[dict(from_period=1,method='equal_installment')])
    body.update(changes)
    return body


def create(client, body):
    response = client.post('/api/v1/plans', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def perform(client, plan, number=1, **body):
    return client.post(f'/api/v1/plans/{plan["id"]}/occurrences/{number}',json={'action':'post',**body})


def value(client, account_id):
    response = client.get(f'/api/v1/accounts/{account_id}')
    assert response.status_code == 200, response.text
    return Decimal(response.json()['account']['balance'])


def test_projection_is_read_only_and_post_splits_principal_and_interest(auth_client_a, db):
    source=account(auth_client_a,'source'); target=account(auth_client_a,'loan','loan','12000')
    before=len(db.exec(select(Transaction)).all())
    body=payload(source,target)
    preview=auth_client_a.post('/api/v1/plans/preview',json=body)
    assert preview.status_code==200,preview.text
    assert Decimal(preview.json()['occurrences'][0]['total'])==Decimal('1066.19')
    assert len(db.exec(select(Transaction)).all())==before
    plan=create(auth_client_a,body)
    assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==12000
    response=perform(auth_client_a,plan)
    assert response.status_code==200,response.text
    assert value(auth_client_a,source)==Decimal('8933.81')
    assert value(auth_client_a,target)==Decimal('11053.81')
    row=response.json()['occurrences'][0]
    assert Decimal(row['principal'])==Decimal('946.19') and Decimal(row['interest'])==120
    txns=db.exec(select(Transaction).where(Transaction.external_id.like('scheduled:%'))).all()
    expenses=[t for t in txns if t.transaction_type=='expense']
    assert sum(t.amount for t in expenses)==120
    count=len(txns)
    assert perform(auth_client_a,plan).status_code==200
    assert len(db.exec(select(Transaction).where(Transaction.external_id.like('scheduled:%'))).all())==count


def test_transfer_month_end_and_restart_idempotency(auth_client_a, db):
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    plan=create(auth_client_a,payload(source,target,'transfer',execution_mode='auto'))
    assert [r['due_date'] for r in plan['occurrences']]==['2024-01-31','2024-02-29','2024-03-31']
    run_due(db.get_bind());run_due(db.get_bind())
    assert value(auth_client_a,source)==9700 and value(auth_client_a,target)==300
    assert len(db.exec(select(ScheduledOccurrence)).all())==3
    assert len(db.exec(select(Transaction).where(Transaction.external_id.like('scheduled:%'))).all())==6


def test_future_post_rejected_and_pause_skip_preserve_balances(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    plan=create(auth_client_a,payload(source,target,'transfer',start_date='2090-01-31'))
    assert perform(auth_client_a,plan).status_code==400
    assert perform(auth_client_a,plan,action='skip').status_code==200
    assert auth_client_a.patch(f'/api/v1/plans/{plan["id"]}/status',json={'status':'paused'}).status_code==200
    assert perform(auth_client_a,plan,2).status_code==409
    assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==0


@pytest.mark.parametrize('treatment,loan_after,accrual', [('waive','11900','0'),('defer','11900','120'),('capitalize','12020','0')])
def test_principal_only_requires_explicit_interest_treatment(auth_client_a, db, treatment, loan_after, accrual):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','12000')
    body=payload(source,target); body['loan']['phases']=[{'from_period':1,'method':'principal_only','amount':100}]
    assert auth_client_a.post('/api/v1/plans',json=body).status_code==422
    body['loan']['phases'][0]['interest_treatment']=treatment
    plan=create(auth_client_a,body)
    response=perform(auth_client_a,plan);assert response.status_code==200,response.text
    assert value(auth_client_a,source)==9900
    assert value(auth_client_a,target)==Decimal(loan_after)
    saved=db.get(ScheduledPlan,uuid.UUID(plan['id']))
    if saved.accrual_account_id:
        assert value(auth_client_a,saved.accrual_account_id)==Decimal(accrual)


def test_rate_change_and_future_stage_preserve_paid_history(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','12000')
    body=payload(source,target);plan=create(auth_client_a,body)
    posted=perform(auth_client_a,plan).json()
    historical=posted['occurrences'][0]
    body['loan']['rates'].append({'effective_date':'2024-02-01','annual_rate':6})
    body['loan']['phases'].append({'from_period':4,'method':'equal_principal'})
    result=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert result.status_code==200,result.text
    assert result.json()['occurrences'][0]==historical
    assert Decimal(result.json()['occurrences'][1]['annual_rate'])==6
    body['loan']['rates'][0]['annual_rate']=7
    edited=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert edited.status_code==200,edited.text
    assert edited.json()['occurrences'][0]==historical


def test_bank_link_does_not_double_debit_and_undo_restores_import(auth_client_a, db):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','12000')
    body=payload(source,target);body['loan']['phases']=[{'from_period':1,'method':'custom','amount':1000}]
    plan=create(auth_client_a,body)
    imported=auth_client_a.post('/api/v1/transactions',json={'account':source,'amount':1000,'currency':'CNY',
        'narration':'bank loan payment','transaction_type':'expense','date':'2024-01-31','external_id':'bank-payment-1'})
    assert imported.status_code==200,imported.text
    txn_id=imported.json()['id']
    assert value(auth_client_a,source)==9000
    result=perform(auth_client_a,plan,action='link',transaction_id=txn_id)
    assert result.status_code==200,result.text
    assert value(auth_client_a,source)==9000 and value(auth_client_a,target)==11120
    assert auth_client_a.delete(f'/api/v1/transactions/{txn_id}').status_code==409
    assert perform(auth_client_a,plan,action='undo').status_code==200
    assert value(auth_client_a,source)==9000 and value(auth_client_a,target)==12000
    db.expire_all(); txn=db.get(Transaction,uuid.UUID(txn_id))
    assert txn.amount==1000 and txn.transaction_type=='expense' and txn.external_id=='bank-payment-1'


def test_auto_post_import_alias_is_idempotent(auth_client_a, db):
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    plan=create(auth_client_a,payload(source,target,'transfer'))
    assert perform(auth_client_a,plan).status_code==200
    imported={'account':source,'amount':100,'currency':'CNY','narration':'Schedule regression','date':'2024-01-31','external_id':'bank-alias'}
    assert auth_client_a.post('/api/v1/transactions',json=imported).json()['status']=='reconciled'
    assert auth_client_a.post('/api/v1/transactions',json=imported).json()['status']=='duplicate'
    assert value(auth_client_a,source)==9900 and value(auth_client_a,target)==100


def test_cross_tenant_isolation_and_revoked_sharing_stops_worker(auth_client_a, auth_client_b, db):
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    plan=create(auth_client_a,payload(source,target,'transfer',execution_mode='auto'))
    account(auth_client_b,'other')
    assert auth_client_b.get(f'/api/v1/plans/{plan["id"]}').status_code==404
    assert auth_client_b.get('/api/v1/plans').json()['items']==[]
    assert perform(auth_client_b,plan).status_code==404
    actor=db.get(User,db.get(ScheduledPlan,uuid.UUID(plan['id'])).owner_id)
    db.get(Account,uuid.UUID(source)).is_active=False;db.commit()
    run_due(db.get_bind())
    db.expire_all()
    assert db.get(ScheduledPlan,uuid.UUID(plan['id'])).status=='paused'
    assert value(auth_client_a,target)==0


def test_loan_maturity_and_advance_payment(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3;body['loan']['rates'][0]['annual_rate']=0
    plan=create(auth_client_a,body)
    assert perform(auth_client_a,plan).status_code==200
    extra=auth_client_a.post(f'/api/v1/plans/{plan["id"]}/prepay',json={'amount':100,'payment_date':'2024-02-01','strategy':'reduce_payment'})
    assert extra.status_code==200,extra.text
    assert value(auth_client_a,target)==700
    assert Decimal(extra.json()['occurrences'][1]['total'])==350
    assert perform(auth_client_a,plan,2).status_code==200
    assert perform(auth_client_a,plan,3).status_code==200
    assert value(auth_client_a,target)==0 and value(auth_client_a,source)==8800


def test_account_deletion_cleans_plan_relations(auth_client_a, db):
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    plan=create(auth_client_a,payload(source,target,'transfer'))
    assert perform(auth_client_a,plan).status_code==200
    response=auth_client_a.delete(f'/api/v1/accounts/{source}')
    assert response.status_code==200,response.text
    assert db.get(ScheduledPlan,uuid.UUID(plan['id'])) is None
    assert auth_client_a.get('/api/v1/plans').json()['items']==[]


def test_deferred_interest_survives_phase_change_until_maturity(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3
    body['loan']['phases']=[{'from_period':1,'method':'principal_only','amount':100,'interest_treatment':'defer'},
                          {'from_period':2,'method':'equal_principal'}]
    plan=create(auth_client_a,body)
    first=perform(auth_client_a,plan).json()
    assert Decimal(first['unpaid_interest'])==12
    second=perform(auth_client_a,plan,2).json()
    assert Decimal(second['unpaid_interest'])==12 and Decimal(second['occurrences'][1]['interest'])==11
    final=perform(auth_client_a,plan,3).json()
    assert Decimal(final['unpaid_interest'])==0
    assert Decimal(final['occurrences'][2]['interest'])==Decimal('17.50')
    assert value(auth_client_a,target)==0 and value(auth_client_a,source)==Decimal('8771.50')


def test_interest_only_retains_principal_and_final_balloon(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3;body['loan']['phases']=[{'from_period':1,'method':'interest_only'}]
    plan=create(auth_client_a,body)
    for period in [1,2]:
        assert perform(auth_client_a,plan,period).status_code==200
        assert value(auth_client_a,target)==1200
    assert perform(auth_client_a,plan,3).status_code==200
    assert value(auth_client_a,target)==0 and value(auth_client_a,source)==8764


def test_skipping_installment_keeps_interest_accrual(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3;body['loan']['day_count']='actual_365'
    body['loan']['phases']=[{'from_period':1,'method':'interest_only'}]
    plan=create(auth_client_a,body)
    assert perform(auth_client_a,plan,action='skip').status_code==200
    result=perform(auth_client_a,plan,2)
    assert result.status_code==200,result.text
    # 60 actual days from Dec 31 through Feb 29, including the skipped period.
    assert Decimal(result.json()['occurrences'][1]['interest'])==Decimal('23.67')
    assert value(auth_client_a,target)==1200


def test_daily_interest_uses_payment_date_and_split_rates(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3;body['loan']['day_count']='actual_365'
    body['loan']['rates'].append({'effective_date':'2024-01-16','annual_rate':6})
    body['loan']['phases']=[{'from_period':1,'method':'interest_only'}]
    plan=create(auth_client_a,body)
    first=perform(auth_client_a,plan,payment_date='2024-02-02')
    assert first.status_code==200,first.text
    # 16 days at 12%, then 17 days at 6%.
    assert Decimal(first.json()['occurrences'][0]['interest'])==Decimal('9.67')
    second=perform(auth_client_a,plan,2)
    assert Decimal(second.json()['occurrences'][1]['interest'])==Decimal('5.33')
    assert perform(auth_client_a,plan,3,payment_date='2024-01-01').status_code==422


def test_cross_currency_bank_debit_is_fixed_and_imports_both_transfer_legs(auth_client_a, db, monkeypatch):
    source=account(auth_client_a,'source',currency='CNY');target=account(auth_client_a,'loan','loan','1200','USD')
    body=payload(source,target,currency='USD');body['loan']['term_months']=3
    body['loan']['phases']=[{'from_period':1,'method':'custom','amount':500}]
    plan=create(auth_client_a,body)
    monkeypatch.setattr('services.report_currency.requests.get',lambda *a,**kw:pytest.fail('actual bank settlement needs no quote'))
    result=perform(auth_client_a,plan,bank_amount=3500)
    assert result.status_code==200,result.text
    assert value(auth_client_a,source)==6500 and value(auth_client_a,target)==712
    assert value(auth_client_a,source)==6500
    original={'account':source,'amount':3500,'currency':'CNY','narration':body['name'],
              'date':'2024-01-31','external_id':'bank-source','transaction_type':'expense'}
    assert auth_client_a.post('/api/v1/transactions',json=original).json()['status']=='reconciled'
    incoming={**original,'account':target,'amount':488,'currency':'USD','external_id':'bank-target','transaction_type':'income'}
    assert auth_client_a.post('/api/v1/transactions',json=incoming).json()['status']=='reconciled'
    for data in [original,incoming]:
        assert auth_client_a.post('/api/v1/transactions',json=data).json()['status']=='duplicate'
    assert value(auth_client_a,source)==6500 and value(auth_client_a,target)==712
    from services.data_integrity import sqlite_integrity_problems
    assert sqlite_integrity_problems(db.connection().connection.driver_connection) == []
    receipt = db.exec(select(Transaction).where(Transaction.account_id == uuid.UUID(target), Transaction.transfer_id.is_not(None))).one()
    native_amount = receipt.original_amount
    for bad_amount, bad_currency in [(native_amount + 1, 'USD'), (native_amount, None), (None, 'USD')]:
        receipt.original_amount, receipt.original_currency = bad_amount, bad_currency
        db.add(receipt)
        db.commit()
        assert 'Invalid transfer family, currency or amount' in sqlite_integrity_problems(db.connection().connection.driver_connection)
    receipt.original_amount, receipt.original_currency = native_amount, 'USD'
    db.add(receipt)
    db.commit()
    assert sqlite_integrity_problems(db.connection().connection.driver_connection) == []
    # Undo removes bank aliases along with the generated ledger entries.
    assert perform(auth_client_a,plan,action='undo').status_code==200
    assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==1200


def test_bank_native_expense_link_keeps_exact_cross_currency_debit(auth_client_a):
    source=account(auth_client_a,'source',currency='CNY');target=account(auth_client_a,'loan','loan','1200','USD')
    body=payload(source,target,currency='USD');body['loan']['term_months']=3
    body['loan']['phases']=[{'from_period':1,'method':'custom','amount':500}]
    plan=create(auth_client_a,body)
    imported=auth_client_a.post('/api/v1/transactions',json={'account':source,'amount':3525,'currency':'CNY',
        'narration':'Actual bank debit','transaction_type':'expense','date':'2024-01-31','external_id':'native-bank'})
    assert imported.status_code==200,imported.text
    result=perform(auth_client_a,plan,action='link',transaction_id=imported.json()['id'])
    assert result.status_code==200,result.text
    assert value(auth_client_a,source)==6475 and value(auth_client_a,target)==712
    assert perform(auth_client_a,plan,action='undo').status_code==200
    assert value(auth_client_a,source)==6475 and value(auth_client_a,target)==1200


def test_worker_fx_failure_is_atomic_and_retries_once(auth_client_a, db, monkeypatch):
    from services.booking_money import PendingExchangeRate
    import services.schedules as schedules
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0','USD')
    plan=create(auth_client_a,payload(source,target,'transfer',execution_mode='auto',occurrence_limit=1))
    original=schedules.prepare_booking
    def offline(session,acct,*args,**kwargs):
        if acct.currency=='USD':
            raise PendingExchangeRate('Quote unavailable')
        return original(session,acct,*args,**kwargs)
    monkeypatch.setattr(schedules,'prepare_booking',offline)
    run_due(db.get_bind())
    db.expire_all();row=db.exec(select(ScheduledOccurrence)).one()
    assert row.status=='failed' and not row.transaction_ids
    assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==0
    monkeypatch.setattr(schedules,'prepare_booking',original)
    from models import ExchangeRateSnapshot
    db.add(ExchangeRateSnapshot(requested_date=date(2024,1,31),effective_date=date(2024,1,31),
          base_currency='EUR',rates={'EUR':'1','USD':'1','CNY':'7'}));row.retry_after=None;db.add(row);db.commit()
    run_due(db.get_bind());run_due(db.get_bind())
    assert value(auth_client_a,source)==9900 and value(auth_client_a,target)==Decimal('14.2857')


def test_prepay_undo_restores_strategy_and_does_not_block_regular_payments(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3;body['loan']['rates'][0]['annual_rate']=0
    plan=create(auth_client_a,body)
    assert perform(auth_client_a,plan).status_code==200
    extra=auth_client_a.post(f'/api/v1/plans/{plan["id"]}/prepay',json={'amount':100,'payment_date':'2024-02-01','strategy':'reduce_term'})
    assert extra.status_code==200,extra.text
    assert extra.json()['config']['payment_override']['amount']=='400.00'
    assert auth_client_a.post(f'/api/v1/plans/{plan["id"]}/prepay',json={'amount':100,'payment_date':'2024-01-01','strategy':'reduce_payment'}).status_code==422
    undone=perform(auth_client_a,plan,-1,action='undo')
    assert undone.status_code==200,undone.text
    assert undone.json()['prepayments']==[] and 'payment_override' not in undone.json()['config']
    assert perform(auth_client_a,plan,2).status_code==200
    assert value(auth_client_a,target)==400


def test_read_only_shares_cannot_create_and_revocation_pauses_job(auth_client_a, auth_client_b, db):
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    alice=db.exec(select(User).where(User.username=='alice')).one()
    bob=db.exec(select(User).where(User.username=='bob')).one();bob.family_id=alice.family_id;db.add(bob)
    shares=[AccountShare(account_id=uuid.UUID(k),user_id=bob.id,permission='read_only') for k in [source,target]]
    for share in shares:db.add(share)
    db.commit()
    assert auth_client_b.post('/api/v1/plans',json=payload(source,target,'transfer')).status_code==403
    for share in shares:share.permission='read_write';db.add(share)
    db.commit()
    plan=create(auth_client_b,payload(source,target,'transfer',execution_mode='auto'))
    db.delete(shares[0]);db.commit();run_due(db.get_bind());db.expire_all()
    assert db.get(ScheduledPlan,uuid.UUID(plan['id'])).status=='paused'
    assert value(auth_client_a,source)==10000


def test_service_import_reconciliation_uses_bound_family(auth_client_a, db):
    from routes.v1_transactions import TransactionIn, ingest_transaction
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    plan=create(auth_client_a,payload(source,target,'transfer'))
    assert perform(auth_client_a,plan).status_code==200
    data=TransactionIn.model_validate(dict(account=source,amount=100,currency='CNY',narration='Schedule regression',
                       date='2024-01-31',external_id='service-import',transaction_type='expense'))
    assert ingest_transaction(data,db,'service:test')['status']=='reconciled'
    db.commit()
    assert value(auth_client_a,source)==9900


def test_dates_outside_range_and_same_currency_mismatch_rejected(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    for frequency in ['monthly','weekly']:
        assert auth_client_a.post('/api/v1/plans',json=payload(source,target,'transfer',start_date='9999-12-31',frequency=frequency)).status_code==422
    plan=create(auth_client_a,payload(source,target,'transfer'))
    assert perform(auth_client_a,plan,bank_amount=99).status_code==422
    assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==0


def test_edit_preview_keeps_paid_snapshots_and_does_not_persist_changes(auth_client_a, db):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','12000')
    body=payload(source,target);plan=create(auth_client_a,body)
    paid=perform(auth_client_a,plan).json()['occurrences'][0]
    before=len(db.exec(select(Transaction)).all())
    body['loan']['rates'].append({'effective_date':'2024-02-01','annual_rate':6})
    response=auth_client_a.post(f'/api/v1/plans/{plan["id"]}/preview',json=body)
    assert response.status_code==200,response.text
    assert response.json()['occurrences'][0]==paid
    assert Decimal(response.json()['occurrences'][1]['annual_rate'])==6
    saved=auth_client_a.get('/api/v1/plans/'+plan['id']).json()
    assert len(saved['config']['loan']['rates'])==1
    assert Decimal(saved['occurrences'][1]['annual_rate'])==12
    assert len(db.exec(select(Transaction)).all())==before


def test_plan_moves_with_owned_accounts_paused_and_historical_links_are_preserved(auth_client_a, db):
    from models import Family
    from services.tenant_migration import migrate_user_to_family
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    plan=create(auth_client_a,payload(source,target,'transfer',execution_mode='auto'))
    assert perform(auth_client_a,plan).status_code==200
    actor=db.exec(select(User).where(User.username=='alice')).one()
    family=Family(name='Moved household');db.add(family);db.commit()
    migrate_user_to_family(db,actor,family.id);db.commit();db.expire_all()
    saved=db.get(ScheduledPlan,uuid.UUID(plan['id']))
    assert saved.family_id==family.id and saved.status=='paused'
    assert perform(auth_client_a,plan,2).status_code==409
    assert value(auth_client_a,source)==9900 and value(auth_client_a,target)==100


def test_undo_auto_post_requires_confirmation_instead_of_background_reposting(auth_client_a, db):
    source=account(auth_client_a,'source');target=account(auth_client_a,'target','savings','0')
    plan=create(auth_client_a,payload(source,target,'transfer',execution_mode='auto',occurrence_limit=1))
    run_due(db.get_bind());assert value(auth_client_a,source)==9900
    undone=perform(auth_client_a,plan,action='undo')
    assert undone.status_code==200 and undone.json()['occurrences'][0]['status']=='undone'
    run_due(db.get_bind());assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==0
    assert perform(auth_client_a,plan).status_code==200
    assert value(auth_client_a,source)==9900


def test_prepayment_fixed_stage_requires_explicit_keep_schedule(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3
    body['loan']['rates'][0]['annual_rate']=0
    body['loan']['phases']=[{'from_period':1,'method':'custom','amount':300}]
    plan=create(auth_client_a,body);assert perform(auth_client_a,plan).status_code==200
    data={'amount':100,'payment_date':'2024-02-01','strategy':'reduce_payment'}
    response=auth_client_a.post('/api/v1/plans/'+plan['id']+'/prepay',json=data)
    assert response.status_code==422 and value(auth_client_a,target)==900
    data['strategy']='keep_schedule'
    response=auth_client_a.post('/api/v1/plans/'+plan['id']+'/prepay',json=data)
    assert response.status_code==200,response.text
    assert value(auth_client_a,target)==800 and Decimal(response.json()['occurrences'][1]['total'])==300


def test_interest_only_bank_link_assigns_loan_category_and_fee_without_double_debit(auth_client_a):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3;body['loan']['fee']=5
    body['loan']['phases']=[{'from_period':1,'method':'interest_only'}]
    plan=create(auth_client_a,body)
    imported=auth_client_a.post('/api/v1/transactions',json={'account':source,'amount':17,'currency':'CNY',
        'narration':'bank interest and fee','category_name':'Groceries','transaction_type':'expense','date':'2024-01-31','external_id':'interest-bank'})
    assert imported.status_code==200,imported.text
    result=perform(auth_client_a,plan,action='link',transaction_id=imported.json()['id'])
    assert result.status_code==200,result.text
    assert value(auth_client_a,source)==9983 and value(auth_client_a,target)==1200
    detail=auth_client_a.get('/api/v1/transactions/'+imported.json()['id']).json()
    assert detail['category_name']=='贷款利息' and Decimal(detail['amount'])==12
    assert Decimal(detail['scheduled_payment']['fee'])==5
    assert perform(auth_client_a,plan,action='undo').status_code==200
    restored=auth_client_a.get('/api/v1/transactions/'+imported.json()['id']).json()
    assert restored['category_name']=='Groceries' and Decimal(restored['amount'])==17


def test_transfer_cycle_edit_preserves_history_and_reschedules_pending(auth_client_a, db):
    source=account(auth_client_a,'cycle source');target=account(auth_client_a,'cycle target','savings','0')
    body=payload(source,target,'transfer');plan=create(auth_client_a,body)
    paid=perform(auth_client_a,plan).json()['occurrences'][0]
    run_due(db.get_bind(),now=datetime(2024,4,1,tzinfo=timezone.utc))
    rows=db.exec(select(ScheduledOccurrence).where(ScheduledOccurrence.plan_id==uuid.UUID(plan['id']))).all()
    before={r.number:(r.due_date,r.status,r.snapshot.copy()) for r in rows}
    body['frequency']='weekly'
    preview=auth_client_a.post(f'/api/v1/plans/{plan["id"]}/preview',json=body)
    assert preview.status_code==200,preview.text
    assert preview.json()['occurrences'][0]==paid
    assert [r['due_date'] for r in preview.json()['occurrences']]==['2024-01-31','2024-02-29','2024-03-07']
    db.expire_all()
    assert {r.number:(r.due_date,r.status,r.snapshot.copy()) for r in db.exec(select(ScheduledOccurrence)).all()}==before
    response=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert response.status_code==200,response.text
    assert response.json()['occurrences'][0]==paid
    db.expire_all()
    pending=db.exec(select(ScheduledOccurrence).where(ScheduledOccurrence.number==3)).one()
    assert pending.due_date==date(2024,3,7) and pending.status=='planned' and pending.snapshot=={}
    assert value(auth_client_a,source)==9900 and value(auth_client_a,target)==100
    body['execution_mode']='auto'
    assert auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==200
    run_due(db.get_bind(),now=datetime(2024,3,8,tzinfo=timezone.utc))
    run_due(db.get_bind(),now=datetime(2024,3,8,tzinfo=timezone.utc))
    assert value(auth_client_a,source)==9700 and value(auth_client_a,target)==300
    assert len(db.exec(select(Transaction).where(Transaction.external_id.like('scheduled:%'))).all())==6


def test_repeated_transfer_cycle_edits_keep_each_paid_date(auth_client_a):
    source=account(auth_client_a,'repeated source');target=account(auth_client_a,'repeated target','savings','0')
    body=payload(source,target,'transfer',occurrence_limit=5);plan=create(auth_client_a,body)
    first=perform(auth_client_a,plan).json()['occurrences'][0]
    body['frequency']='weekly'
    assert auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==200
    second=perform(auth_client_a,plan,2).json()['occurrences'][1]
    body['frequency']='quarterly'
    response=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert response.status_code==200,response.text
    rows=response.json()['occurrences']
    assert rows[0]==first and rows[1]==second
    assert [r['due_date'] for r in rows]==['2024-01-31','2024-02-29','2024-03-07','2024-06-07','2024-09-07']
    body['interval']=2
    response=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert response.status_code==200,response.text
    assert [r['due_date'] for r in response.json()['occurrences']]==['2024-01-31','2024-02-29','2024-03-07','2024-09-07','2025-03-07']


def test_transfer_cycle_change_keeps_skipped_and_undone_periods(auth_client_a, db):
    source=account(auth_client_a,'processed source');target=account(auth_client_a,'processed target','savings','0')
    body=payload(source,target,'transfer',occurrence_limit=4);plan=create(auth_client_a,body)
    assert perform(auth_client_a,plan,action='skip').status_code==200
    assert perform(auth_client_a,plan,2).status_code==200
    assert perform(auth_client_a,plan,2,action='undo').status_code==200
    body['frequency']='yearly';body['execution_mode']='auto'
    response=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert response.status_code==200,response.text
    rows=response.json()['occurrences']
    assert [r['due_date'] for r in rows]==['2024-01-31','2024-02-29','2024-03-31','2025-03-31']
    assert [r['status'] for r in rows[:2]]==['skipped','undone']
    run_due(db.get_bind(),now=datetime(2024,4,1,tzinfo=timezone.utc))
    assert value(auth_client_a,source)==9900 and value(auth_client_a,target)==100
    body['occurrence_limit']=1
    assert auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==409
    body['occurrence_limit']=4;body['end_date']='2024-02-01'
    assert auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==409


def test_transfer_cycle_edit_without_history_and_loan_monthly_constraint(auth_client_a, db):
    source=account(auth_client_a,'new cycle source');target=account(auth_client_a,'new cycle target','savings','0')
    body=payload(source,target,'transfer');plan=create(auth_client_a,body)
    run_due(db.get_bind(),now=datetime(2024,4,1,tzinfo=timezone.utc))
    body['frequency']='weekly';body['interval']=2
    response=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert response.status_code==200,response.text
    assert [r['due_date'] for r in response.json()['occurrences']]==['2024-01-31','2024-02-14','2024-02-28']
    loan_target=account(auth_client_a,'monthly loan','loan','1200')
    loan_body=payload(source,loan_target);loan=create(auth_client_a,loan_body)
    loan_body['frequency']='weekly'
    assert auth_client_a.put(f'/api/v1/plans/{loan["id"]}',json=loan_body).status_code==422


def test_edit_transfer_accounts_currency_dates_preserves_booking_and_bank_matching(auth_client_a, db):
    source=account(auth_client_a,'old CNY source');target=account(auth_client_a,'old CNY target','savings','0')
    body=payload(source,target,'transfer');plan=create(auth_client_a,body)
    original=perform(auth_client_a,plan).json()['occurrences'][0]
    new_source=account(auth_client_a,'new USD source',amount='1000',currency='USD')
    new_target=account(auth_client_a,'new USD target','savings','0','USD')
    body.update(name='Edited transfer',account_id=new_source,destination_id=new_target,currency='USD',amount=25,
                start_date='2024-02-15',frequency='weekly',interval=2,occurrence_limit=4,end_date='2024-03-15',timezone_name='America/New_York')
    before=len(db.exec(select(Transaction)).all())
    preview=auth_client_a.post(f'/api/v1/plans/{plan["id"]}/preview',json=body)
    assert preview.status_code==200,preview.text
    assert preview.json()['occurrences'][0]==original
    assert len(db.exec(select(Transaction)).all())==before
    assert auth_client_a.get('/api/v1/plans/'+plan['id']).json()['account_id']==source
    edited=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert edited.status_code==200,edited.text
    rows=edited.json()['occurrences'];assert rows[0]==original
    assert [r['due_date'] for r in rows]==['2024-01-31','2024-02-15','2024-02-29','2024-03-14']
    assert [r['currency'] for r in rows]==['CNY','USD','USD','USD']
    assert 'history_versions' not in edited.json()['config']
    detail=auth_client_a.get('/api/v1/transactions/'+original['transaction_ids'][0]).json()
    assert detail['scheduled_payment']['currency']=='CNY' and Decimal(detail['scheduled_payment']['total'])==100
    assert perform(auth_client_a,plan,2).status_code==200
    assert value(auth_client_a,new_source)==975 and value(auth_client_a,new_target)==25
    assert value(auth_client_a,source)==9900 and value(auth_client_a,target)==100
    imported=auth_client_a.post('/api/v1/transactions',json={'account':source,'amount':100,'currency':'CNY',
        'narration':'Schedule regression','transaction_type':'expense','date':'2024-01-31','external_id':'bank-old-after-edit'})
    assert imported.status_code==200,imported.text
    assert imported.json()['status']=='reconciled' and value(auth_client_a,source)==9900
    assert perform(auth_client_a,plan,2,action='undo').status_code==200
    assert perform(auth_client_a,plan,1,action='undo').status_code==200
    assert value(auth_client_a,source)==10000 and value(auth_client_a,new_source)==1000
    assert perform(auth_client_a,plan,1).status_code==200
    assert value(auth_client_a,source)==9900 and value(auth_client_a,target)==100
    assert value(auth_client_a,new_source)==1000 and value(auth_client_a,new_target)==0


def test_edit_all_loan_terms_after_payment_only_affects_future(auth_client_a):
    source=account(auth_client_a,'original debit');target=account(auth_client_a,'existing loan','loan','12000')
    body=payload(source,target);plan=create(auth_client_a,body)
    original=perform(auth_client_a,plan).json()['occurrences'][0]
    new_source=account(auth_client_a,'new debit')
    body.update(account_id=new_source,start_date='2024-02-15',timezone_name='Europe/London')
    body['loan'].update(term_months=6,interest_start_date='2024-01-31',day_count='actual_365',fee=3,
                        rates=[{'effective_date':'2024-01-31','annual_rate':5}],phases=[{'from_period':1,'method':'equal_principal'}])
    response=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert response.status_code==200,response.text
    data=response.json();assert data['occurrences'][0]==original
    assert data['edit_start_date']=='2024-02-15' and data['edit_from_period']==2
    future=data['occurrences'][1]
    assert Decimal(future['principal'])==Decimal('2210.76') and Decimal(future['interest'])==Decimal('22.71')
    assert Decimal(future['fee'])==3
    result=perform(auth_client_a,plan,2,payment_date='2024-02-16')
    assert result.status_code==200,result.text
    assert Decimal(result.json()['occurrences'][1]['interest'])==Decimal('24.23')
    assert result.json()['occurrences'][0]==original
    assert value(auth_client_a,source)==Decimal('8933.81')
    assert value(auth_client_a,new_source)==Decimal('7762.01')
    assert value(auth_client_a,target)==Decimal('8843.05')


def test_edit_loan_target_and_currency_preserves_original_loan_and_totals(auth_client_a, db):
    from models import Loan
    source=account(auth_client_a,'CNY debit');target=account(auth_client_a,'CNY loan','loan','12000')
    body=payload(source,target);plan=create(auth_client_a,body)
    original=perform(auth_client_a,plan).json()['occurrences'][0]
    new_source=account(auth_client_a,'USD debit',currency='USD')
    new_target=account(auth_client_a,'USD loan','loan','1200','USD')
    body.update(account_id=new_source,destination_id=new_target,currency='USD',start_date='2024-02-01')
    body['loan'].update(term_months=3,interest_start_date='2024-01-01',rates=[{'effective_date':'2024-01-01','annual_rate':0}],phases=[{'from_period':1,'method':'equal_principal'}])
    response=auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body)
    assert response.status_code==200,response.text
    data=response.json();assert data['occurrences'][0]==original
    assert Decimal(data['occurrences'][1]['principal'])==600
    assert Decimal(data['paid_totals']['principal'])==0
    assert Decimal(data['paid_totals_by_currency']['CNY']['principal'])==Decimal('946.19')
    assert db.exec(select(Loan).where(Loan.account_id==uuid.UUID(new_target))).first()
    assert perform(auth_client_a,plan,2).status_code==200
    assert value(auth_client_a,new_source)==9400 and value(auth_client_a,new_target)==600
    assert value(auth_client_a,source)==Decimal('8933.81') and value(auth_client_a,target)==Decimal('11053.81')
    assert perform(auth_client_a,plan,3).status_code==200
    assert value(auth_client_a,new_target)==0


def test_new_account_recipients_cannot_read_previous_private_plan_history(auth_client_a, auth_client_b, db):
    source=account(auth_client_a,'private old source');target=account(auth_client_a,'private old target','savings','0')
    body=payload(source,target,'transfer');plan=create(auth_client_a,body)
    assert perform(auth_client_a,plan).status_code==200
    alice=db.exec(select(User).where(User.username=='alice')).one()
    bob=db.exec(select(User).where(User.username=='bob')).one();bob.family_id=alice.family_id;db.add(bob);db.commit()
    new_source=account(auth_client_a,'shared new source');new_target=account(auth_client_a,'shared new target','savings','0')
    for key in [new_source,new_target]:db.add(AccountShare(account_id=uuid.UUID(key),user_id=bob.id,permission='read_only'))
    db.commit()
    body.update(account_id=new_source,destination_id=new_target)
    assert auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==200
    assert auth_client_b.get('/api/v1/plans/'+plan['id']).status_code==403
    assert auth_client_b.get('/api/v1/plans').json()['items']==[]
    for key in [source,target]:db.add(AccountShare(account_id=uuid.UUID(key),user_id=bob.id,permission='read_only'))
    db.commit()
    response=auth_client_b.get('/api/v1/plans/'+plan['id'])
    assert response.status_code==200 and response.json()['can_manage'] is False
    assert auth_client_b.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==403


def test_cross_family_account_edits_and_duplicate_loan_plan_are_rejected(auth_client_a, auth_client_b):
    source=account(auth_client_a,'source');target=account(auth_client_a,'loan','loan','1200')
    body=payload(source,target);plan=create(auth_client_a,body)
    foreign=account(auth_client_b,'foreign account')
    body['account_id']=foreign
    assert auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==403
    body['account_id']=source
    second_loan=account(auth_client_a,'second loan','loan','1200')
    create(auth_client_a,payload(source,second_loan))
    body['destination_id']=second_loan
    assert auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==409


def test_deleting_historical_account_cleans_edited_plan(auth_client_a, db):
    source=account(auth_client_a,'historical source');target=account(auth_client_a,'historical target','savings','0')
    body=payload(source,target,'transfer');plan=create(auth_client_a,body)
    assert perform(auth_client_a,plan).status_code==200
    new_source=account(auth_client_a,'current source');new_target=account(auth_client_a,'current target','savings','0')
    body.update(account_id=new_source,destination_id=new_target)
    assert auth_client_a.put(f'/api/v1/plans/{plan["id"]}',json=body).status_code==200
    response=auth_client_a.delete('/api/v1/accounts/'+target)
    assert response.status_code==200,response.text
    assert db.get(ScheduledPlan,uuid.UUID(plan['id'])) is None
    assert value(auth_client_a,new_source)==10000 and value(auth_client_a,new_target)==0


def test_undo_old_prepayment_after_loan_edit_removes_unused_history_context(auth_client_a, db):
    source=account(auth_client_a,'old prepaid source');target=account(auth_client_a,'old prepaid loan','loan','1200')
    body=payload(source,target,start_date='2090-01-31')
    body['loan']['rates'][0]['annual_rate']=0
    plan=create(auth_client_a,body)
    response=auth_client_a.post('/api/v1/plans/'+plan['id']+'/prepay',json={'amount':100,'payment_date':'2024-01-15','strategy':'reduce_payment'})
    assert response.status_code==200,response.text
    assert value(auth_client_a,source)==9900 and value(auth_client_a,target)==1100
    new_source=account(auth_client_a,'new prepaid source');new_target=account(auth_client_a,'new prepaid loan','loan','1200')
    body.update(account_id=new_source,destination_id=new_target,start_date='2024-02-01')
    response=auth_client_a.put('/api/v1/plans/'+plan['id'],json=body)
    assert response.status_code==200,response.text
    response=perform(auth_client_a,plan,-1,action='undo')
    assert response.status_code==200,response.text
    assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==1200
    assert value(auth_client_a,new_source)==10000 and value(auth_client_a,new_target)==1200
    db.expire_all()
    assert db.get(ScheduledPlan,uuid.UUID(plan['id'])).config['history_versions']==[]


def test_undone_previous_loan_does_not_block_edited_loan_worker(auth_client_a, db):
    source=account(auth_client_a,'undone CNY debit');target=account(auth_client_a,'undone CNY loan','loan','12000')
    body=payload(source,target);plan=create(auth_client_a,body)
    assert perform(auth_client_a,plan).status_code==200
    assert perform(auth_client_a,plan,action='undo').status_code==200
    new_source=account(auth_client_a,'active USD debit',currency='USD')
    new_target=account(auth_client_a,'active USD loan','loan','1200','USD')
    body.update(account_id=new_source,destination_id=new_target,currency='USD',start_date='2024-02-01',execution_mode='auto')
    body['loan'].update(term_months=3,interest_start_date='2024-01-01',rates=[{'effective_date':'2024-01-01','annual_rate':0}],phases=[{'from_period':1,'method':'equal_principal'}])
    response=auth_client_a.put('/api/v1/plans/'+plan['id'],json=body)
    assert response.status_code==200,response.text
    assert response.json()['next']['number']==2 and response.json()['next']['currency']=='USD'
    run_due(db.get_bind(),now=datetime(2024,2,2,tzinfo=timezone.utc))
    assert value(auth_client_a,new_source)==9400 and value(auth_client_a,new_target)==600
    assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==12000


def test_interest_free_inclusive_boundaries_and_hidden_contract_rate_changes():
    from services.schedule_math import active_rate,interest_for,next_rate_change
    config=LoanConfig.model_validate(dict(term_months=3,interest_start_date='2024-01-01',day_count='actual_365',fee=0,
        rates=[{'effective_date':'2024-01-01','annual_rate':'36.5'},{'effective_date':'2024-01-16','annual_rate':73}],
        phases=[{'from_period':1,'method':'equal_principal'}],
        interest_free_periods=[{'start_date':'2024-01-10','end_date':'2024-01-20'}]))
    assert active_rate(config,date(2024,1,20))==0
    assert active_rate(config,date(2024,1,21))==73
    assert interest_for(config,Decimal(1000),date(2024,1,1),date(2024,2,1))==31
    assert next_rate_change(config,date(2024,1,5))=={'effective_date':'2024-01-10','annual_rate':'0'}
    assert next_rate_change(config,date(2024,1,11))=={'effective_date':'2024-01-21','annual_rate':'73'}


def test_dated_interest_only_period_automatically_resumes_principal_and_interest(auth_client_a):
    source=account(auth_client_a,'dated interest source');target=account(auth_client_a,'dated interest loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=4
    body['loan']['interest_only_periods']=[{'start_date':'2024-01-31','end_date':'2024-02-29'}]
    plan=create(auth_client_a,body)
    assert [r['method'] for r in plan['occurrences']]==['interest_only','interest_only','equal_installment','equal_installment']
    assert perform(auth_client_a,plan).status_code==200
    assert perform(auth_client_a,plan,2).status_code==200
    assert value(auth_client_a,target)==1200 and value(auth_client_a,source)==9976
    third=perform(auth_client_a,plan,3)
    assert third.status_code==200,third.text
    assert Decimal(third.json()['occurrences'][2]['principal'])>0 and Decimal(third.json()['occurrences'][2]['interest'])==12
    assert value(auth_client_a,target)<1200


def test_free_and_interest_only_zero_payments_do_not_generate_fake_cashflows(auth_client_a, db):
    source=account(auth_client_a,'free source');target=account(auth_client_a,'free loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3
    body['loan']['interest_free_periods']=[{'start_date':'2023-12-31','end_date':'2024-02-29'}]
    body['loan']['interest_only_periods']=[{'start_date':'2024-01-31','end_date':'2024-02-29'}]
    plan=create(auth_client_a,body)
    assert Decimal(plan['occurrences'][0]['total'])==0
    assert perform(auth_client_a,plan).status_code==200
    assert perform(auth_client_a,plan,2).status_code==200
    assert value(auth_client_a,source)==10000 and value(auth_client_a,target)==1200
    assert len(db.exec(select(Transaction).where(Transaction.external_id.like('scheduled:%'))).all())==0
    final=perform(auth_client_a,plan,3)
    assert final.status_code==200,final.text
    row=final.json()['occurrences'][2]
    assert row['method']=='equal_installment' and Decimal(row['principal'])==1200 and Decimal(row['interest'])==Decimal('11.61')
    assert value(auth_client_a,target)==0
    assert value(auth_client_a,source)==Decimal('8788.39')
    assert len(db.exec(select(Transaction).where(Transaction.external_id.like('scheduled:%'))).all())==3


def test_zero_payment_rejects_cross_currency_bank_link_or_settlement(auth_client_a):
    source=account(auth_client_a,'zero USD source',currency='USD');target=account(auth_client_a,'zero CNY loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3
    body['loan']['interest_free_periods']=[{'start_date':'2023-12-31','end_date':'2024-02-29'}]
    body['loan']['interest_only_periods']=[{'start_date':'2024-01-31','end_date':'2024-02-29'}]
    plan=create(auth_client_a,body)
    assert perform(auth_client_a,plan,bank_amount=1).status_code==422
    imported=auth_client_a.post('/api/v1/transactions',json={'account':source,'amount':1,'currency':'USD',
        'narration':'unrelated bank expense','transaction_type':'expense','date':'2024-01-31','external_id':'zero-unrelated'})
    assert imported.status_code==200
    assert perform(auth_client_a,plan,action='link',transaction_id=imported.json()['id']).status_code==422
    assert value(auth_client_a,source)==9999 and value(auth_client_a,target)==1200
    detail=auth_client_a.get('/api/v1/transactions/'+imported.json()['id']).json()
    assert detail['scheduled_payment'] is None
    assert perform(auth_client_a,plan).status_code==200
    assert value(auth_client_a,source)==9999


def test_partial_month_free_period_and_prepayment_use_same_accrual(auth_client_a):
    source=account(auth_client_a,'partial free source');target=account(auth_client_a,'partial free loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3
    body['loan']['interest_free_periods']=[{'start_date':'2024-01-01','end_date':'2024-01-15'}]
    body['loan']['interest_only_periods']=[{'start_date':'2024-01-31','end_date':'2024-02-29'}]
    plan=create(auth_client_a,body)
    assert Decimal(plan['occurrences'][0]['interest'])==Decimal('6.19')
    data={'amount':100,'payment_date':'2024-01-16','strategy':'reduce_payment'}
    assert auth_client_a.post('/api/v1/plans/'+plan['id']+'/prepay',json=data).status_code==422
    data['strategy']='keep_schedule'
    result=auth_client_a.post('/api/v1/plans/'+plan['id']+'/prepay',json=data)
    assert result.status_code==200,result.text
    assert Decimal(result.json()['prepayments'][0]['snapshot']['interest'])==Decimal('0.39')
    assert value(auth_client_a,source)==Decimal('9899.61') and value(auth_client_a,target)==1100


@pytest.mark.parametrize('field', ['interest_free_periods','interest_only_periods'])
def test_loan_date_periods_reject_invalid_or_overlapping_ranges(auth_client_a, field):
    source=account(auth_client_a,'validation source');target=account(auth_client_a,'validation loan','loan','1200')
    body=payload(source,target)
    body['loan'][field]=[{'start_date':'2024-02-02','end_date':'2024-02-01'}]
    assert auth_client_a.post('/api/v1/plans/preview',json=body).status_code==422
    body['loan'][field]=[{'start_date':'2024-02-01','end_date':'2024-02-15'},{'start_date':'2024-02-15','end_date':'2024-02-20'}]
    assert auth_client_a.post('/api/v1/plans/preview',json=body).status_code==422
    body['loan'][field]=[{'start_date':'2024-02-01','end_date':'2024-02-15'},{'start_date':'2024-02-16','end_date':'2024-02-20'}]
    assert auth_client_a.post('/api/v1/plans/preview',json=body).status_code==200


def test_interest_only_window_requires_principal_and_interest_after_end(auth_client_a):
    source=account(auth_client_a,'resume source');target=account(auth_client_a,'resume loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=3
    body['loan']['interest_only_periods']=[{'start_date':'2024-01-31','end_date':'2024-03-31'}]
    assert auth_client_a.post('/api/v1/plans/preview',json=body).status_code==422
    body['loan']['interest_only_periods'][0]['end_date']='2024-02-29'
    body['loan']['phases']=[{'from_period':1,'method':'equal_installment'},{'from_period':3,'method':'principal_only','amount':100,'interest_treatment':'defer'}]
    assert auth_client_a.post('/api/v1/plans/preview',json=body).status_code==422
    body['loan']['phases'][1]={'from_period':3,'method':'equal_principal'}
    assert auth_client_a.post('/api/v1/plans/preview',json=body).status_code==200


def test_adding_optional_loan_periods_keeps_existing_paid_history(auth_client_a):
    source=account(auth_client_a,'period edit source');target=account(auth_client_a,'period edit loan','loan','1200')
    body=payload(source,target);body['loan']['term_months']=4
    plan=create(auth_client_a,body);paid=perform(auth_client_a,plan).json()['occurrences'][0]
    body['loan']['interest_free_periods']=[{'start_date':'2024-02-01','end_date':'2024-03-30'}]
    body['loan']['interest_only_periods']=[{'start_date':'2024-02-29','end_date':'2024-03-31'}]
    preview=auth_client_a.post('/api/v1/plans/'+plan['id']+'/preview',json=body)
    assert preview.status_code==200,preview.text
    assert preview.json()['occurrences'][0]==paid
    assert Decimal(preview.json()['occurrences'][2]['total'])==0
    result=auth_client_a.put('/api/v1/plans/'+plan['id'],json=body)
    assert result.status_code==200,result.text
    assert result.json()['occurrences'][0]==paid
    assert result.json()['occurrences'][3]['method']=='equal_installment'


def test_late_bank_payment_keeps_interest_only_phase_of_scheduled_due_date(auth_client_a):
    source=account(auth_client_a,'late interest debit');target=account(auth_client_a,'late interest loan','loan','1200')
    body=payload(source,target)
    body['loan'].update(term_months=3,day_count='actual_365',
        interest_only_periods=[{'start_date':'2024-01-31','end_date':'2024-01-31'}])
    plan=create(auth_client_a,body)
    result=perform(auth_client_a,plan,payment_date='2024-02-01')
    assert result.status_code==200,result.text
    row=result.json()['occurrences'][0]
    assert row['method']=='interest_only' and Decimal(row['principal'])==0
    assert Decimal(row['interest'])==Decimal('12.62')
    assert value(auth_client_a,target)==1200 and value(auth_client_a,source)==Decimal('9987.38')
    assert result.json()['occurrences'][1]['method']=='equal_installment'

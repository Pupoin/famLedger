"""B08/B09/B10: historical booking, pending retries and native refund quotas."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select
from models import Account, AccountShare, ExchangeRateSnapshot, PendingFxTransaction, RefundAllocation, Transaction, UserPreference
from test_fix104_regressions import setup_accounts

DAY = date.today() - timedelta(days=3)


def quote(db, day=DAY, cny='7'):
    db.add(ExchangeRateSnapshot(requested_date=day, effective_date=day, base_currency='EUR',
                               rates={'EUR': '1', 'USD': '1', 'CNY': cny}))
    db.commit()


def create(client, account, amount='100', currency='USD', **changes):
    data = dict(account=str(account.id), amount=amount, currency=currency,
                transacted_at=DAY.isoformat(), narration='Verified merchant', transaction_type='expense')
    data.update(changes)
    return client.post('/api/v1/transactions', json=data)


def test_historical_booking_fixed_and_duplicate(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db)
    quote(db)
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('cached date should not fetch'))
    response = create(auth_client_a, accounts[0], external_id='stable-100')
    assert response.status_code == 200, response.text
    result = response.json()
    assert Decimal(result['amount']) == 700 and Decimal(result['original_amount']) == 100
    assert result['currency'] == 'CNY' and result['original_currency'] == 'USD'
    repeat = create(auth_client_a, accounts[0], external_id='stable-100')
    assert repeat.json()['status'] == 'duplicate'
    for _ in range(2):
        detail = auth_client_a.get(f"/api/v1/transactions/{result['id']}")
        assert Decimal(detail.json()['amount']) == 700
        balance = auth_client_a.get(f'/api/v1/accounts/{accounts[0].id}')
        assert Decimal(balance.json()['account']['balance']) == -700
    edit = auth_client_a.patch(f"/api/v1/transactions/{result['id']}", json={'notes': 'Note only'})
    assert edit.status_code == 200 and Decimal(edit.json()['amount']) == 700


def test_repeated_external_id_does_not_overwrite_changed_payload(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    first = create(auth_client_a, accounts[0], amount='12', currency='CNY', external_id='do-not-overwrite',
                   narration='Original purchase', notes='Keep this note', extra={'marker': 'original'})
    assert first.status_code == 200, first.text
    original_id = first.json()['id']
    repeat = create(auth_client_a, accounts[0], amount='999', currency='CNY', external_id='do-not-overwrite',
                    narration='Changed name', transaction_type='income', notes='Changed note', extra={'marker': 'changed'})
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()['status'] == 'duplicate'
    assert repeat.json()['id'] == original_id
    db.expire_all()
    original = db.get(Transaction, UUID(original_id))
    assert original.amount == Decimal('12')
    assert original.narration == 'Original purchase'
    assert original.notes == 'Keep this note'
    assert original.transaction_type == 'expense'
    assert original.extra['marker'] == 'original'
    assert len(db.exec(select(Transaction).where(Transaction.account_id == accounts[0].id)).all()) == 1


def test_external_id_is_optional_and_unique_per_account(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    a = create(auth_client_a, accounts[0], amount='12', currency='CNY', external_id='same-source')
    b = create(auth_client_a, accounts[1], amount='12', currency='CNY', external_id='same-source')
    assert a.status_code == b.status_code == 200
    assert a.json()['id'] != b.json()['id']
    without_id = [create(auth_client_a, accounts[0], amount='12', currency='CNY') for _ in range(2)]
    assert all(response.status_code == 200 for response in without_id)
    assert without_id[0].json()['id'] != without_id[1].json()['id']
    assert all(response.json()['external_id'] is None for response in without_id)


def test_actual_bank_settlement_needs_no_network(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db)
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a, **k: pytest.fail('bank amount must win'))
    response = create(auth_client_a, accounts[0], settlement_amount='705', settlement_currency='CNY')
    assert response.status_code == 200, response.text
    result = response.json()
    assert Decimal(result['amount']) == 705 and Decimal(result['exchange_rate']) == Decimal('7.05')
    assert result['exchange_rate_source'] == 'bank'


def fail_quotes(*args, **kwargs):
    import requests
    raise requests.ConnectionError('offline')


def test_pending_is_not_ledger_confirm_once_and_cancel(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db)
    monkeypatch.setattr('services.report_currency.requests.get', fail_quotes)
    response = create(auth_client_a, accounts[0], external_id='pending-1')
    assert response.status_code == 200, response.text
    pending = response.json()
    assert pending['status'] == 'pending_fx'
    assert not db.exec(select(Transaction)).all()
    assert len(db.exec(select(PendingFxTransaction)).all()) == 1
    duplicate = create(auth_client_a, accounts[0], external_id='pending-1').json()
    assert duplicate['id'] == pending['id'] and duplicate['duplicate']
    retry = auth_client_a.post(f"/api/v1/pending-transactions/{pending['id']}/retry")
    assert retry.status_code == 200 and retry.json()['status'] == 'pending_fx', retry.text
    confirmed = auth_client_a.post(f"/api/v1/pending-transactions/{pending['id']}/confirm", json={'settlement_amount': '702', 'settlement_currency': 'CNY'})
    assert confirmed.status_code == 200 and confirmed.json()['status'] == 'created', confirmed.text
    assert Decimal(confirmed.json()['amount']) == 702
    repeated = auth_client_a.post(f"/api/v1/pending-transactions/{pending['id']}/confirm", json={'settlement_amount': '799', 'settlement_currency': 'CNY'})
    assert repeated.status_code == 200 and repeated.json()['status'] == 'posted'
    db.expire_all()
    assert len(db.exec(select(Transaction)).all()) == 1
    assert db.exec(select(Transaction)).one().amount == 702
    another = create(auth_client_a, accounts[0], external_id='cancel-1').json()
    canceled = auth_client_a.post(f"/api/v1/pending-transactions/{another['id']}/cancel")
    assert canceled.status_code == 200
    assert create(auth_client_a, accounts[0], external_id='cancel-1').json()['status'] == 'canceled'
    assert auth_client_a.post(f"/api/v1/pending-transactions/{another['id']}/retry").json()['status'] == 'canceled'
    assert len(db.exec(select(Transaction)).all()) == 1


def test_full_native_refund_cash_and_fx_are_separate(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = create(auth_client_a, accounts[0], settlement_amount='700', settlement_currency='CNY').json()
    response = create(auth_client_a, accounts[0], transaction_type='refund', narration='Verified merchant refund',
                      settlement_amount='720', settlement_currency='CNY', refund_of_transaction_id=expense['id'])
    assert response.status_code == 200, response.text
    refund = response.json()
    allocation = db.exec(select(RefundAllocation)).one()
    assert allocation.allocated_amount == 100 and allocation.original_book_amount == 700
    assert allocation.refund_book_amount == 720 and allocation.fx_difference_amount == 20
    detail = auth_client_a.get(f"/api/v1/transactions/{expense['id']}").json()
    assert Decimal(detail['refund_info']['total_refunded']) == 100
    assert detail['refund_info']['currency'] == 'USD'
    summary = auth_client_a.get('/api/v1/dashboard/summary?period=ALL')
    assert summary.status_code == 200, summary.text
    assert summary.json()['outflows']['total'] == 0
    assert summary.json()['fx_gain'] == 20 and summary.json()['actual_refund_amount'] == 720
    assert summary.json()['money_in_out']['balance'] == 20
    report = auth_client_a.get('/api/v1/analytics/report?selected_month=' + DAY.strftime('%Y-%m'))
    assert report.status_code == 200, report.text
    data = report.json()
    monthly = data['trends']['monthly_breakdown'][-1]
    assert data['kpis']['net_savings'] == monthly['net'] == 20
    assert monthly['expense'] == 0 and monthly['fx_gain'] == 20 and monthly['fx_loss'] == 0
    assert monthly['savings_rate'] == '0.0%'
    assert Decimal(auth_client_a.get(f'/api/v1/accounts/{accounts[0].id}').json()['account']['balance']) == 20
    assert auth_client_a.patch(f"/api/v1/transactions/{expense['id']}", json={'amount': '800'}).status_code == 400
    assert len(db.exec(select(Transaction)).all()) == 2


def test_refund_fx_in_display_currency_conserves_reported_cash(auth_client_a, db):
    _, alice, _, accounts = setup_accounts(db)
    pref = db.exec(select(UserPreference).where(UserPreference.username == alice.username)).first()
    pref = pref or UserPreference(username=alice.username)
    pref.currency = 'USD'
    db.add(pref); db.commit()
    for day, rate in {date(2020, 7, 10): '7', date(2020, 7, 11): '8', date(2020, 7, 31): '8', date.today(): '8'}.items():
        quote(db, day, rate)
    expense = create(auth_client_a, accounts[0], transacted_at='2020-07-10', settlement_amount='700', settlement_currency='CNY').json()
    refund = create(auth_client_a, accounts[0], transacted_at='2020-07-11', transaction_type='refund',
                    settlement_amount='720', settlement_currency='CNY', refund_of_transaction_id=expense['id'])
    assert refund.status_code == 200, refund.text
    report = auth_client_a.get('/api/v1/analytics/report?selected_month=2020-07')
    assert report.status_code == 200, report.text
    data = report.json()
    assert data['currency'] == 'USD'
    assert data['actual_refund_amount'] == 90 and data['spending_refund_amount'] == 100
    assert data['fx_gain'] == 0 and data['fx_loss'] == 10
    assert data['kpis']['total_expense'] == 0 and data['kpis']['net_savings'] == -10
    assert data['trends']['monthly_breakdown'][-1]['net'] == -10
    dashboard = auth_client_a.get('/api/v1/dashboard/summary?selected_month=2020-07')
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()['money_in_out']['balance'] == -10


def test_partial_refunds_original_quota_not_book_amount(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = create(auth_client_a, accounts[0], settlement_amount='700', settlement_currency='CNY').json()
    for amount, book in [('60', '432'), ('60', '438')]:
        result = create(auth_client_a, accounts[0], amount=amount, settlement_amount=book, settlement_currency='CNY',
                        transaction_type='refund', refund_of_transaction_id=expense['id'])
        assert result.status_code == 200, result.text
    rows = db.exec(select(RefundAllocation)).all()
    assert sum(r.allocated_amount for r in rows) == 100
    assert sum(r.original_book_amount for r in rows) == 700
    assert sorted(r.allocated_amount for r in rows) == [40, 60]
    extra = create(auth_client_a, accounts[0], amount='1', settlement_amount='7', settlement_currency='CNY', transaction_type='refund').json()
    over = auth_client_a.post(f"/api/v1/refunds/{extra['id']}/allocate", json={'original_transaction_id': expense['id'], 'allocated_amount':'1'})
    assert over.status_code == 400


def test_ambiguous_merchant_not_automatched(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    for _ in range(2):
        assert create(auth_client_a, accounts[0], currency='CNY').status_code == 200
    refund = create(auth_client_a, accounts[0], currency='CNY', transaction_type='refund').json()
    assert refund['status'] == 'created'
    assert not db.exec(select(RefundAllocation)).all()


def test_foreign_master_uses_fixed_activity_settlement(auth_client_a, db, monkeypatch):
    _, alice, _, accounts = setup_accounts(db)
    primary, child = accounts
    child.currency = 'USD'
    for account in accounts:
        account.account_type = 'credit_card'; account.classification = 'liability'
    child.parent_account_id = primary.id
    db.add_all(accounts); db.commit(); quote(db)
    result = create(auth_client_a, child)
    assert result.status_code == 200, result.text
    assert Decimal(result.json()['amount']) == 100
    assert Decimal(result.json()['master_settlement_amount']) == 700
    monkeypatch.setattr('services.report_currency.requests.get', fail_quotes)
    for _ in range(2):
        detail = auth_client_a.get(f'/api/v1/accounts/{primary.id}')
        assert detail.status_code == 200, detail.text
        assert Decimal(detail.json()['account']['balance']) == 700
    confirmed_refund = create(auth_client_a, child, transaction_type='refund', refund_of_transaction_id=result.json()['id'],
                              master_settlement_amount='720', master_settlement_currency='CNY')
    assert confirmed_refund.status_code == 200, confirmed_refund.text
    assert Decimal(auth_client_a.get(f'/api/v1/accounts/{primary.id}').json()['account']['balance']) == -20
    assert Decimal(auth_client_a.get(f'/api/v1/accounts/{child.id}').json()['account']['balance']) == 0


def test_pending_permissions_rechecked(auth_client_a, auth_client_b, db, monkeypatch):
    _, alice, bob, accounts = setup_accounts(db)
    monkeypatch.setattr('services.report_currency.requests.get', fail_quotes)
    pending = create(auth_client_a, accounts[0]).json()
    assert auth_client_b.get('/api/v1/pending-transactions').json()['items'] == []
    assert auth_client_b.post(f"/api/v1/pending-transactions/{pending['id']}/retry").status_code == 403
    accounts[0].is_active = False; db.add(accounts[0]); db.commit()
    response = auth_client_a.post(f"/api/v1/pending-transactions/{pending['id']}/confirm", json={'settlement_amount':'700', 'settlement_currency':'CNY'})
    assert response.status_code in (403,409)
    assert not db.exec(select(Transaction)).all()


def test_native_currency_mismatch_requires_explicit_confirmation(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = create(auth_client_a, accounts[0], settlement_amount='700', settlement_currency='CNY').json()
    refund = create(auth_client_a, accounts[0], amount='80', currency='EUR', transaction_type='refund',
                    settlement_amount='720',settlement_currency='CNY').json()
    assert not db.exec(select(RefundAllocation)).all()
    link = f"/api/v1/refunds/{refund['id']}/link/{expense['id']}"
    assert auth_client_a.post(link).status_code == 400
    confirmed = auth_client_a.post(link+'?allocated_amount=100&original_currency=USD&refund_original_amount=80')
    assert confirmed.status_code == 200, confirmed.text
    allocation = db.exec(select(RefundAllocation)).one()
    assert allocation.allocated_amount == 100 and allocation.refund_original_amount == 80
    assert allocation.fx_difference_amount == 20


def test_same_native_does_not_allow_arbitrary_ratio(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = create(auth_client_a, accounts[0], currency='CNY', narration='original').json()
    refund = create(auth_client_a, accounts[0], currency='CNY', amount='30',transaction_type='refund',narration='unlinked').json()
    response = auth_client_a.post(f"/api/v1/refunds/{refund['id']}/allocate", json={
        'original_transaction_id':expense['id'],'allocated_amount':'100','original_currency':'CNY','refund_original_amount':'30'})
    assert response.status_code == 400
    assert not db.exec(select(RefundAllocation)).all()


def test_four_decimal_refund_rounding_conserves_book_total(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = create(auth_client_a, accounts[0], amount='4',settlement_amount='0.0002',settlement_currency='CNY').json()
    for _ in range(4):
        response = create(auth_client_a, accounts[0], amount='1', transaction_type='refund',
                          settlement_amount='0.0001',settlement_currency='CNY',refund_of_transaction_id=expense['id'])
        assert response.status_code == 200, response.text
        assert sum(r.original_book_amount for r in db.exec(select(RefundAllocation)).all()) <= Decimal('0.0002')
    rows = db.exec(select(RefundAllocation)).all()
    assert sum(r.allocated_amount for r in rows) == 4
    assert sum(r.original_book_amount for r in rows) == Decimal('0.0002')


def test_rebind_foreign_master_requires_explicit_history_policy(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    primary, child = accounts
    for account in accounts:
        account.account_type='credit_card';account.classification='liability'
    child.currency='USD';db.add_all(accounts);db.commit();quote(db)
    assert create(auth_client_a, child).status_code == 200
    url=f'/api/v1/accounts/{child.id}'
    assert auth_client_a.patch(url,json={'parent_account_id':str(primary.id)}).status_code == 409
    bound=auth_client_a.patch(url,json={'parent_account_id':str(primary.id),'historical_settlement_policy':'convert_verified'})
    assert bound.status_code == 200, bound.text
    assert Decimal(auth_client_a.get(f'/api/v1/accounts/{primary.id}').json()['account']['balance']) == 700
    txn=db.exec(select(Transaction)).one();assert txn.master_settlement_amount==700
    assert auth_client_a.patch(url,json={'currency':'EUR'}).status_code == 400


def test_unverified_history_requires_manual_review_not_guessing(auth_client_a, db):
    from sqlalchemy import text
    _, _, _, accounts = setup_accounts(db)
    created=create(auth_client_a, accounts[0], currency='CNY').json()
    db.execute(text('UPDATE transactions SET original_amount=NULL,original_currency=NULL,exchange_rate=NULL,exchange_rate_date=NULL,exchange_rate_source=NULL'))
    db.commit();db.expire_all()
    detail=auth_client_a.get(f"/api/v1/transactions/{created['id']}").json()
    assert detail['needs_money_review'] and detail['original_amount'] is None
    assert auth_client_a.patch(f"/api/v1/transactions/{created['id']}",json={'amount':'101'}).status_code == 409
    confirmed=auth_client_a.patch(f"/api/v1/transactions/{created['id']}",json={
        'original_amount':'10','original_currency':'USD','settlement_amount':'100','settlement_currency':'CNY'})
    assert confirmed.status_code == 200, confirmed.text
    assert not confirmed.json()['needs_money_review'] and Decimal(confirmed.json()['amount']) == 100
    assert Decimal(confirmed.json()['original_amount']) == 10


def test_background_retry_uses_stored_creator_and_original_day(auth_client_a, db, monkeypatch):
    from routes.v1_pending_fx import retry_due_records
    _, alice, _, accounts=setup_accounts(db)
    monkeypatch.setattr('services.report_currency.requests.get',fail_quotes)
    pending=create(auth_client_a,accounts[0],external_id='worker-source').json()
    quote(db)
    retry_due_records(db.get_bind())
    db.expire_all()
    row=db.get(PendingFxTransaction,UUID(pending['id']))
    assert row.status=='posted'
    txn=db.exec(select(Transaction)).one()
    assert txn.amount==700 and txn.exchange_rate_date==DAY


def test_pending_deleted_with_account(auth_client_a, db, monkeypatch):
    from services.financial_deletion import delete_account_data
    _, _, _, accounts=setup_accounts(db)
    monkeypatch.setattr('services.report_currency.requests.get',fail_quotes)
    assert create(auth_client_a,accounts[0]).json()['status']=='pending_fx'
    delete_account_data(db,[accounts[0].id]);db.commit()
    assert not db.exec(select(PendingFxTransaction)).all()


def test_invalid_refund_target_rejected_before_pending_save(auth_client_a,db,monkeypatch):
    from uuid import uuid4
    _, _, _, accounts=setup_accounts(db)
    monkeypatch.setattr('services.report_currency.requests.get',fail_quotes)
    response=create(auth_client_a,accounts[0],transaction_type='refund',refund_of_transaction_id=str(uuid4()))
    assert response.status_code==400
    assert not db.exec(select(PendingFxTransaction)).all()


def test_notes_edit_keeps_allocated_native_and_book_amounts(auth_client_a,db):
    _, _, _, accounts=setup_accounts(db)
    expense=create(auth_client_a,accounts[0],amount='4',settlement_amount='0.0002',settlement_currency='CNY').json()
    refund=create(auth_client_a,accounts[0],amount='4',transaction_type='refund',settlement_amount='0.0003',settlement_currency='CNY',refund_of_transaction_id=expense['id'])
    assert refund.status_code==200
    edited=auth_client_a.patch(f"/api/v1/transactions/{expense['id']}",json={'amount':'0.0002','date':DAY.isoformat(),'notes':'metadata only'})
    assert edited.status_code==200,edited.text
    assert Decimal(edited.json()['amount'])==Decimal('0.0002')
    allocation=db.exec(select(RefundAllocation)).one()
    assert allocation.allocated_amount==4 and allocation.original_book_amount==Decimal('0.0002')


def test_financial_edit_prepares_booking_before_flush(auth_client_a,db,monkeypatch):
    _, _, _, accounts=setup_accounts(db)
    primary,child=accounts
    child.currency='USD'
    for account in accounts:account.account_type='credit_card';account.classification='liability'
    child.parent_account_id=primary.id;db.add_all(accounts);db.commit()
    created=create(auth_client_a,child,master_settlement_amount='700',master_settlement_currency='CNY').json()
    monkeypatch.setattr('services.report_currency.requests.get',fail_quotes)
    edited=auth_client_a.patch(f"/api/v1/transactions/{created['id']}",json={
        'original_amount':'200','original_currency':'USD','settlement_amount':'200','settlement_currency':'USD',
        'master_settlement_amount':'1405','master_settlement_currency':'CNY','category_id':None})
    assert edited.status_code==200,edited.text
    assert Decimal(edited.json()['original_amount'])==200 and Decimal(edited.json()['master_settlement_amount'])==1405


def test_reports_retain_master_actual_settlement_and_fx(auth_client_a,db):
    _, _, _, accounts=setup_accounts(db)
    primary,child=accounts
    child.currency='USD'
    for account in accounts:account.account_type='credit_card';account.classification='liability'
    child.parent_account_id=primary.id;db.add_all(accounts);db.commit()
    expense=create(auth_client_a,child,master_settlement_amount='700',master_settlement_currency='CNY').json()
    refund=create(auth_client_a,child,transaction_type='refund',master_settlement_amount='720',master_settlement_currency='CNY',refund_of_transaction_id=expense['id'])
    assert refund.status_code==200,refund.text
    summary=auth_client_a.get('/api/v1/dashboard/summary?period=ALL')
    assert summary.status_code==200,summary.text
    result=summary.json()
    assert result['outflows']['total']==0 and result['fx_gain']==20 and result['actual_refund_amount']==720
    from services.report_currency import ReportCurrency
    from services.stats_engine import get_report_account_balances
    converter=ReportCurrency(db,currency='CNY')
    values=get_report_account_balances(db,accounts,converter)
    assert sum(values.values())==-20


def test_account_group_totals_use_fixed_master_contribution(auth_client_a,db):
    _, _, _, accounts=setup_accounts(db)
    primary,child=accounts
    child.currency='USD'
    for account in accounts:account.account_type='credit_card';account.classification='liability'
    child.parent_account_id=primary.id;db.add_all(accounts);db.commit()
    expense=create(auth_client_a,child,master_settlement_amount='700',master_settlement_currency='CNY').json()
    assert create(auth_client_a,child,transaction_type='refund',master_settlement_amount='720',master_settlement_currency='CNY',refund_of_transaction_id=expense['id']).status_code==200
    response=auth_client_a.get('/api/v1/accounts')
    assert response.status_code==200,response.text
    rows=response.json()['accounts']
    assert sum(Decimal(row['report_own_balance']) for row in rows)==-20
    assert Decimal(next(row['balance'] for row in rows if row['id']==str(primary.id)))==-20
    assert Decimal(next(row['balance'] for row in rows if row['id']==str(child.id)))==0


def test_one_refund_to_multiple_expenses_has_native_remaining(auth_client_a,db):
    _, _, _, accounts=setup_accounts(db)
    expenses=[create(auth_client_a,accounts[0],currency='CNY',amount='50',narration=f'expense-{i}').json() for i in range(2)]
    refund=create(auth_client_a,accounts[0],currency='CNY',amount='100',transaction_type='refund',narration='Combined refund').json()
    for i,original in enumerate(expenses):
        response=auth_client_a.post(f"/api/v1/refunds/{refund['id']}/allocate",json={'original_transaction_id':original['id'],'allocated_amount':'50'})
        assert response.status_code==200,response.text
        detail=auth_client_a.get(f"/api/v1/transactions/{refund['id']}").json()['refund_info']
        assert detail['is_linked'] and Decimal(detail['remaining_amount'])==50*(1-i)
        assert detail['is_fully_allocated']==bool(i)
    assert len(db.exec(select(RefundAllocation)).all())==2

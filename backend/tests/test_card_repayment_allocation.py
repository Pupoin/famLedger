"""Grouped repayments must agree across users, reports, curves and persistence."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import select

from models import Account, AccountShare, CardMembership, CardSettlementArchive, CardSettlementState, Family, Transaction, Transfer, User
from fastapi import HTTPException
from routes.v1_accounts import get_account_realtime_balance
from services.balance_sheet import ledger_net_worth_history, visible_balance_accounts
from services.card_settlement import group_for_account
from services.report_currency import ReportCurrency

DAY = date(2026, 9, 1)


@pytest.fixture
def group(db, request):
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    family = Family(name='Settlement regression')
    db.add(family); db.flush()
    alice.family_id = bob.family_id = family.id
    db.add_all([alice, bob]); db.flush()
    master = Account(name='Master', family_id=family.id, owner_id=alice.id,
                     account_type='credit_card', classification='liability')
    child = Account(name='Child', family_id=family.id, owner_id=bob.id,
                    account_type='credit_card', classification='liability', currency=getattr(request,'param','CNY'))
    db.add_all([master, child]); db.flush()
    db.add(AccountShare(account_id=child.id, user_id=alice.id, permission='read_only'))
    db.flush()
    child.parent_account_id = master.id
    db.add(child); db.commit()
    return master, child, alice, bob


def activity(db, account, amount, kind='expense', offset=0, **fields):
    at = datetime(2026, 9, 1, 12) + timedelta(days=offset)
    row = Transaction(account_id=account.id, amount=Decimal(str(amount)), currency=account.currency,
                      transacted_at=at.date(), occurred_at=at, transaction_type=kind,
                      narration='Recorded payment' if kind == 'transfer' else 'Recorded activity',
                      **fields)
    db.add(row); db.commit()
    return row


def balance(db, account):
    return get_account_realtime_balance(db, account.id, account.classification, account.balance)


def purchases(db, group):
    master, child, *_ = group
    a = activity(db, master, 300)
    b = activity(db, child, 200)
    return a, b


def test_secondary_payment_then_primary_proportional_then_full_payment(db, group):
    master, child, *_ = group
    purchases(db, group)
    child_payment = activity(db, child, 100, 'transfer', 1, extra={'direction':'inflow'})
    assert (balance(db, master), balance(db, child)) == (400, 100)
    primary_payment = activity(db, master, 200, 'transfer', 2, extra={'direction':'inflow'})
    assert (balance(db, master), balance(db, child)) == (200, 50)
    assert group_for_account(db, master).native_balance(master.id) == 150
    state = db.get(CardSettlementState, master.id)
    recorded = [r for r in state.allocations if r['source_transaction_id'] == str(primary_payment.id)]
    assert sum(Decimal(r['settlement_amount']) for r in recorded) == 200
    assert {r['account_id']:Decimal(r['amount']) for r in recorded} == {str(master.id):150,str(child.id):50}
    assert any(r['source_transaction_id'] == str(child_payment.id) for r in state.allocations)
    activity(db, child, 200, 'transfer', 3, extra={'direction':'inflow'})
    assert (balance(db, master), balance(db, child)) == (0, 0)
    assert len(db.exec(select(Transaction)).all()) == 5  # no fabricated repayments


def test_primary_incoming_transfer_is_repayment_without_changing_type(db, group):
    master, child, *_ = group
    purchases(db, group)
    payment = activity(db, master, 200, 'transfer', 1, extra={'direction':'in'})
    assert (balance(db, master), balance(db, child)) == (300, 120)
    assert group_for_account(db, master).native_balance(master.id) == 180
    assert db.get(Transaction, payment.id).transaction_type == 'transfer'


def test_child_excess_repayment_reduces_other_cards(db, group):
    master, child, *_ = group
    purchases(db, group)
    activity(db, child, 300, 'income', 1)
    assert (balance(db, master), balance(db, child)) == (200, 0)
    assert group_for_account(db, master).native_balance(master.id) == 200


def test_overpayment_is_on_primary_and_consumed_only_once(db, group):
    master, child, *_ = group
    purchases(db, group)
    activity(db, child, 600, 'transfer', 1, extra={'direction':'inflow'})
    assert (balance(db, master), balance(db, child)) == (-100, 0)
    activity(db, child, 60, offset=2)
    assert (balance(db, master), balance(db, child)) == (-40, 0)
    activity(db, child, 80, offset=3)
    assert (balance(db, master), balance(db, child)) == (40, 40)
    for _ in range(3):
        db.expire_all()
        assert (balance(db, master), balance(db, child)) == (40, 40)


def test_payment_before_purchase_cannot_clear_new_spending_twice(db, group):
    master, child, *_ = group
    activity(db, master, 100, 'income')
    activity(db, child, 150, offset=1)
    assert (balance(db, master), balance(db, child)) == (50, 50)


def test_payment_edit_delete_and_backdating_rebuild_saved_allocations(db, group):
    master, child, *_ = group
    purchases(db, group)
    payment = activity(db, master, 250, 'income', 1)
    assert balance(db, child) == 100
    payment.amount = Decimal(500); db.add(payment); db.commit()
    assert (balance(db, master), balance(db, child)) == (0, 0)
    assert sum(Decimal(r['settlement_amount']) for r in db.get(CardSettlementState,master.id).allocations) == 500
    payment.transacted_at = DAY - timedelta(days=1); db.add(payment); db.commit()
    assert (balance(db, master), balance(db, child)) == (0, 0)
    db.delete(payment); db.commit()
    assert (balance(db, master), balance(db, child)) == (500, 200)
    assert not db.get(CardSettlementState,master.id).allocations


@pytest.mark.parametrize('paid',[False,True])
def test_refund_targets_original_card_before_group_credit(db, group, paid):
    master, child, *_ = group
    _, original = purchases(db, group)
    if paid:
        activity(db, master, 500, 'income', 1)
    activity(db, child, 100, 'refund', 2, refund_of_transaction_id=original.id)
    assert (balance(db, master), balance(db, child)) == ((-100,0) if paid else (400,100))


def test_refund_after_original_paid_reduces_other_card_debt(db, group):
    master, child, *_ = group
    _, original = purchases(db, group)
    activity(db, child, 200, 'income', 1)
    activity(db, child, 100, 'refund', 2, refund_of_transaction_id=original.id)
    assert (balance(db, master), balance(db, child)) == (200,0)


def test_allocation_rounding_conserves_a_single_small_payment(db, group):
    master, child, *_ = group
    activity(db, master, 1)
    activity(db, child, 2)
    payment = activity(db, master, '.0001', 'income', 1)
    state = db.get(CardSettlementState,master.id)
    assert sum(Decimal(r['settlement_amount']) for r in state.allocations if r['source_transaction_id']==str(payment.id)) == Decimal('.0001')
    assert balance(db, master) == Decimal('2.9999')


@pytest.mark.parametrize('group',['USD'],indirect=True)
def test_fixed_foreign_principal_and_refund_fx_difference(db, group, monkeypatch):
    master, child, *_ = group
    original = activity(db, child, 100, master_account_id=master.id, master_settlement_amount=Decimal(700),
                        master_settlement_currency='CNY', master_exchange_rate=Decimal(7))
    activity(db, master, 350, 'income', 1)
    assert (balance(db, master),balance(db, child)) == (350,50)
    monkeypatch.setattr('services.report_currency.requests.get', lambda *a,**k: pytest.fail('no live FX on replay'))
    activity(db, child, 100, 'refund', 2, refund_of_transaction_id=original.id,
             master_account_id=master.id, master_settlement_amount=Decimal(720),master_settlement_currency='CNY',
             master_exchange_rate=Decimal('7.2'))
    assert (balance(db, master), balance(db,child)) == (-370,0)


@pytest.mark.parametrize('group',['USD'],indirect=True)
def test_full_foreign_refund_clears_native_principal_with_bank_fx_loss(db, group):
    master, child, *_ = group
    original = activity(db, child, 100, master_account_id=master.id,master_settlement_amount=Decimal(700),master_settlement_currency='CNY')
    activity(db, child, 100, 'refund', 1,refund_of_transaction_id=original.id,
             master_account_id=master.id,master_settlement_amount=Decimal(690),master_settlement_currency='CNY')
    assert (balance(db,master),balance(db,child)) == (10,0)


def test_reports_count_visible_child_without_double_counting_primary(auth_client_a,auth_client_b,db,group):
    master,child,alice,bob = group
    purchases(db,group)
    activity(db,master,250,'income',1)
    before = db.get(CardSettlementState,master.id).model_dump()
    for client, expected in ((auth_client_a,250),(auth_client_b,100)):
        listing = client.get('/api/v1/accounts').json()['accounts']
        assert sum(Decimal(r['report_own_balance']) for r in listing) == expected
        summary = client.get('/api/v1/dashboard/summary').json()['balance_sheet']
        report = client.get('/api/v1/analytics/report').json()['net_worth']
        assert summary['total_liabilities'] == report['liabilities_total'] == expected
    detail = auth_client_b.get(f'/api/v1/accounts/{child.id}').json()
    assert Decimal(detail['account']['balance']) == 100
    assert detail['account']['balance_included']
    assert all(row['source_transaction_id'] is None for row in detail['repayment_allocations'])
    assert [Decimal(row['amount']) for row in detail['repayment_allocations']] == [100]
    assert auth_client_b.get(f'/api/v1/accounts/{master.id}').status_code == 403
    assert db.get(CardSettlementState,master.id).model_dump() == before


def test_child_curve_includes_primary_repayment_and_history_counts_group_once(auth_client_b,db,group):
    master,child,alice,bob = group
    purchases(db,group)
    activity(db,master,500,'income',1)
    detail = auth_client_b.get(f'/api/v1/accounts/{child.id}?period=ALL').json()
    assert detail['chart']['points'][-1]['balance'] == detail['metrics']['balance'] == 0
    assert detail['metrics']['change_amount'] == 0
    history = ledger_net_worth_history(db,visible_balance_accounts(db,alice),ReportCurrency(db,alice),
                                      [('purchase',DAY),('paid',DAY+timedelta(days=1))])
    assert [r['value'] for r in history] == [-500,0]
    personal = ledger_net_worth_history(db,visible_balance_accounts(db,bob),ReportCurrency(db,bob),[('purchase',DAY)])
    assert personal[0]['value']==-200


def test_history_projects_all_cutoffs_once_without_writing_repayment_allocations(db, group, monkeypatch):
    import services.card_replay as card_replay
    master, child, alice, bob = group
    _, original = purchases(db, group)
    activity(db, child, 100, 'transfer', 1, extra={'direction': 'inflow'})
    activity(db, master, 200, 'transfer', 2, extra={'direction': 'inflow'})
    activity(db, child, 25, 'refund', 3, refund_of_transaction_id=original.id)
    activity(db, master, 200, 'income', 4)
    before = db.get(CardSettlementState, master.id).model_dump()
    replay = card_replay.replay
    calls = []
    def counted(*args, **kwargs):
        calls.append(args[1].id)
        return replay(*args, **kwargs)
    monkeypatch.setattr(card_replay, 'replay', counted)
    # Unsorted labels and repeated cutoffs must preserve the caller's order.
    days = [4, 0, 1, 2, 3, 0]
    periods = [(str(index), DAY + timedelta(days=day)) for index, day in enumerate(days)]
    history = ledger_net_worth_history(db, visible_balance_accounts(db, alice), ReportCurrency(db, alice), periods)
    assert [row['value'] for row in history] == [25, -500, -400, -200, -175, -500]
    assert len(calls) == 1
    personal = ledger_net_worth_history(db, visible_balance_accounts(db, bob), ReportCurrency(db, bob), periods)
    assert [row['value'] for row in personal] == [0, -200, -100, -50, -25, -200]
    assert len(calls) == 2
    assert db.get(CardSettlementState, master.id).model_dump() == before
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize('payment',[250,500])
def test_unlink_requires_zero_and_preserves_cleared_history(db,group,payment):
    master,child,*_ = group
    purchases(db,group)
    activity(db,master,payment,'income',1)
    expected = balance(db,child)
    child.parent_account_id=None;db.add(child)
    if expected:
        with pytest.raises(HTTPException, match='副卡待还未清零'):
            db.commit()
        db.rollback()
        assert child.parent_account_id == master.id
        assert (balance(db, master), balance(db, child)) == (250, 100)
        return
    db.commit()
    assert balance(db,child)==expected
    assert balance(db,master)==Decimal(500-payment)-expected
    assert len(db.exec(select(Transaction).where(Transaction.transaction_type=='expense')).all())==2


def test_share_revocation_detaches_without_resurrecting_paid_debt(auth_client_b,db,group):
    master,child,alice,_ = group
    purchases(db,group);activity(db,master,500,'income',1)
    response=auth_client_b.patch(f'/api/v1/accounts/{child.id}/shares',json={'members':[{'user_id':str(alice.id),'shared':False}]})
    assert response.status_code==200,response.text
    db.expire_all()
    assert db.get(Account,child.id).parent_account_id is None
    assert balance(db,child)==balance(db,master)==0


def test_internal_transfer_does_not_reduce_group_debt(db,group):
    master,child,*_=group
    purchases(db,group)
    outgoing=activity(db,child,100,'transfer',1,extra={'direction':'outflow'})
    incoming=activity(db,master,100,'transfer',1,extra={'direction':'inflow'})
    pair=Transfer(family_id=master.family_id,outflow_transaction_id=outgoing.id,inflow_transaction_id=incoming.id,amount=Decimal(100))
    db.add(pair);db.flush()
    outgoing.transfer_id=incoming.transfer_id=pair.id
    db.add_all([outgoing,incoming]);db.commit()
    assert balance(db,master)==500


def test_cross_family_private_activity_never_affects_group(db,group):
    master,child,*_=group
    purchases(db,group)
    family=Family(name='Other tenant');db.add(family);db.flush()
    outsider=Account(name='Other primary',family_id=family.id,account_type='credit_card',classification='liability')
    db.add(outsider);db.commit()
    activity(db,outsider,99999,'income',1)
    assert (balance(db,master),balance(db,child))==(500,200)


def test_bank_payment_is_counted_once_and_does_not_change_spending(auth_client_a,db,group):
    master,child,alice,_=group
    purchases(db,group)
    bank=Account(name='Payment bank',family_id=master.family_id,owner_id=alice.id,
                 account_type='checking',classification='asset')
    db.add(bank);db.commit()
    activity(db,bank,1000,'income',excluded_from_stats=True,extra={'is_initial':True})
    outgoing=activity(db,bank,200,'transfer',1,extra={'direction':'outflow'})
    incoming=activity(db,master,200,'transfer',1,extra={'direction':'inflow'})
    pair=Transfer(family_id=master.family_id,outflow_transaction_id=outgoing.id,inflow_transaction_id=incoming.id,amount=Decimal(200))
    db.add(pair);db.flush()
    outgoing.transfer_id=incoming.transfer_id=pair.id
    db.add_all([outgoing,incoming]);db.commit()
    assert balance(db,master)==300 and balance(db,child)==120
    summary=auth_client_a.get('/api/v1/dashboard/summary?period=ALL').json()
    assert summary['balance_sheet']['total_assets']==800
    assert summary['balance_sheet']['total_liabilities']==300
    assert summary['balance_sheet']['net_worth']==500
    assert summary['outflows']['total']==500
    assert len(db.exec(select(Transaction)).all())==5


def test_unpaid_reparent_is_rejected_without_reallocation(db,group):
    master,child,alice,_=group
    purchases(db,group);activity(db,master,250,'income',1)
    other=Account(name='New master',family_id=master.family_id,owner_id=alice.id,
                  account_type='credit_card',classification='liability')
    db.add(other);db.commit()
    child.parent_account_id=other.id;db.add(child)
    with pytest.raises(HTTPException, match='副卡待还未清零'):
        db.commit()
    db.rollback()
    assert child.parent_account_id == master.id
    assert (balance(db,master), balance(db,other), balance(db,child)) == (250, 0, 100)
    assert len(db.exec(select(Transaction).where(Transaction.transaction_type=='expense')).all())==2


@pytest.mark.parametrize('endpoint',['edit','reconcile'])
def test_child_balance_adjustment_consumes_group_credit_and_rejects_negative(auth_client_b,db,group,endpoint):
    master,child,*_=group
    purchases(db,group);activity(db,master,600,'income',1)
    def request(amount):
        if endpoint=='edit':
            return auth_client_b.patch(f'/api/v1/accounts/{child.id}',json={'balance':str(amount)})
        return auth_client_b.post(f'/api/v1/accounts/{child.id}/reconcile-balance',json={'new_balance':str(amount),'reconciliation_type':'adjustment'})
    assert request(-1).status_code==422
    assert (balance(db,master),balance(db,child))==(-100,0)
    response=request(50)
    assert response.status_code==200,response.text
    assert (balance(db,master),balance(db,child))==(50,50)
    assert request(50).status_code==200
    assert (balance(db,master),balance(db,child))==(50,50)


def test_existing_session_observes_repayment_changed_by_another_request(auth_client_a,db,group):
    master,child,*_=group
    purchases(db,group)
    payment=activity(db,master,250,'income',1)
    assert balance(db,child)==100
    response=auth_client_a.patch(f'/api/v1/transactions/{payment.id}',json={'amount':'500'})
    assert response.status_code==200,response.text
    assert (balance(db,master),balance(db,child))==(0,0)


@pytest.mark.parametrize('paid', [250, 500])
def test_primary_deletion_requires_all_children_cleared(auth_client_a, db, group, paid):
    master, child, *_ = group
    purchases(db, group)
    activity(db, master, paid, 'income', 1)
    expected = balance(db, child)
    response = auth_client_a.delete(f'/api/v1/accounts/{master.id}')
    if expected:
        assert response.status_code == 409, response.text
        db.expire_all()
        assert child.parent_account_id == master.id
        assert (balance(db,master), balance(db,child)) == (250,100)
        return
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id is None
    assert balance(db, child) == expected


def test_user_financial_deletion_blocks_unpaid_cross_owner_links(db, group):
    from services.financial_deletion import delete_account_data
    master, child, *_ = group
    purchases(db, group)
    activity(db, master, 250, 'income', 1)
    with pytest.raises(HTTPException, match='副卡待还未清零'):
        delete_account_data(db, {master.id})
    db.rollback()
    assert child.parent_account_id == master.id
    assert (balance(db,master), balance(db,child)) == (250,100)


@pytest.mark.parametrize('moving', ['child', 'master'])
@pytest.mark.parametrize('paid', [250,500])
def test_family_migration_requires_cleared_cross_owner_links(db, group, moving, paid):
    from services.tenant_migration import migrate_user_to_family
    master, child, alice, bob = group
    purchases(db, group)
    activity(db, master, paid, 'income', 1)
    target = Family(name='New personal family', kind='personal')
    db.add(target); db.commit()
    if paid < 500:
        with pytest.raises(HTTPException, match='副卡待还未清零'):
            migrate_user_to_family(db, bob if moving == 'child' else alice, target.id)
            db.commit()
        db.rollback()
        assert child.parent_account_id == master.id
        assert (balance(db,master),balance(db,child)) == (250,100)
        return
    migrate_user_to_family(db, bob if moving == 'child' else alice, target.id)
    db.commit()
    assert child.parent_account_id is None
    assert (balance(db,master),balance(db,child)) == (0,0)


def test_existing_session_observes_unlink_by_another_request(auth_client_b, db, group):
    master, child, alice, _ = group
    purchases(db, group)
    activity(db, master, 500, 'income', 1)
    assert balance(db, child) == 0
    response = auth_client_b.patch(f'/api/v1/accounts/{child.id}/shares', json={
        'members': [{'user_id': str(alice.id), 'shared': False}]})
    assert response.status_code == 200, response.text
    assert (balance(db, master), balance(db, child)) == (0, 0)


def test_cleared_child_can_become_an_asset(auth_client_b, db, group):
    master, child, *_ = group
    purchases(db, group)
    activity(db, master, 500, 'income', 1)
    response = auth_client_b.patch(f'/api/v1/accounts/{child.id}', json={'account_type': 'checking'})
    assert response.status_code == 200, response.text
    db.expire_all()
    assert (balance(db, master), balance(db, child)) == (0, 0)


def test_bulk_unlink_of_unpaid_children_rolls_back_every_link(db, group):
    master, child, alice, _ = group
    second = Account(name='Second child', owner_id=alice.id, family_id=master.family_id,
                     account_type='credit_card', classification='liability', parent_account_id=master.id)
    db.add(second); db.commit()
    purchases(db, group)
    activity(db, second, 500)
    activity(db, master, 500, 'income', 1)
    child.parent_account_id = second.parent_account_id = None
    db.add_all([child, second])
    with pytest.raises(HTTPException, match='副卡待还未清零'):
        db.commit()
    db.rollback()
    assert child.parent_account_id == second.parent_account_id == master.id
    assert (balance(db,master),balance(db,child),balance(db,second)) == (500,100,250)


@pytest.mark.parametrize('direct', [False, True])
def test_deleting_child_invalidates_primary_allocation_cache(auth_client_b, db, group, direct):
    master, child, alice, _ = group
    second = Account(name='Remaining child', owner_id=alice.id, family_id=master.family_id,
                     account_type='credit_card', classification='liability', parent_account_id=master.id)
    db.add(second); db.commit()
    purchases(db, group)
    activity(db, second, 500)
    activity(db, master, 500, 'income', 1)
    activity(db,child,100,'income',2)
    assert balance(db, master) == 400
    if direct:
        from routes.v1_accounts import delete_account
        delete_account(child.id, session=db, user_or_ctx='bob')
    else:
        response = auth_client_b.delete(f'/api/v1/accounts/{child.id}')
        assert response.status_code == 200, response.text
    assert balance(db, master) == 400
    assert balance(db,second) == 250
    state = db.get(CardSettlementState, master.id, populate_existing=True)
    assert str(child.id) not in state.balances


def test_unpaid_child_unlink_keeps_sibling_and_primary_unchanged(db, group):
    master, child, alice, _ = group
    sibling = Account(name='Sibling', owner_id=alice.id, family_id=master.family_id,
                      account_type='credit_card', classification='liability', parent_account_id=master.id)
    db.add(sibling); db.commit()
    purchases(db, group)
    activity(db, sibling, 500)
    activity(db, master, 500, 'income', 1)
    child.parent_account_id = None
    db.add(child)
    with pytest.raises(HTTPException, match='副卡待还未清零'):
        db.commit()
    db.rollback()
    assert child.parent_account_id == master.id
    assert (balance(db,master),balance(db,child),balance(db,sibling)) == (500,100,250)
    assert group_for_account(db, master).native_balance(master.id) == 150


def test_cleared_child_unlink_keeps_sibling_unpaid_share(db, group):
    master, child, alice, _ = group
    sibling = Account(name='Remaining sibling', owner_id=alice.id, family_id=master.family_id,
                      account_type='credit_card', classification='liability', parent_account_id=master.id)
    db.add(sibling); db.commit()
    purchases(db, group)
    activity(db, sibling, 500)
    activity(db, master, 500, 'income', 1)
    activity(db, child, 100, 'income', 2)
    assert (balance(db, child), balance(db, sibling)) == (0, 250)
    child.parent_account_id = None
    db.add(child); db.commit()
    assert (balance(db, master), balance(db, child), balance(db, sibling)) == (400, 0, 250)


def test_reparent_does_not_reallocate_new_primarys_earlier_repayments(db, group):
    master, child, alice, _ = group
    other = Account(name='Existing primary', owner_id=alice.id, family_id=master.family_id,
                    account_type='credit_card', classification='liability')
    db.add(other); db.commit()
    purchases(db, group)
    activity(db, other, 500)
    activity(db, other, 300, 'income', 1)
    activity(db, master, 500, 'income', 1)
    child.parent_account_id = other.id
    db.add(child); db.commit()
    assert (balance(db, master), balance(db, other), balance(db, child)) == (0, 200, 0)


    future = datetime.now().replace(microsecond=0) + timedelta(days=1)
    db.add(Transaction(account_id=child.id, amount=Decimal(100),currency='CNY',transacted_at=future.date(),occurred_at=future,transaction_type='expense',narration='New group purchase'))
    db.commit()
    assert (balance(db,master),balance(db,other),balance(db,child)) == (0,300,100)


@pytest.mark.parametrize('group', ['USD'], indirect=True)
@pytest.mark.parametrize('endpoint', ['edit', 'reconcile'])
def test_foreign_child_manual_balance_uses_unpaid_lots_fixed_rate(auth_client_b, db, group, monkeypatch, endpoint):
    master, child, *_ = group
    activity(db, child, 100, master_account_id=master.id, master_settlement_amount=Decimal(700),
             master_settlement_currency='CNY', master_exchange_rate=Decimal(7))
    activity(db, master, 350, 'income', 1)
    def quote(session, amount, source, target, day, *args, **kwargs):
        assert (source, target) == ('USD', 'CNY')
        return Decimal(amount) * 8, Decimal(8), day, 'test_quote'
    monkeypatch.setattr('services.booking_money.fixed_conversion', quote)
    if endpoint == 'edit':
        response = auth_client_b.patch(f'/api/v1/accounts/{child.id}', json={'balance': '25'})
    else:
        response = auth_client_b.post(f'/api/v1/accounts/{child.id}/reconcile-balance', json={
            'new_balance': '25', 'reconciliation_type': 'adjustment'})
    assert response.status_code == 200, response.text
    db.expire_all()
    assert (balance(db, master), balance(db, child)) == (175, 25)


@pytest.mark.parametrize('group', ['USD'], indirect=True)
def test_unpaid_foreign_reparent_keeps_fixed_booking_and_link(db, group, monkeypatch):
    master, child, alice, _ = group
    activity(db, child, 100, master_account_id=master.id, master_settlement_amount=Decimal(700),
             master_settlement_currency='CNY', master_exchange_rate=Decimal(7))
    activity(db, master, 350, 'income', 1)
    other = Account(name='New CNY primary', owner_id=alice.id, family_id=master.family_id,
                    account_type='credit_card', classification='liability')
    db.add(other); db.commit()
    def quote(session, amount, source, target, day, *args, **kwargs):
        assert (source, target) == ('USD', 'CNY')
        rate = Decimal(6 if day == DAY else 8)
        return Decimal(amount) * rate, rate, day, 'test_quote'
    monkeypatch.setattr('services.booking_money.fixed_conversion', quote)
    child.parent_account_id = other.id
    db.add(child)
    with pytest.raises(HTTPException, match='副卡待还未清零'):
        db.commit()
    db.rollback()
    assert child.parent_account_id == master.id
    assert (balance(db,master),balance(db,other),balance(db,child)) == (350,0,50)


@pytest.mark.parametrize('group', ['USD'], indirect=True)
def test_unlink_multiple_foreign_children_in_one_commit(db, group):
    master, child, alice, _ = group
    sibling = Account(name='Foreign sibling', owner_id=alice.id, family_id=master.family_id,
                      account_type='credit_card', classification='liability', currency='USD',
                      parent_account_id=master.id)
    db.add(sibling); db.commit()
    for card in [child, sibling]:
        activity(db, card, 100, master_account_id=master.id, master_settlement_amount=Decimal(700),
                 master_settlement_currency='CNY', master_exchange_rate=Decimal(7))
    activity(db, master, 1400, 'income', 1)
    child.parent_account_id = sibling.parent_account_id = None
    db.add_all([child, sibling]); db.commit()
    assert (balance(db, master), balance(db, child), balance(db, sibling)) == (0, 0, 0)


@pytest.mark.parametrize('operation', ['unlink', 'type', 'delete', 'unshare'])
def test_unpaid_relationship_operations_are_atomic_and_explain_reason(auth_client_b, db, group, operation):
    master, child, alice, _ = group
    purchases(db,group); activity(db,master,250,'income',1)
    snapshot = db.get(CardSettlementState,master.id).model_dump()
    if operation == 'delete':
        response = auth_client_b.delete(f'/api/v1/accounts/{child.id}')
    elif operation == 'unshare':
        response = auth_client_b.patch(f'/api/v1/accounts/{child.id}/shares',json={
            'members':[{'user_id':str(alice.id),'shared':False}]})
    else:
        response = auth_client_b.patch(f'/api/v1/accounts/{child.id}',json={
            'parent_account_id':''} if operation=='unlink' else {'account_type':'checking'})
    assert response.status_code==409,response.text
    assert '未清零' in response.json()['detail']
    db.expire_all()
    assert child.parent_account_id==master.id and child.account_type=='credit_card'
    assert db.exec(select(AccountShare).where(AccountShare.account_id==child.id,AccountShare.user_id==alice.id)).first()
    assert (balance(db,master),balance(db,child))==(250,100)
    assert db.get(CardSettlementState,master.id).model_dump()==snapshot


def test_bulk_unpaid_type_change_rolls_back_other_account_information(auth_client_b, db, group):
    master,child,_,bob=group
    purchases(db,group)
    other=Account(name='Other card',family_id=master.family_id,owner_id=bob.id,
                  institution_name='Original bank',account_type='credit_card',classification='liability')
    db.add(other);db.commit()
    response=auth_client_b.patch('/api/v1/accounts/bulk/settings',json={
        'account_ids':[str(other.id),str(child.id)],'institution_name':'Changed bank','account_type':'checking'})
    assert response.status_code==409,response.text
    db.expire_all()
    assert other.institution_name=='Original bank' and other.account_type=='credit_card'
    assert child.parent_account_id==master.id and child.institution_name is None
    assert (balance(db,master),balance(db,child))==(500,200)


@pytest.mark.parametrize('operation',['reduce','delete'])
def test_closed_card_period_cannot_be_reopened_by_editing_old_payment(auth_client_a,db,group,operation):
    master,child,*_=group
    purchases(db,group);payment=activity(db,master,500,'income',1)
    child.parent_account_id=None;db.add(child);db.commit()
    if operation=='reduce':
        response=auth_client_a.patch(f'/api/v1/transactions/{payment.id}',json={'amount':'250'})
    else:
        response=auth_client_a.delete(f'/api/v1/transactions/{payment.id}')
    assert response.status_code==409,response.text
    assert '结算期间' in response.json()['detail']
    db.expire_all()
    assert db.get(Transaction,payment.id).amount==500
    assert child.parent_account_id is None
    assert (balance(db,master),balance(db,child))==(0,0)


@pytest.mark.parametrize('group',['USD'],indirect=True)
def test_cleared_foreign_reparent_preserves_old_bookings_and_historical_balances(db,group,monkeypatch):
    master,child,alice,_=group
    original=activity(db,child,100,master_account_id=master.id,master_settlement_amount=Decimal(700),
                      master_settlement_currency='CNY',master_exchange_rate=Decimal(7))
    activity(db,master,700,'income',1)
    other=Account(name='Other primary',family_id=master.family_id,owner_id=alice.id,
                  account_type='credit_card',classification='liability')
    db.add(other);db.commit()
    monkeypatch.setattr('services.booking_money.fixed_conversion',lambda *a,**k: pytest.fail('changing a relationship must not reprice old bookings'))
    child.parent_account_id=other.id;db.add(child);db.commit()
    db.expire_all()
    assert (original.master_account_id,original.master_settlement_amount,original.master_exchange_rate)==(master.id,700,7)
    assert (balance(db,master),balance(db,other),balance(db,child))==(0,0,0)
    past=group_for_account(db,child,DAY)
    assert past.master.id==master.id and past.native_balance(child.id)==100 and past.balance==700
    assert group_for_account(db,child,DAY+timedelta(days=1)).native_balance(child.id)==0


def test_cleared_child_reclassified_as_asset_has_positive_income_in_detail_and_reports(auth_client_b,db,group):
    master,child,*_=group
    purchases(db,group);activity(db,master,500,'income',1)
    response=auth_client_b.patch(f'/api/v1/accounts/{child.id}',json={'account_type':'checking'})
    assert response.status_code==200,response.text
    now=datetime.now()+timedelta(seconds=1)
    db.add(Transaction(account_id=child.id,amount=Decimal(20),currency='CNY',transacted_at=now.date(),
                       occurred_at=now,transaction_type='income',narration='Asset deposit'))
    db.commit()
    detail=auth_client_b.get(f'/api/v1/accounts/{child.id}?period=ALL').json()
    assert Decimal(detail['account']['balance'])==Decimal(detail['account']['own_balance'])==20
    assert detail['account']['subcard_settlement_balance']=='0.0000'
    assert detail['account']['is_settlement_primary'] is False
    assert auth_client_b.get('/api/v1/dashboard/summary').json()['balance_sheet']['total_assets']==20


def test_deleted_primary_retains_only_minimal_settlement_evidence(auth_client_a,auth_client_b,db,group):
    master,child,*_=group
    purchases(db,group);activity(db,master,500,'income',1)
    response=auth_client_a.delete(f'/api/v1/accounts/{master.id}')
    assert response.status_code==200,response.text
    archive=db.get(CardSettlementArchive,master.id)
    assert archive is not None and len(archive.transactions)==2
    assert all(record['narration']=='' for record in archive.transactions)
    assert all(not {'notes','merchant_id','category_id','external_id','tags'} & record.keys() for record in archive.transactions)
    detail=auth_client_b.get(f'/api/v1/accounts/{child.id}?period=ALL').json()
    assert Decimal(detail['account']['balance'])==0
    assert all(row['source_transaction_id'] is None for row in detail['repayment_allocations'])
    assert auth_client_a.get(f'/api/v1/accounts/{master.id}').status_code==404


@pytest.mark.parametrize('endpoint',['edit','reconcile'])
def test_after_midnight_adjustment_uses_local_financial_day_and_utc_relationship_time(auth_client_b,db,group,monkeypatch,endpoint):
    from datetime import timezone
    from zoneinfo import ZoneInfo
    import routes.v1_accounts as account_routes
    import services.card_history as card_history
    master,child,alice,_=group
    purchases(db,group);activity(db,master,500,'income',1)
    other=Account(name='New midnight primary',family_id=master.family_id,owner_id=alice.id,
                  account_type='credit_card',classification='liability')
    db.add(other);db.commit()
    midnight=datetime(2026,10,6,18,0,tzinfo=timezone.utc)
    class LinkClock(datetime):
        @classmethod
        def now(cls,tz=None):
            return midnight.astimezone(tz) if tz else midnight.replace(tzinfo=None)
    class AdjustmentClock(datetime):
        @classmethod
        def now(cls,tz=None):
            now=midnight+timedelta(seconds=1)
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.setattr(card_history,'datetime',LinkClock)
    child.parent_account_id=other.id;db.add(child);db.commit()
    monkeypatch.setattr(account_routes,'datetime',AdjustmentClock)
    if endpoint=='edit':
        response=auth_client_b.patch(f'/api/v1/accounts/{child.id}',json={'balance':'50'})
    else:
        response=auth_client_b.post(f'/api/v1/accounts/{child.id}/reconcile-balance',json={
            'new_balance':'50','reconciliation_type':'adjustment','date':'2026-10-07','time':'02:00:01'})
    assert response.status_code==200,response.text
    adjustment=db.exec(select(Transaction).where(Transaction.account_id==child.id,Transaction.transaction_type=='adjustment')).one()
    assert adjustment.transacted_at==date(2026,10,7)
    assert adjustment.occurred_at==datetime(2026,10,6,18,0,1)
    assert adjustment.master_account_id==other.id
    assert (balance(db,master),balance(db,other),balance(db,child))==(0,50,50)


def test_former_child_can_become_primary_without_historical_nested_groups(db,group):
    master,child,_,bob=group
    purchases(db,group);activity(db,master,500,'income',1)
    child.parent_account_id=None;db.add(child);db.commit()
    new_child=Account(name='A new additional card',family_id=child.family_id,owner_id=bob.id,
                      account_type='credit_card',classification='liability',parent_account_id=child.id)
    db.add(new_child);db.commit()
    now=datetime.now()+timedelta(seconds=1)
    db.add(Transaction(account_id=new_child.id,amount=Decimal(40),currency='CNY',transacted_at=now.date(),
                       occurred_at=now,transaction_type='expense',narration='New generation purchase'))
    db.commit()
    assert (balance(db,master),balance(db,child),balance(db,new_child))==(0,40,40)
    assert group_for_account(db,child,DAY).master.id==master.id
    assert group_for_account(db,child,DAY).native_balance(child.id)==200


def test_multiple_rebindings_keep_each_periods_group_and_native_balance(db,group,monkeypatch):
    from datetime import timezone
    import services.card_history as card_history
    master,child,alice,_=group
    purchases(db,group);activity(db,master,500,'income',1)
    other=Account(name='Middle primary',family_id=master.family_id,owner_id=alice.id,
                  account_type='credit_card',classification='liability')
    db.add(other);db.commit()
    current=[datetime(2026,10,1,12,tzinfo=timezone.utc)]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return current[0].astimezone(tz) if tz else current[0].replace(tzinfo=None)
    monkeypatch.setattr(card_history,'datetime',Clock)
    child.parent_account_id=other.id;db.add(child);db.commit()
    activity(db,child,100,offset=31)
    activity(db,other,100,'income',32)
    assert (balance(db,master),balance(db,other),balance(db,child))==(0,0,0)
    current[0]=datetime(2026,10,4,12,tzinfo=timezone.utc)
    child.parent_account_id=master.id;db.add(child);db.commit()
    activity(db,child,80,offset=34)
    assert (balance(db,master),balance(db,other),balance(db,child))==(80,0,80)
    old=group_for_account(db,child,DAY)
    middle=group_for_account(db,child,date(2026,10,2))
    assert (old.master.id,old.native_balance(child.id))==(master.id,200)
    assert (middle.master.id,middle.native_balance(child.id))==(other.id,100)
    periods=db.exec(select(CardMembership).where(CardMembership.account_id==child.id)).all()
    assert len(periods)==3 and sum(row.ended_at is None for row in periods)==1
    cutoffs = [('old', DAY), ('cleared', DAY + timedelta(days=1)),
               ('middle', date(2026,10,2)), ('paid', date(2026,10,3)), ('new', date(2026,10,5))]
    history = ledger_net_worth_history(db, visible_balance_accounts(db, alice), ReportCurrency(db, alice), cutoffs)
    assert [row['value'] for row in history] == [-500, 0, -100, 0, -80]
    personal = ledger_net_worth_history(db, [child], ReportCurrency(db, group[3]), cutoffs)
    assert [row['value'] for row in personal] == [-200, 0, -100, 0, -80]

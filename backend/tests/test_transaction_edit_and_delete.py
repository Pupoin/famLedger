"""Transfer editing/deletion must conserve balances, links and permissions."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlmodel import select

from models import (Account, AccountShare, CardSettlementState, Category, ExchangeRateSnapshot, Family, RefundAllocation,
                    RejectedTransfer, Transaction, TransactionSplit, Transfer, User, UserPreference)
from routes.v1_accounts import get_account_realtime_balance

DAY = date(2026, 9, 9)


@pytest.fixture
def accounts(db):
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    family = Family(name='Transaction regression', currency='CNY')
    db.add(family); db.flush()
    alice.family_id = bob.family_id = family.id
    db.add_all([alice, bob]); db.flush()
    rows = [Account(name=name, owner_id=alice.id, family_id=family.id, account_type='checking', currency='CNY')
            for name in ('Source', 'Destination', 'Other destination')]
    db.add_all(rows); db.commit()
    return rows


def activity(db, account, kind='expense', amount=100, **changes):
    values = dict(account_id=account.id, transacted_at=DAY, occurred_at=datetime(2026, 9, 9, 10),
                  amount=Decimal(amount), currency=account.currency, original_amount=Decimal(amount),
                  original_currency=account.currency, exchange_rate=Decimal(1), exchange_rate_date=DAY,
                  exchange_rate_source='bank', transaction_type=kind, narration='Regression activity')
    values.update(changes)
    row = Transaction(**values)
    db.add(row); db.commit()
    return row


def paired(db, accounts):
    out = activity(db, accounts[0], 'transfer')
    incoming = activity(db, accounts[1], 'transfer')
    pair = Transfer(family_id=accounts[0].family_id, outflow_transaction_id=out.id,
                    inflow_transaction_id=incoming.id, amount=out.amount)
    db.add(pair); db.flush()
    out.transfer_id = incoming.transfer_id = pair.id
    db.add_all([out, incoming]); db.commit()
    return out, incoming, pair


def balance(db, account):
    db.expire_all()
    return get_account_realtime_balance(db, account.id, account.classification, account.balance)


def remove(client, row, pair, scope='single', **extra):
    return client.delete(f'/api/v1/transactions/{row.id}', params={
        'scope': scope, 'expected_transfer_id': str(pair.id), **extra})


def test_paired_deletion_requires_explicit_scope_and_current_pair(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    for params in ({}, {'scope': 'single'}, {'scope': 'pair', 'expected_transfer_id': str(uuid4())}):
        response = auth_client_a.delete(f'/api/v1/transactions/{out.id}', params=params)
        assert response.status_code == 409, response.text
    db.expire_all()
    assert db.get(Transfer, pair.id) and db.get(Transaction, incoming.id) and db.get(Transaction, out.id)


@pytest.mark.parametrize('index,direction,expected', [(0, 'inflow', 100), (1, 'outflow', -100)])
def test_single_deletion_keeps_peer_money_direction_and_transfer_type(auth_client_a, db, accounts, index, direction, expected):
    out, incoming, pair = paired(db, accounts)
    row, remaining = (out, incoming) if index == 0 else (incoming, out)
    row_id, peer_id, pair_id = row.id, remaining.id, pair.id
    response = remove(auth_client_a, row, pair)
    assert response.status_code == 200, response.text
    assert response.json()['deleted_ids'] == [str(row_id)]
    db.expire_all()
    assert db.get(Transaction, row_id) is None and db.get(Transfer, pair_id) is None
    peer = db.get(Transaction, peer_id)
    assert peer.transaction_type == 'transfer' and peer.transfer_id is None
    assert peer.extra['direction'] == direction and peer.amount == 100 and peer.original_amount == 100
    assert balance(db, accounts[1 if index == 0 else 0]) == expected


def test_delete_both_cleans_foreign_keys_but_keeps_linked_refund(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    refund = activity(db, accounts[2], 'refund', 10, refund_of_transaction_id=out.id)
    db.add_all([TransactionSplit(transaction_id=out.id, amount=Decimal(100)),
                TransactionSplit(transaction_id=incoming.id, amount=Decimal(100)),
                RefundAllocation(original_transaction_id=out.id, refund_transaction_id=refund.id, allocated_amount=Decimal(10)),
                RejectedTransfer(outflow_transaction_id=out.id, inflow_transaction_id=incoming.id)])
    db.commit()
    ids, pair_id, refund_id = [out.id, incoming.id], pair.id, refund.id
    response = remove(auth_client_a, out, pair, 'pair')
    assert response.status_code == 200, response.text
    assert set(response.json()['deleted_ids']) == {str(value) for value in ids}
    db.expire_all()
    assert all(db.get(Transaction, value) is None for value in ids)
    assert db.get(Transfer, pair_id) is None
    for model in (TransactionSplit, RefundAllocation, RejectedTransfer):
        assert db.exec(select(model)).all() == []
    assert db.get(Transaction, refund_id).refund_of_transaction_id is None


@pytest.mark.parametrize('shared', [True, False])
def test_pair_delete_denied_for_readonly_or_private_peer_single_delete_allowed(auth_client_a, db, accounts, shared):
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    accounts[1].owner_id = bob.id; db.add(accounts[1])
    if shared:
        db.add(AccountShare(account_id=accounts[1].id, user_id=alice.id, permission='read_only'))
    db.commit()
    out, incoming, pair = paired(db, accounts)
    peer_id, pair_id = incoming.id, pair.id
    detail = auth_client_a.get(f'/api/v1/transactions/{out.id}').json()
    assert detail['deletion_info']['can_delete'] is True
    assert detail['deletion_info']['can_delete_pair'] is False
    if not shared:
        assert detail['paired_transfer']['counterpart']['amount'] is None
    response = remove(auth_client_a, out, pair, 'pair')
    assert response.status_code == 403, response.text
    db.expire_all()
    assert db.get(Transfer, pair_id) and db.get(Transaction, peer_id)
    assert remove(auth_client_a, out, pair).status_code == 200
    db.expire_all()
    assert db.get(Transaction, peer_id).transaction_type == 'transfer'


@pytest.mark.parametrize('scope', ['single', 'pair'])
def test_scheduled_peer_cannot_be_deleted_or_unlinked(auth_client_a, db, accounts, scope):
    out, incoming, pair = paired(db, accounts)
    incoming.extra = {'scheduled_occurrence_id': str(uuid4())}; db.add(incoming); db.commit()
    response = remove(auth_client_a, out, pair, scope)
    assert response.status_code == 409, response.text
    db.expire_all()
    assert db.get(Transaction, out.id) and db.get(Transfer, pair.id)


def test_broken_cross_family_pair_is_not_a_delete_shortcut(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    family = Family(name='Other tenant'); db.add(family); db.flush()
    accounts[1].family_id = family.id; db.add(accounts[1]); db.commit()
    response = remove(auth_client_a, out, pair, 'pair')
    assert response.status_code == 409
    db.expire_all()
    assert db.get(Transaction, incoming.id) and db.get(Transaction, out.id)


@pytest.mark.parametrize('which', ['purchase', 'refund'])
def test_refund_deletion_only_unlinks_and_retains_the_other_transaction(auth_client_a, db, accounts, which):
    original = activity(db, accounts[0])
    refund = activity(db, accounts[1], 'refund', 20, refund_of_transaction_id=original.id)
    db.add(RefundAllocation(original_transaction_id=original.id, refund_transaction_id=refund.id, allocated_amount=Decimal(20)))
    db.commit()
    row = original if which == 'purchase' else refund
    retained_id = refund.id if which == 'purchase' else original.id
    detail = auth_client_a.get(f'/api/v1/transactions/{row.id}').json()['deletion_info']
    assert (detail['linked_refund_count'] == 1) if which == 'purchase' else detail['has_refund_links']
    response = auth_client_a.delete(f'/api/v1/transactions/{row.id}')
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Transaction, retained_id) is not None
    assert db.get(Transaction, retained_id).refund_of_transaction_id is None
    assert db.exec(select(RefundAllocation)).all() == []


def test_convert_expense_to_transfer_creates_one_counterpart_and_updates_balances(auth_client_a, db, accounts):
    original = activity(db, accounts[0])
    payload = {'transaction_type': 'transfer', 'to_account_id': str(accounts[1].id)}
    response = auth_client_a.patch(f'/api/v1/transactions/{original.id}', json=payload)
    assert response.status_code == 200, response.text
    pair_id = response.json()['paired_transfer']['transfer_id']
    assert balance(db, accounts[0]) == -100 and balance(db, accounts[1]) == 100
    # Retrying the same edit must update the existing peer, not create another.
    response = auth_client_a.patch(f'/api/v1/transactions/{original.id}', json=payload)
    assert response.status_code == 200, response.text
    db.expire_all()
    assert len(db.exec(select(Transaction)).all()) == 2
    assert len(db.exec(select(Transfer)).all()) == 1
    assert response.json()['paired_transfer']['transfer_id'] == pair_id


def test_changing_destination_moves_existing_inflow_without_duplicate(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    incoming_id, pair_id = incoming.id, pair.id
    response = auth_client_a.patch(f'/api/v1/transactions/{out.id}', json={'to_account_id': str(accounts[2].id)})
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Transaction, incoming_id).account_id == accounts[2].id
    assert response.json()['paired_transfer']['transfer_id'] == str(pair_id)
    assert balance(db, accounts[0]) == -100 and balance(db, accounts[1]) == 0 and balance(db, accounts[2]) == 100
    assert len(db.exec(select(Transaction)).all()) == 2


def test_paired_amount_time_and_original_money_update_together(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    peer_id, pair_id = incoming.id, pair.id
    response = auth_client_a.patch(f'/api/v1/transactions/{out.id}', json={
        'amount': '250', 'occurred_at': '2026-09-10T18:15:12Z'})
    assert response.status_code == 200, response.text
    db.expire_all(); peer = db.get(Transaction, peer_id)
    assert peer.amount == peer.original_amount == 250 and db.get(Transfer, pair_id).amount == 250
    assert peer.transacted_at == date(2026, 9, 11) and peer.occurred_at == datetime(2026, 9, 10, 18, 15, 12)
    assert balance(db, accounts[0]) == -250 and balance(db, accounts[1]) == 250


@pytest.mark.parametrize('failure', ['readonly', 'cross_family', 'same_account', 'inactive'])
def test_invalid_destination_leaves_expense_and_balances_unchanged(auth_client_a, db, accounts, failure):
    destination = accounts[1]
    if failure == 'readonly':
        bob = db.exec(select(User).where(User.username == 'bob')).one()
        alice = db.exec(select(User).where(User.username == 'alice')).one()
        destination.owner_id = bob.id
        db.add(AccountShare(account_id=destination.id, user_id=alice.id, permission='read_only'))
    elif failure == 'cross_family':
        family = Family(name='Separate family'); db.add(family); db.flush(); destination.family_id = family.id
    elif failure == 'same_account':
        destination = accounts[0]
    else:
        destination.is_active = False
    db.add(destination); db.commit()
    row = activity(db, accounts[0]); row_id = row.id
    response = auth_client_a.patch(f'/api/v1/transactions/{row_id}', json={
        'transaction_type': 'transfer', 'to_account_id': str(destination.id)})
    assert response.status_code in (400, 403), response.text
    db.expire_all()
    assert db.get(Transaction, row_id).transaction_type == 'expense'
    assert len(db.exec(select(Transaction)).all()) == 1


def test_cross_currency_destination_requires_verified_amount_and_preserves_ratio(auth_client_a, db, accounts):
    accounts[1].currency = 'USD'; db.add(accounts[1]); db.commit()
    row = activity(db, accounts[0])
    payload = {'transaction_type': 'transfer', 'to_account_id': str(accounts[1].id)}
    assert auth_client_a.patch(f'/api/v1/transactions/{row.id}', json=payload).status_code == 422
    response = auth_client_a.patch(f'/api/v1/transactions/{row.id}', json={**payload, 'destination_amount': '14'})
    assert response.status_code == 200, response.text
    peer_id = UUID(response.json()['paired_transfer']['counterpart']['id'])
    response = auth_client_a.patch(f'/api/v1/transactions/{row.id}', json={'amount': '200'})
    assert response.status_code == 200, response.text
    db.expire_all(); peer = db.get(Transaction, peer_id)
    assert peer.currency == peer.original_currency == 'USD' and peer.amount == peer.original_amount == 28
    assert balance(db, accounts[0]) == -200 and balance(db, accounts[1]) == 28


def test_incoming_pair_can_move_destination_using_its_account_selector(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    response = auth_client_a.patch(f'/api/v1/transactions/{incoming.id}', json={'account_id': str(accounts[2].id)})
    assert response.status_code == 200, response.text
    assert balance(db, accounts[0]) == -100 and balance(db, accounts[1]) == 0 and balance(db, accounts[2]) == 100


@pytest.mark.parametrize('side', ['outgoing', 'incoming'])
def test_both_transfer_accounts_can_be_changed_together_from_either_side(auth_client_a, db, accounts, side):
    out, incoming, pair = paired(db, accounts)
    row = out if side == 'outgoing' else incoming
    ids, pair_id = {out.id, incoming.id}, pair.id
    response = auth_client_a.patch(f'/api/v1/transactions/{row.id}', json={
        'from_account_id': str(accounts[1].id), 'to_account_id': str(accounts[0].id)})
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Transaction, out.id).account_id == accounts[1].id
    assert db.get(Transaction, incoming.id).account_id == accounts[0].id
    assert db.get(Transfer, pair_id).outflow_transaction_id == out.id
    assert {txn.id for txn in db.exec(select(Transaction)).all()} == ids
    assert balance(db, accounts[0]) == 100 and balance(db, accounts[1]) == -100


def test_incoming_transfer_can_move_the_outgoing_account(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    response = auth_client_a.patch(f'/api/v1/transactions/{incoming.id}', json={'from_account_id': str(accounts[2].id)})
    assert response.status_code == 200, response.text
    assert balance(db, accounts[0]) == 0 and balance(db, accounts[1]) == 100 and balance(db, accounts[2]) == -100
    assert db.get(Transaction, out.id).extra['to_account_id'] == str(accounts[1].id)
    assert db.get(Transaction, incoming.id).extra['from_account_id'] == str(accounts[2].id)


@pytest.mark.parametrize('invalid', ['readonly', 'cross_family', 'same_account', 'inactive'])
def test_invalid_outgoing_account_edit_is_atomic(auth_client_a, db, accounts, invalid):
    out, incoming, pair = paired(db, accounts)
    target = accounts[2]
    if invalid == 'readonly':
        alice = db.exec(select(User).where(User.username == 'alice')).one()
        bob = db.exec(select(User).where(User.username == 'bob')).one()
        target.owner_id = bob.id
        db.add(AccountShare(account_id=target.id, user_id=alice.id, permission='read_only'))
    elif invalid == 'cross_family':
        family = Family(name='Another tenant'); db.add(family); db.flush(); target.family_id = family.id
    elif invalid == 'same_account':
        target = accounts[1]
    else:
        target.is_active = False
    db.add(target); db.commit()
    response = auth_client_a.patch(f'/api/v1/transactions/{incoming.id}', json={'from_account_id': str(target.id)})
    assert response.status_code in {400, 403}, response.text
    db.expire_all()
    assert db.get(Transaction, out.id).account_id == accounts[0].id
    assert db.get(Transaction, incoming.id).account_id == accounts[1].id
    assert db.get(Transaction, out.id).amount == db.get(Transaction, incoming.id).amount == 100


def test_readonly_original_source_cannot_be_moved_to_an_owned_account(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    accounts[0].owner_id = bob.id; db.add(accounts[0])
    db.add(AccountShare(account_id=accounts[0].id, user_id=alice.id, permission='read_only')); db.commit()
    response = auth_client_a.patch(f'/api/v1/transactions/{incoming.id}', json={'from_account_id': str(accounts[2].id)})
    assert response.status_code == 403
    db.expire_all()
    assert db.get(Transaction, out.id).account_id == accounts[0].id


def test_incoming_cross_currency_source_edit_requires_actual_amount(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    accounts[2].currency = 'USD'; db.add(accounts[2]); db.commit()
    payload = {'from_account_id': str(accounts[2].id)}
    url = f'/api/v1/transactions/{incoming.id}'
    assert auth_client_a.patch(url, json=payload).status_code == 422
    response = auth_client_a.patch(url, json={**payload, 'source_amount': '14'})
    assert response.status_code == 200, response.text
    assert balance(db, accounts[0]) == 0 and balance(db, accounts[1]) == 100 and balance(db, accounts[2]) == -14
    db.expire_all()
    assert db.get(Transaction, out.id).currency == 'USD' and db.get(Transfer, pair.id).amount == 14


def test_changing_current_side_currency_preserves_confirmed_peer_money(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    accounts[2].currency = 'USD'; db.add(accounts[2])
    db.add(ExchangeRateSnapshot(requested_date=DAY, effective_date=DAY, base_currency='EUR',
        rates={'EUR': '1', 'USD': '1', 'CNY': '7'})); db.commit()
    url = f'/api/v1/transactions/{out.id}'
    payload = {'from_account_id': str(accounts[2].id), 'amount': '14', 'settlement_amount': '14', 'settlement_currency': 'USD'}
    assert auth_client_a.patch(url, json=payload).status_code == 422
    response = auth_client_a.patch(url, json={**payload, 'destination_amount': '100'})
    assert response.status_code == 200, response.text
    assert balance(db, accounts[0]) == 0 and balance(db, accounts[1]) == 100 and balance(db, accounts[2]) == -14


def test_incoming_standalone_transfer_can_attach_a_source_without_duplicates(auth_client_a, db, accounts):
    row = activity(db, accounts[1], 'income')
    payload = {'transaction_type': 'transfer', 'transfer_direction': 'inflow', 'from_account_id': str(accounts[0].id)}
    url = f'/api/v1/transactions/{row.id}'
    first = auth_client_a.patch(url, json=payload)
    assert first.status_code == 200, first.text
    second = auth_client_a.patch(url, json=payload)
    assert second.status_code == 200, second.text
    assert first.json()['paired_transfer']['transfer_id'] == second.json()['paired_transfer']['transfer_id']
    assert balance(db, accounts[0]) == -100 and balance(db, accounts[1]) == 100
    assert len(db.exec(select(Transaction)).all()) == 2


def test_convert_to_refund_and_link_original_is_one_atomic_edit(auth_client_a, db, accounts):
    category = Category(family_id=accounts[0].family_id, name='Dining', category_type='expense')
    db.add(category); db.commit()
    original = activity(db, accounts[0], category_id=category.id)
    changed = activity(db, accounts[1], amount=20, narration='Different merchant')
    response = auth_client_a.patch(f'/api/v1/transactions/{changed.id}', json={
        'transaction_type': 'refund', 'refund_of_transaction_id': str(original.id), 'allocation_amount': '20',
        'allocation_currency': 'CNY'})
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail['refund_info']['is_linked'] and not detail['refund_info']['category_editable']
    assert detail['category_name'] == 'Dining'
    assert len(db.exec(select(RefundAllocation)).all()) == 1


def test_invalid_refund_match_rolls_back_type_change(auth_client_a, db, accounts):
    row = activity(db, accounts[0]); row_id = row.id
    response = auth_client_a.patch(f'/api/v1/transactions/{row_id}', json={
        'transaction_type': 'refund', 'refund_of_transaction_id': str(uuid4())})
    assert response.status_code == 400, response.text
    db.expire_all()
    assert db.get(Transaction, row_id).transaction_type == 'expense'
    assert db.exec(select(RefundAllocation)).all() == []


def test_daily_newest_first_is_applied_before_cursor_pagination(auth_client_a, db, accounts):
    rows = [activity(db, accounts[0], occurred_at=datetime(2026, 9, 9, hour)) for hour in (8, 12, 16)]
    previous = activity(db, accounts[0], transacted_at=DAY - timedelta(days=1), occurred_at=datetime(2026, 9, 8, 23))
    response = auth_client_a.get('/api/v1/transactions', params={'account_id': str(accounts[0].id), 'limit': 2})
    assert response.status_code == 200, response.text
    first = response.json()
    assert [row['id'] for row in first['items']] == [str(rows[2].id), str(rows[1].id)]
    response = auth_client_a.get('/api/v1/transactions', params={
        'account_id': str(accounts[0].id), 'limit': 2, 'cursor': first['next_cursor']})
    assert [row['id'] for row in response.json()['items']] == [str(rows[0].id), str(previous.id)]


def test_budget_drilldown_uses_budget_currency_even_if_user_display_currency_differs(auth_client_a, db, accounts):
    db.add(UserPreference(username='alice', currency='USD'))
    db.add(ExchangeRateSnapshot(requested_date=DAY, effective_date=DAY, base_currency='EUR',
                               rates={'EUR': '1', 'USD': '1', 'CNY': '7'}))
    category = Category(family_id=accounts[0].family_id, name='Dining', category_type='expense')
    db.add(category); db.commit()
    activity(db, accounts[0], amount=70, category_id=category.id)
    budget = auth_client_a.get('/api/v1/budgets/summary?month=2026-09')
    assert budget.status_code == 200, budget.text
    detail = auth_client_a.get('/api/v1/transactions', params={
        'category_name': 'Dining', 'transaction_type': 'expense,refund', 'start_date': '2026-09-01',
        'end_date': '2026-09-30', 'spending_net': 'true', 'spending_currency': budget.json()['currency']})
    assert detail.status_code == 200, detail.text
    assert detail.json()['spending_summary']['currency'] == 'CNY'
    assert detail.json()['spending_summary']['net'] == budget.json()['total_spent'] == 70


def test_own_label_edit_does_not_write_a_readonly_transfer_peer(auth_client_a, db, accounts):
    out, incoming, pair = paired(db, accounts)
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    accounts[1].owner_id = bob.id; db.add(accounts[1])
    db.add(AccountShare(account_id=accounts[1].id, user_id=alice.id, permission='read_only'))
    db.commit(); peer_id = incoming.id; previous_extra = incoming.extra
    response = auth_client_a.patch(f'/api/v1/transactions/{out.id}', json={'narration': 'Renamed own side'})
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Transaction, peer_id).extra == previous_extra
    assert db.get(Transaction, peer_id).narration == 'Regression activity'
    response = auth_client_a.patch(f'/api/v1/transactions/{out.id}', json={'amount': '200'})
    assert response.status_code == 403
    assert balance(db, accounts[0]) == -100 and balance(db, accounts[1]) == 100


def card_payment(db, accounts):
    master, child = accounts[1], accounts[2]
    master.account_type = child.account_type = 'credit_card'
    master.classification = child.classification = 'liability'
    db.add_all([master, child]); db.flush()
    child.parent_account_id = master.id; db.add(child); db.commit()
    activity(db, master, amount=300); activity(db, child, amount=200)
    out = activity(db, accounts[0], 'transfer', 500, extra={'direction': 'outflow'},
                   transacted_at=DAY + timedelta(days=1), occurred_at=datetime(2026, 9, 10, 10))
    incoming = activity(db, master, 'transfer', 500, extra={'direction': 'inflow'},
                        transacted_at=out.transacted_at, occurred_at=out.occurred_at)
    pair = Transfer(family_id=master.family_id, outflow_transaction_id=out.id,
                    inflow_transaction_id=incoming.id, amount=Decimal(500))
    db.add(pair); db.flush(); out.transfer_id = incoming.transfer_id = pair.id
    db.add_all([out, incoming]); db.commit()
    assert balance(db, master) == balance(db, child) == 0
    return out, incoming, pair


def test_deleting_both_repayment_legs_replays_primary_and_secondary_debt(auth_client_a, db, accounts):
    out, incoming, pair = card_payment(db, accounts)
    response = remove(auth_client_a, out, pair, 'pair')
    assert response.status_code == 200, response.text
    assert balance(db, accounts[0]) == 0
    assert balance(db, accounts[1]) == 500 and balance(db, accounts[2]) == 200
    state = db.get(CardSettlementState, accounts[1].id)
    assert not state.allocations


@pytest.mark.parametrize('operation', ['single', 'pair', 'edit'])
def test_closed_card_period_rejects_delete_or_edit_atomically(auth_client_a, db, accounts, operation):
    out, incoming, pair = card_payment(db, accounts)
    peer_id, source_id, pair_id = incoming.id, out.id, pair.id
    accounts[2].parent_account_id = None; db.add(accounts[2]); db.commit()
    response = (auth_client_a.patch(f'/api/v1/transactions/{out.id}', json={'amount': '200'})
                if operation == 'edit' else remove(auth_client_a, incoming, pair, operation))
    assert response.status_code == 409, response.text
    db.expire_all()
    assert db.get(Transaction, source_id).amount == 500 and db.get(Transaction, peer_id).amount == 500
    assert db.get(Transfer, pair_id).amount == 500
    assert balance(db, accounts[0]) == -500 and balance(db, accounts[1]) == 0


@pytest.mark.parametrize('reimbursement_type', ['corporate', 'personal_advance'])
def test_income_reimbursement_and_advance_settings_are_preserved(auth_client_a, db, accounts, reimbursement_type):
    row = activity(db, accounts[0], 'income', is_reimbursable=True, excluded_from_stats=True,
                   extra={'reimbursement_type': reimbursement_type, 'counterparty': 'Payer'}, reimbursement_status='待还款')
    response = auth_client_a.patch(f'/api/v1/transactions/{row.id}', json={'narration': 'Receipt renamed'})
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail['is_reimbursable'] and detail['excluded_from_stats']
    assert detail['reimbursement_type'] == reimbursement_type and detail['counterparty'] == 'Payer'

"""Replay the ledger using the settlement relationship at each financial event."""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from services.account_types import financial_classification
from services.booking_money import money
from services.card_history import boundary_key, load_component, naive_utc, CLOSED_PERIOD
from services.card_settlement import CardGroup, _event_key, settlement_value, ZERO
from services.transaction_direction import transaction_direction
from models import Account


def replay(session, anchor, cutoff=None, use_cache=True, *, observe=None, inputs=None):
    cached = inputs if inputs is not None else (session.info.setdefault('card_group_inputs', {}).get(anchor.id) if use_cache else None)
    if cached is None:
        refresh = use_cache and not session.new and not session.dirty and not session.deleted
        cached = load_component(session, anchor, refresh=refresh)
        if use_cache:
            session.info.setdefault('card_group_inputs', {})[anchor.id] = cached
    cards, activities, allocations, pairs, memberships = cached
    groups = {key: CardGroup(card, {key: card}) for key, card in cards.items()}
    parents = {}
    def root_of(account_id):
        seen = set()
        while account_id in parents:
            if account_id in seen:
                raise HTTPException(409, '主副卡结算关系存在循环')
            seen.add(account_id)
            account_id = parents[account_id]
        return account_id

    def join(row):
        root_id = root_of(row.master_account_id)
        if root_id == row.account_id or row.account_id in parents or root_id != row.master_account_id:
            raise HTTPException(409, '主副卡结算关系存在循环或重叠')
        own = groups[row.account_id]
        if own.balance or own.lots:
            raise HTTPException(409, CLOSED_PERIOD)
        parents[row.account_id] = root_id
        groups[root_id].cards[row.account_id] = cards[row.account_id]

    initial = [row for row in memberships if row.started_at is None]
    for row in sorted(initial, key=lambda row: str(row.account_id)):
        join(row)
    events = [(_event_key(txn), 'transaction', txn) for txn in activities]
    for row in memberships:
        if row.started_at is not None:
            events.append((boundary_key(row.started_at), 'join', row))
        if row.ended_at is not None:
            events.append((boundary_key(row.ended_at), 'leave', row))
    with_history = {txn.account_id for txn in activities}
    for card in cards.values():
        if card.id not in with_history and not card.ledger_initialized and card.balance:
            stamp = naive_utc(card.created_at)
            day = boundary_key(stamp)[0]
            events.append(((day, stamp, datetime.min, str(card.id)), 'opening', card))

    by_id = {txn.id: txn for txn in activities}
    refund_targets = {}
    for allocation in allocations:
        original = by_id.get(allocation.original_transaction_id)
        if original is None:
            continue
        native = allocation.original_book_amount
        if native is None:
            native = allocation.allocated_amount * original.amount / (original.original_amount or original.amount)
        refund_targets.setdefault(allocation.refund_transaction_id, []).append((original, money(native)))

    # Closing and opening at the same instant must be ordered independently of
    # random UUIDs. Transaction timestamps equal to closure belong to the old group.
    order = {'transaction': 0, 'opening': 0, 'leave': 1, 'join': 2}
    for key, event_kind, event in sorted(events, key=lambda item: (item[0], order[item[1]])):
        if cutoff and key[0] > cutoff:
            continue
        if observe:
            observe(key[0], groups, parents)
        if event_kind == 'join':
            join(event)
            continue
        if event_kind == 'leave':
            group = groups[root_of(event.account_id)]
            if group.native_balance(event.account_id) != 0 or group.outstanding(event.account_id) != 0:
                raise HTTPException(409, CLOSED_PERIOD)
            parents.pop(event.account_id, None)
            group.cards.pop(event.account_id, None)
            continue
        account_id = event.id if event_kind == 'opening' else event.account_id
        card = cards[account_id]
        group = groups[root_of(account_id)]
        if event_kind == 'opening':
            if card.currency != group.master.currency:
                raise HTTPException(409, '外币副卡期初余额缺少已核实的主卡结算，请先核对')
            if card.balance > 0:
                group.charge(None, money(card.balance), money(card.balance), card.id)
            else:
                group.receive(None, money(-card.balance), 'opening', card.id)
            continue
        txn = event
        kind = txn.transaction_type
        if kind not in {'expense', 'income', 'refund', 'transfer', 'adjustment'}:
            continue
        value = settlement_value(txn, card, group.master)
        down = (txn.extra or {}).get('direction') == 'decrease' or (not txn.extra and '(-' in (txn.narration or ''))
        # A standalone former card can become an asset. Group balances use a
        # debt sign internally; the API reverses that sign for standalone assets.
        debt = account_id in parents or len(group.cards) > 1 or financial_classification(group.master) == 'liability'
        direction_account = card if not debt or financial_classification(card) == 'liability' else Account(
            id=card.id, name='', account_type='credit_card', currency=card.currency)
        incoming = kind in {'income', 'refund'} or (kind == 'transfer' and (
            txn.id == pairs[txn.transfer_id].inflow_transaction_id if txn.transfer_id in pairs
            else transaction_direction(txn, session, direction_account) == 'inflow')) or (
            kind == 'adjustment' and (down if debt else not down))
        if not incoming:
            group.charge(txn, money(txn.amount), value)
            continue
        if kind == 'refund':
            targets = refund_targets.get(txn.id, [])
            original = by_id.get(txn.refund_of_transaction_id)
            if not targets and original:
                targets = [(original, money(txn.amount if txn.currency == original.currency else ZERO))]
            removed = ZERO
            for original, native in targets:
                if original.account_id in group.cards:
                    removed += group.consume(txn, group.outstanding(original.account_id), original.account_id,
                                             'refund', transaction_id=original.id, native_limit=native)
            difference = money(value - removed)
            if difference < 0:
                group.charge(txn, -difference, -difference, group.master.id)
            else:
                group.receive(txn, difference, 'refund', card.id)
            continue
        priority = card.id if card.id != group.master.id else None
        allocation_kind = 'adjustment' if kind == 'adjustment' else 'repayment'
        if kind == 'transfer' and txn.transfer_id in pairs:
            outgoing = by_id.get(pairs[txn.transfer_id].outflow_transaction_id)
            if outgoing and root_of(outgoing.account_id) == group.master.id:
                priority = card.id
                allocation_kind = 'internal_transfer'
        group.receive(txn, value, allocation_kind, priority)
    if observe:
        observe(None, groups, parents)
    return groups, parents, memberships


def replay_at_dates(session, anchor, dates):
    """Capture immutable balance values at every cutoff in one ledger replay.

    No extra payments, balances or allocations are persisted. The same replay
    handles original refunds, fixed FX settlements and dated link changes.
    """
    dates = sorted(set(dates))
    if not dates:
        return {}
    inputs = load_component(session, anchor,
        refresh=not (session.new or session.dirty or session.deleted))
    cards = inputs[0]
    history, index = {}, 0

    def capture(next_day, groups, parents):
        nonlocal index
        while index < len(dates) and (next_day is None or dates[index] < next_day):
            balances = {}
            for account_id in cards:
                root = account_id
                while root in parents:
                    root = parents[root]
                group = groups[root]
                value = group.balance if root == account_id else group.outstanding(account_id)
                balances[account_id] = (root, value, group.master.currency)
            history[dates[index]] = balances
            index += 1

    replay(session, anchor, cutoff=dates[-1], use_cache=False, observe=capture, inputs=inputs)
    return history

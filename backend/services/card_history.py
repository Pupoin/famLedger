"""Dated card relationships and minimal evidence for closed settlement periods."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlmodel import select, or_

from models import (Account, CardMembership, CardSettlementArchive, RefundAllocation,
                    Transaction, Transfer)

CLEAR_REQUIRED = '副卡待还未清零，请先还清再更换主卡、解绑、修改类型、取消关联共享或删除'
CLOSED_PERIOD = '该修改会使已解绑的副卡结算期间重新产生欠款，请同时核对该期间的消费、退款和还款'


def naive_utc(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def boundary_key(value):
    stamp = naive_utc(value)
    day = stamp.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date()
    return day, stamp, datetime.max, '\uffff'


def history_exists(session, account_id):
    return session.scalars(select(CardMembership.id).where(or_(
        CardMembership.account_id == account_id, CardMembership.master_account_id == account_id))).first() is not None


def load_component(session, root, refresh=False):
    """Follow only recorded settlement edges, including closed/deleted members."""
    ids = {root.id}
    memberships = {}
    while True:
        before = len(ids)
        rows = session.scalars(select(CardMembership).where(or_(
            CardMembership.account_id.in_(ids), CardMembership.master_account_id.in_(ids)))
            .execution_options(populate_existing=refresh)).all()
        for row in rows:
            memberships[row.id] = row
            memberships.pop(('initial', row.account_id), None)
            ids.update((row.account_id, row.master_account_id))
        # Existing current links without a recorded interval are initial links.
        # This read-only fallback never rewrites or guesses financial amounts.
        links = session.execute(select(Account.id, Account.parent_account_id, Account.currency)
            .where(or_(Account.id.in_(ids), Account.parent_account_id.in_(ids)))).all()
        known_children = {row.account_id for row in memberships.values()}
        for account_id, parent_id, currency in links:
            ids.add(account_id)
            if parent_id:
                ids.add(parent_id)
                if account_id not in known_children:
                    parent_currency = session.scalar(select(Account.currency).where(Account.id == parent_id))
                    if parent_currency:
                        memberships[('initial', account_id)] = CardMembership(
                            account_id=account_id, master_account_id=parent_id,
                            currency=currency, settlement_currency=parent_currency)
        if len(ids) == before:
            break
    cards = {card.id: card for card in session.scalars(select(Account).where(Account.id.in_(ids))
             .execution_options(populate_existing=refresh)).all()}
    archives = session.scalars(select(CardSettlementArchive).where(CardSettlementArchive.account_id.in_(ids))
                              .execution_options(populate_existing=refresh)).all()
    activities = session.scalars(select(Transaction).where(Transaction.account_id.in_(ids))
                                .execution_options(populate_existing=refresh)).all()
    by_id = {row.id: row for row in activities}
    archived_refunds, archived_transfers = {}, {}
    for archive in archives:
        cards.setdefault(archive.account_id, Account(id=archive.account_id, name='', family_id=root.family_id,
                         account_type=archive.account_type, currency=archive.currency))
        for data in archive.transactions:
            row = Transaction.model_validate(data)
            by_id.setdefault(row.id, row)
        for data in archive.refunds:
            row = RefundAllocation.model_validate(data)
            archived_refunds[row.id] = row
        for data in archive.transfers:
            row = Transfer.model_validate(data)
            archived_transfers[row.id] = row
    for membership in memberships.values():
        cards.setdefault(membership.account_id, Account(id=membership.account_id, name='', family_id=root.family_id,
                         account_type='credit_card', currency=membership.currency))
        cards.setdefault(membership.master_account_id, Account(id=membership.master_account_id, name='', family_id=root.family_id,
                         account_type='credit_card', currency=membership.settlement_currency))
    txn_ids = set(by_id)
    allocations = {row.id: row for row in session.scalars(select(RefundAllocation).where(
        RefundAllocation.refund_transaction_id.in_(txn_ids)).execution_options(populate_existing=refresh)).all()} if txn_ids else {}
    allocations = {**archived_refunds, **allocations}
    pair_ids = {txn.transfer_id for txn in by_id.values() if txn.transfer_id}
    pairs = {row.id: row for row in session.scalars(select(Transfer).where(Transfer.id.in_(pair_ids))
             .execution_options(populate_existing=refresh)).all()} if pair_ids else {}
    return cards, list(by_id.values()), list(allocations.values()), {**archived_transfers, **pairs}, list(memberships.values())


def require_clear(session, account, previous_parent_id=None):
    from services.card_settlement import replay_component
    previous_parent_id = previous_parent_id or account.parent_account_id
    anchor = session.get(Account, previous_parent_id) if previous_parent_id else account
    if not anchor:
        return
    groups, parents, _ = replay_component(session, anchor, use_cache=False)
    group = groups[parents.get(account.id, account.id)]
    if group.native_balance(account.id) != 0 or group.outstanding(account.id) != 0:
        raise HTTPException(409, CLEAR_REQUIRED)


def link_can_change(session, account):
    from services.account_balances import current_snapshot
    snapshot = current_snapshot(session, account)
    if snapshot is not None and (account.parent_account_id or history_exists(session, account.id)):
        return snapshot.latest_own_balance == 0 and snapshot.latest_settlement_balance == 0
    if not account.parent_account_id and not history_exists(session, account.id):
        return True
    from services.card_settlement import group_for_account
    group = group_for_account(session, account)
    return bool(group and group.native_balance(account.id) == 0 and group.outstanding(account.id) == 0)


def maintain_memberships(session):
    """Validate pending link changes and record their effective UTC time."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    candidates = [row for row in list(session.new) + list(session.dirty) if isinstance(row, Account)]
    for card in candidates:
        state = inspect(card)
        if card in session.new:
            previous = None
            changed = bool(card.parent_account_id)
        else:
            changed = state.attrs.parent_account_id.history.has_changes()
            previous = session.scalar(select(Account.parent_account_id).where(Account.id == card.id)) if changed else None
        if not changed or previous == card.parent_account_id:
            continue
        prior = session.scalars(select(CardMembership).where(CardMembership.account_id == card.id,
                               CardMembership.ended_at.is_(None))).first()
        historical = history_exists(session, card.id)
        if previous:
            require_clear(session, card, previous)
            if prior is None:
                master = session.get(Account, previous)
                prior = CardMembership(account_id=card.id, master_account_id=previous,
                                       currency=card.currency, settlement_currency=master.currency)
            prior.ended_at = now
            session.add(prior)
        elif historical:
            require_clear(session, card)
        if card.parent_account_id:
            master = session.get(Account, card.parent_account_id)
            if master is None:
                master = next((row for row in session.new if isinstance(row, Account) and row.id == card.parent_account_id), None)
            if master is None or master.family_id != card.family_id:
                raise HTTPException(409, '副卡的主卡关系已失效')
            from services.account_types import account_type_is
            children = session.scalars(select(Account).where(Account.parent_account_id == card.id)).all()
            children.extend(row for row in session.new if isinstance(row, Account) and row.parent_account_id == card.id)
            if (master.id == card.id or master.parent_account_id or any(row.parent_account_id == card.id for row in children)
                    or not account_type_is(master.account_type, 'credit_card') or not account_type_is(card.account_type, 'credit_card')):
                raise HTTPException(409, '主副卡必须是信用卡，且不支持多级关联')
            # A former supplementary card can later become a primary. Its new
            # children must not be retroactively nested inside its old group.
            former_child = session.scalar(select(CardMembership.id).where(CardMembership.account_id == master.id)) is not None
            starts_late = bool(previous or historical or former_child)
            if former_child and not previous and not historical:
                if card in session.new:
                    if card.balance:
                        raise HTTPException(409, CLEAR_REQUIRED)
                else:
                    require_clear(session, card)
            session.add(CardMembership(account_id=card.id, master_account_id=master.id,
                        currency=card.currency, settlement_currency=master.currency,
                        started_at=now if starts_late else None))


def parent_at(session, account, txn):
    """Use the relationship at the financial date, rather than the current link."""
    from services.card_settlement import _event_key
    key = _event_key(txn)
    memberships = session.scalars(select(CardMembership).where(CardMembership.account_id == account.id)).all()
    memberships.extend(row for row in session.new if isinstance(row, CardMembership) and row.account_id == account.id)
    eligible = [row for row in memberships if (row.started_at is None or key > boundary_key(row.started_at))
                and (row.ended_at is None or key <= boundary_key(row.ended_at))]
    if eligible:
        return max(eligible, key=lambda row: naive_utc(row.started_at) if row.started_at else datetime.min)
    if not memberships and account.parent_account_id:
        master = session.get(Account, account.parent_account_id)
        if master:
            return CardMembership(account_id=account.id, master_account_id=master.id,
                                  currency=account.currency, settlement_currency=master.currency)
    return None


def archive_account(session, account):
    """Keep only financial amounts/directions needed by another card's history."""
    if not history_exists(session, account.id):
        return
    from services.transaction_direction import transaction_direction
    activities = session.scalars(select(Transaction).where(Transaction.account_id == account.id)).all()
    ids = {row.id for row in activities}
    fields = {'id', 'account_id', 'transacted_at', 'occurred_at', 'created_at', 'amount', 'currency',
              'original_amount', 'original_currency', 'transaction_type', 'master_account_id',
              'master_settlement_amount', 'master_settlement_currency', 'refund_of_transaction_id', 'transfer_id'}
    records = []
    for row in activities:
        data = row.model_dump(mode='json', include=fields)
        data['narration'] = ''
        direction_account = Account(id=account.id, name='', account_type='credit_card', currency=account.currency) if parent_at(session, account, row) else account
        data['extra'] = {'direction': transaction_direction(row, session, direction_account)} if row.transaction_type == 'transfer' else {
            'direction': (row.extra or {}).get('direction', 'decrease' if '(-' in (row.narration or '') else 'increase')}
        records.append(data)
    refunds = session.scalars(select(RefundAllocation).where(or_(
        RefundAllocation.refund_transaction_id.in_(ids), RefundAllocation.original_transaction_id.in_(ids)))).all() if ids else []
    transfers = session.scalars(select(Transfer).where(or_(
        Transfer.inflow_transaction_id.in_(ids), Transfer.outflow_transaction_id.in_(ids)))).all() if ids else []
    archive = session.get(CardSettlementArchive, account.id) or CardSettlementArchive(
        account_id=account.id, currency=account.currency, account_type=account.account_type)
    archive.transactions = records
    archive.refunds = [row.model_dump(mode='json') for row in refunds]
    archive.transfers = [row.model_dump(mode='json') for row in transfers]
    session.add(archive)

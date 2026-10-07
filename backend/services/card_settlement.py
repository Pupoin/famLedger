"""One card-group debt, with deterministic allocations in fixed booking money.

Allocations are derived from the original ledger, never extra repayment income.
Reads replay without writing; writes persist the same result in their transaction.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, event, inspect
from sqlalchemy.orm import Session as SASession
from sqlmodel import select

from models import (Account, CardSettlementState, CardMembership, CardSettlementArchive,
                    RefundAllocation, Transaction, Transfer)
from services.account_types import account_type_is
from services.booking_money import MONEY, RATE, money
from services.transaction_direction import transaction_direction

ZERO = Decimal(0)


@dataclass
class Lot:
    account_id: object
    transaction_id: object
    native: Decimal
    settlement: Decimal


@dataclass
class CardGroup:
    master: Account
    cards: dict
    lots: list = field(default_factory=list)
    credit: Decimal = ZERO
    allocations: list = field(default_factory=list)
    credits: list = field(default_factory=list)

    def outstanding(self, account_id):
        return sum((lot.settlement for lot in self.lots if lot.account_id == account_id), ZERO)

    def native_balance(self, account_id):
        value = sum((lot.native for lot in self.lots if lot.account_id == account_id), ZERO)
        return money(value - self.credit if account_id == self.master.id else value)

    @property
    def balance(self):
        return money(sum((lot.settlement for lot in self.lots), ZERO) - self.credit)

    def record(self, source, lot, settlement, native, kind):
        self.allocations.append({
            "source_transaction_id": str(source.id) if source else None,
            "source_account_id": str(source.account_id) if source else str(self.master.id),
            "target_transaction_id": str(lot.transaction_id) if lot.transaction_id else None,
            "account_id": str(lot.account_id),
            "date": source.transacted_at.isoformat() if source else None,
            "kind": kind, "amount": str(money(native)),
            "currency": self.cards[lot.account_id].currency,
            "settlement_amount": str(money(settlement)), "settlement_currency": self.master.currency,
        })

    def consume(self, source, amount, account_id, kind, transaction_id=None, native_limit=None):
        """Consume oldest outstanding lots on one card, at each lot's fixed rate."""
        remaining = amount
        for lot in self.lots:
            if lot.account_id != account_id or not lot.settlement:
                continue
            if transaction_id is not None and lot.transaction_id != transaction_id:
                continue
            take = min(remaining, lot.settlement)
            if native_limit is not None:
                if lot.native <= 0:
                    continue
                take = min(take, lot.settlement * min(native_limit, lot.native) / lot.native)
            if take == lot.settlement:
                native = lot.native
            else:
                take = money(take)
                native = money(lot.native * take / lot.settlement)
            if not take:
                continue
            lot.settlement -= take
            lot.native -= native
            remaining -= take
            if native_limit is not None:
                native_limit -= native
            self.record(source, lot, take, native, kind)
            if remaining <= 0 or (native_limit is not None and native_limit <= 0):
                break
        self.lots = [lot for lot in self.lots if lot.settlement > 0]
        return amount - remaining

    def proportional(self, source, amount, kind):
        debts = {card_id: self.outstanding(card_id) for card_id in self.cards}
        debts = {key: value for key, value in debts.items() if value > 0}
        total = sum(debts.values(), ZERO)
        amount = min(amount, total)
        if not amount:
            return ZERO
        # Largest-remainder rounding makes allocations add up to the exact payment.
        shares = {key: (amount * debt / total).quantize(MONEY, rounding=ROUND_DOWN)
                  for key, debt in debts.items()}
        remainder = money(amount - sum(shares.values(), ZERO))
        ranked = sorted(debts, key=lambda key: (-(amount * debts[key] / total - shares[key]), str(key)))
        for key in ranked:
            if remainder <= 0:
                break
            shares[key] += MONEY
            remainder -= MONEY
        return sum((self.consume(source, share, key, kind) for key, share in shares.items()), ZERO)

    def receive(self, source, amount, kind, priority=None):
        if priority is not None:
            amount -= self.consume(source, amount, priority, kind)
        amount -= self.proportional(source, amount, kind)
        if amount > 0:
            self.credit += amount
            self.credits.append([source, amount])

    def charge(self, txn, native, settlement, account_id=None):
        account_id = account_id or txn.account_id
        lot = Lot(account_id, txn.id if txn else None, native, settlement)
        self.lots.append(lot)
        # Old overpayments are consumed once; later spending is never erased twice.
        for credit in self.credits:
            if not lot.settlement:
                break
            take = min(credit[1], lot.settlement)
            if not take:
                continue
            used = self.consume(credit[0], take, account_id, "credit", transaction_id=lot.transaction_id)
            credit[1] -= used
            self.credit -= used


def settlement_value(txn, card, master):
    if card.id == master.id:
        return money(txn.amount)
    if (txn.master_account_id == master.id and txn.master_settlement_currency == master.currency
            and txn.master_settlement_amount is not None):
        return money(txn.master_settlement_amount)
    if card.currency == master.currency and txn.master_settlement_amount is None:
        return money(txn.amount)
    raise HTTPException(409, "外币副卡历史流水缺少固定主卡结算，请先核对")


def _event_key(txn):
    stamp = txn.occurred_at or datetime.min
    if stamp.tzinfo:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    created = txn.created_at or datetime.min
    if created.tzinfo:
        created = created.astimezone(timezone.utc).replace(tzinfo=None)
    return txn.transacted_at, stamp, created, str(txn.id)


def replay_component(session, master, cutoff=None, use_cache=True):
    from services.card_replay import replay
    return replay(session, master, cutoff, use_cache)


def replay_group(session, master, cutoff=None, use_cache=True, subject_id=None):
    from dataclasses import replace
    groups, parents, _ = replay_component(session, master, cutoff, use_cache)
    subject_id = subject_id or master.id
    root = parents.get(subject_id, subject_id)
    result = groups[root]
    allocations = [row for group in groups.values() for row in group.allocations
                   if row['account_id'] in {str(key) for key in result.cards}]
    return replace(result, allocations=allocations)


def settlement_anchor(session, account):
    """Resolve eligibility once, without replaying any financial events."""
    from services.card_history import history_exists
    historical = history_exists(session, account.id)
    if not account_type_is(account.account_type, "credit_card") and not historical:
        return None
    master = session.get(Account, account.parent_account_id) if account.parent_account_id else account
    if not master or master.family_id != account.family_id:
        return None
    if master.id == account.id and not session.scalars(select(Account.id).where(
            Account.parent_account_id == master.id, Account.family_id == master.family_id)).first() and not historical:
        return None
    return master


def group_for_account(session, account, cutoff=None):
    master = settlement_anchor(session, account)
    if not master:
        return None
    # Scalar SELECT bypasses the identity map. Another request/worker can commit
    # a repayment while this session is alive; never retain that old allocation.
    version = session.scalar(select(CardSettlementState.updated_at).where(
        CardSettlementState.master_account_id == master.id))
    versions = session.info.setdefault("card_group_versions", {})
    if master.id not in versions or versions[master.id] != version:
        session.info["card_group_cache"] = {key: value for key, value in session.info.get("card_group_cache", {}).items()
                                            if key[0] != master.id}
        session.info.get("card_group_inputs", {}).pop(master.id, None)
        versions[master.id] = version
    key = (master.id, account.id, cutoff)
    cache = session.info.setdefault("card_group_cache", {})
    if key not in cache:
        result = replay_group(session, master, cutoff, subject_id=account.id)
        session.info.setdefault("card_group_cache", {})[key] = result
    return session.info["card_group_cache"][key]


def balance_adjustment(session, account, target, current, day):
    """A child's new debt first consumes pooled credit; it cannot own overpayment."""
    difference = target - current
    if not account.parent_account_id:
        return difference
    if target < 0:
        raise HTTPException(422, "副卡待还金额不能为负数，溢缴款请在主卡调整")
    group = group_for_account(session, account)
    if difference > 0 and group and group.credit > 0:
        from services.booking_money import fixed_conversion
        native_credit, *_ = fixed_conversion(session, group.credit, group.master.currency, account.currency, day)
        difference += native_credit
    return money(difference)


def adjustment_settlement(session, account, difference, day):
    """A manual debt reduction removes native principal at its booked lot rates.

    Applying today's rate would remove a different native amount when replaying
    the adjustment, so the user's requested balance could never be reached.
    """
    if difference >= 0 or not account.parent_account_id:
        return {}
    group = group_for_account(session, account)
    if not group:
        return {}
    remaining = money(-difference)
    settlement = ZERO
    for lot in group.lots:
        if lot.account_id != account.id or lot.native <= 0:
            continue
        take = min(remaining, lot.native)
        settlement += lot.settlement if take == lot.native else money(lot.settlement * take / lot.native)
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        raise HTTPException(422, "副卡待还金额不能为负数，溢缴款请在主卡调整")
    return dict(master_account_id=group.master.id, master_settlement_amount=money(settlement),
                master_settlement_currency=group.master.currency,
                master_exchange_rate=(settlement / -difference).quantize(RATE),
                master_exchange_rate_date=day, master_exchange_rate_source='fixed_unpaid_lots')


def _remember_balance_changes(session, rows):
    session.info.pop("card_group_cache", None)
    session.info.pop("card_group_inputs", None)
    session.info.pop("card_group_versions", None)
    touched = session.info.setdefault("card_settlement_touched", set())
    for row in rows:
        if isinstance(row, Account):
            touched.add(row.id)
            touched.update(inspect(row).attrs.parent_account_id.history.deleted)
            if row.parent_account_id:
                touched.add(row.parent_account_id)
            if row in session.deleted:
                session.execute(delete(CardSettlementState).where(CardSettlementState.master_account_id == row.id))
        elif isinstance(row, Transaction):
            touched.add(row.account_id)
            touched.update(inspect(row).attrs.account_id.history.deleted)
        elif isinstance(row, (RefundAllocation, Transfer)):
            names = ("refund_transaction_id", "original_transaction_id") if isinstance(row, RefundAllocation) else ("inflow_transaction_id", "outflow_transaction_id")
            for name in names:
                for txn_id in (getattr(row, name), *inspect(row).attrs[name].history.deleted):
                    txn = session.get(Transaction, txn_id) if txn_id else None
                    if txn:
                        touched.add(txn.account_id)
        elif isinstance(row, CardMembership):
            touched.update((row.account_id, row.master_account_id))
        elif isinstance(row, CardSettlementArchive):
            touched.add(row.account_id)


@event.listens_for(SASession, "before_flush", insert=True)
def remember_card_changes(session, flush_context, instances):
    rows = list(session.new) + list(session.dirty) + list(session.deleted)
    if any(isinstance(row, (Account, Transaction, RefundAllocation, Transfer,
                           CardMembership, CardSettlementArchive)) for row in rows):
        # Acquire before the first ledger/account UPDATE, even for explicit
        # flushes. PostgreSQL row locks must not precede this shared lock.
        from services.transaction_lock import lock_mutation
        lock_mutation(session)
    _remember_balance_changes(session, rows)


@event.listens_for(SASession, "do_orm_execute", retval=True)
def remember_bulk_balance_changes(state):
    """ORM bulk UPDATE/DELETE bypass flush hooks; capture both old/new owners.

    Derived Core snapshot updates deliberately do not enter this listener.
    Administrative raw SQL must be followed by the explicit balance rebuild.
    """
    mapper = state.bind_mapper
    model = mapper.class_ if mapper else None
    if not (state.is_update or state.is_delete) or model not in (
            Account, Transaction, Transfer, RefundAllocation, CardMembership, CardSettlementArchive
            ) or state.statement.table is model.__table__:
        return state.invoke_statement()
    from services.transaction_lock import lock_mutation
    session = state.session
    lock_mutation(session)
    session.flush()
    query = select(model)
    if state.statement.whereclause is not None:
        query = query.where(state.statement.whereclause)
    rows = session.scalars(query.execution_options(populate_existing=True)).all()
    ids = {row.id for row in rows}
    _remember_balance_changes(session, rows)
    result = state.invoke_statement()
    if state.is_update and ids:
        rows = session.scalars(select(model).where(model.id.in_(ids))
                               .execution_options(populate_existing=True)).all()
        _remember_balance_changes(session, rows)
    return result


@event.listens_for(SASession, "before_commit")
def persist_allocations(session):
    # A SAVEPOINT release is not the outer ledger commit. Its snapshot changes
    # could disappear on a later savepoint rollback while ledger rows survive.
    if session.in_nested_transaction():
        return
    changed = session.info.get("card_settlement_touched") or any(
        isinstance(row, (Account, Transaction, RefundAllocation, Transfer, CardMembership, CardSettlementArchive))
        for row in list(session.new) + list(session.dirty) + list(session.deleted))
    if not changed:
        return
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    session.flush()
    touched = session.info.pop("card_settlement_touched", set())
    if touched:
        # All writes are flushed. Reload metadata left in long-lived identity
        # maps by another worker, including the persisted opening-history flag.
        session.scalars(select(Account).where(Account.id.in_(touched))
                        .execution_options(populate_existing=True)).all()
    from services.card_history import load_component
    from services.card_history import history_exists
    masters = {}
    for account_id in touched:
        card = session.get(Account, account_id) if account_id else None
        if card and (account_type_is(card.account_type, 'credit_card') or history_exists(session, card.id)):
            component = load_component(session, card)[0]
            for candidate_id in component:
                candidate = session.get(Account, candidate_id)
                if candidate and not candidate.parent_account_id:
                    masters[candidate.id] = candidate
        elif not card:
            for membership in session.scalars(select(CardMembership).where(
                    (CardMembership.account_id == account_id) | (CardMembership.master_account_id == account_id))).all():
                for candidate_id in (membership.account_id, membership.master_account_id):
                    candidate = session.get(Account, candidate_id)
                    if candidate and not candidate.parent_account_id:
                        masters[candidate.id] = candidate
    balance_groups = {}
    for master in masters.values():
        group = replay_group(session, master)
        state = session.get(CardSettlementState, master.id) or CardSettlementState(master_account_id=master.id, currency=master.currency)
        state.currency = master.currency
        state.allocations = group.allocations
        state.balances = {str(key): {"amount": str(group.native_balance(key)), "currency": card.currency,
                                   "settlement_amount": str(money(group.outstanding(key) - (group.credit if key == master.id else ZERO)))}
                          for key, card in group.cards.items()}
        state.updated_at = datetime.now(timezone.utc)
        session.add(state)
        balance_groups.update({key: group for key in group.cards})

    from services.account_balances import persist_latest_balances
    persist_latest_balances(session, touched | set(balance_groups), balance_groups)


@event.listens_for(SASession, "after_commit")
@event.listens_for(SASession, "after_rollback")
def clear_cache(session):
    session.info.pop("card_group_cache", None)
    session.info.pop("card_group_inputs", None)
    session.info.pop("card_group_versions", None)
    if not session.in_nested_transaction():
        session.info.pop("card_settlement_touched", None)

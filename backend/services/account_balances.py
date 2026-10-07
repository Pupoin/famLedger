"""Current balances are materialized with ledger writes, never independently.

Historical projections still replay the dated ledger. These snapshots contain
native/fixed settlement money; they never cache a user's display currency.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm.attributes import set_committed_value
from sqlmodel import select

from models import (Account, Transaction, Transfer, RefundAllocation,
                    CardMembership, CardSettlementArchive)
from services.account_types import financial_classification
from services.transaction_direction import transaction_direction

FINANCIAL_MODELS = (Account, Transaction, Transfer, RefundAllocation,
                    CardMembership, CardSettlementArchive)
SNAPSHOT_FIELDS = ("latest_balance", "latest_own_balance", "latest_settlement_balance",
                   "latest_settlement_currency", "latest_transaction_count", "ledger_initialized", "balance_updated_at")
ACCOUNT_FIELDS = ("parent_account_id", "account_type", "classification", "family_id", "currency", "balance")


def pending_financial_changes(session):
    return bool(session.info.get("card_settlement_touched")) or any(
        isinstance(row, FINANCIAL_MODELS)
        for row in list(session.new) + list(session.dirty) + list(session.deleted))


def current_snapshot(session, account):
    """Refresh only the small snapshot, including in long-lived worker sessions."""
    if account is None or pending_financial_changes(session):
        return None
    row = session.execute(select(*(getattr(Account, name) for name in (*SNAPSHOT_FIELDS, *ACCOUNT_FIELDS)),
                                 Account.balance_version).where(Account.id == account.id)).first()
    if row is None or row.latest_balance is None or row.balance_updated_at is None:
        return None
    for name in (*SNAPSHOT_FIELDS, *ACCOUNT_FIELDS, "balance_version"):
        set_committed_value(account, name, getattr(row, name))
    return row


def current_balances(session, accounts):
    """One small SELECT for an authorized list, without reading transaction rows."""
    accounts = list(accounts)
    by_id = {account.id: account for account in accounts}
    values = {}
    if by_id and not pending_financial_changes(session):
        rows = session.execute(select(Account.id, *(getattr(Account, name) for name in (*SNAPSHOT_FIELDS, *ACCOUNT_FIELDS)),
                                      Account.balance_version).where(Account.id.in_(by_id))).all()
        for row in rows:
            if row.latest_balance is not None and row.balance_updated_at is not None:
                values[row.id] = row.latest_balance
                for name in (*SNAPSHOT_FIELDS, *ACCOUNT_FIELDS, "balance_version"):
                    set_committed_value(by_id[row.id], name, getattr(row, name))
    from routes.v1_accounts import get_account_realtime_balance
    for account in accounts:
        if account.id not in values:
            values[account.id] = get_account_realtime_balance(session, account.id)
    return values


def own_settlement_balance(session, account, native_balance):
    """A card share keeps its bank-fixed settlement rate when grouped/reported."""
    if (not pending_financial_changes(session) and account.balance_updated_at is not None
            and account.latest_settlement_balance is not None and account.latest_settlement_currency):
        return account.latest_settlement_balance, account.latest_settlement_currency
    from services.card_settlement import group_for_account
    group = group_for_account(session, account)
    if group:
        value = group.outstanding(account.id) - (group.credit if group.master.id == account.id else Decimal(0))
        return (-value if financial_classification(account) == 'asset' else value), group.master.currency
    return native_balance, account.currency


def raw_balance(session, account, activities):
    """The existing ledger convention, including opening and adjustment rows."""
    if not activities:
        return Decimal(0) if account.ledger_initialized else Decimal(account.balance or 0)
    liability = financial_classification(account) == "liability"
    balance = Decimal(0)
    for txn in activities:
        amount = Decimal(txn.amount or 0)
        if txn.transaction_type in ("income", "refund"):
            balance += -amount if liability else amount
        elif txn.transaction_type == "expense":
            balance += amount if liability else -amount
        elif txn.transaction_type == "transfer":
            incoming = transaction_direction(txn, session, account) == "inflow"
            balance += amount if incoming != liability else -amount
        elif txn.transaction_type == "adjustment":
            decrease = ((txn.extra or {}).get("direction") == "decrease" if txn.extra
                        else "(-" in (txn.narration or ""))
            balance += -amount if decrease else amount
    return balance


def calculate_snapshots(session, accounts, groups=None):
    """Batch-load each affected account's ledger once; reuse card-group replay."""
    accounts = list(accounts)
    by_account = {account.id: [] for account in accounts}
    if by_account:
        for txn in session.scalars(select(Transaction).where(Transaction.account_id.in_(by_account))).all():
            by_account[txn.account_id].append(txn)
    groups = groups or {}
    values = {}
    from services.card_settlement import group_for_account
    for account in accounts:
        group = groups.get(account.id)
        if group is None:
            group = group_for_account(session, account)
        native = raw_balance(session, account, by_account[account.id])
        own, settlement, settlement_currency = native, native, account.currency
        if group:
            own = group.native_balance(account.id)
            native = group.balance if group.master.id == account.id else own
            settlement = group.outstanding(account.id) - (group.credit if group.master.id == account.id else Decimal(0))
            settlement_currency = group.master.currency
            if financial_classification(account) == "asset":
                native, own, settlement = -native, -own, -settlement
        values[account.id] = dict(latest_balance=native, latest_own_balance=own,
            latest_settlement_balance=settlement, latest_settlement_currency=settlement_currency,
            latest_transaction_count=len(by_account[account.id]),
            ledger_initialized=account.ledger_initialized or bool(by_account[account.id]))
    return values


def persist_latest_balances(session, account_ids, groups=None):
    """Called after ledger flush while holding the shared financial write lock."""
    accounts = session.scalars(select(Account).where(Account.id.in_(set(account_ids)))
                              .execution_options(populate_existing=True)).all() if account_ids else []
    values = calculate_snapshots(session, accounts, groups)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for account in accounts:
        snapshot = {**values[account.id], "balance_updated_at": now}
        # Core UPDATE avoids re-triggering membership/ledger hooks for derived
        # fields. Increment the DB version, not a potentially stale ORM value.
        session.execute(Account.__table__.update().where(Account.id == account.id)
                        .values(**snapshot, balance_version=Account.balance_version + 1))
        for name, value in snapshot.items():
            set_committed_value(account, name, value)
        session.expire(account, ["balance_version"])
    return len(accounts)


def rebuild_latest_balances(session, missing_only=False):
    """Startup backfill / explicit repair; does not change any ledger activity."""
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    session.flush()
    query = select(Account.id)
    if missing_only:
        query = query.where((Account.latest_balance.is_(None)) | (Account.balance_updated_at.is_(None)))
    ids = set(session.scalars(query).all())
    count = persist_latest_balances(session, ids)
    session.commit()
    return count


def verify_latest_balances(session):
    """Read-only reconciliation against the ledger, safe for SQLite and PG."""
    # Prevent comparing a pre-commit snapshot against a post-commit ledger.
    # This only locks the diagnostic transaction; it changes no financial data.
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    accounts = session.scalars(select(Account).execution_options(populate_existing=True)).all()
    expected = calculate_snapshots(session, accounts)
    return [{"account_id": str(account.id), "fields": [name for name, value in expected[account.id].items()
                if getattr(account, name) != value]}
            for account in accounts if account.balance_updated_at is None or any(
                getattr(account, name) != value for name, value in expected[account.id].items())]

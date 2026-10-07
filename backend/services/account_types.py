"""Account names never determine financial classification."""
import json
from decimal import Decimal
from pathlib import Path

ACCOUNT_TYPES = json.loads((Path(__file__).resolve().parent.parent / 'account_types.json').read_text(encoding='utf-8'))
ALIASES = {alias.casefold(): key for key, definition in ACCOUNT_TYPES.items() for alias in definition['aliases']}


def normalize_account_type(value):
    key = ALIASES.get(str(value or '').strip().casefold())
    if key is None:
        raise ValueError('不支持的账户类别，请选择有效的账户类别')
    return key


def account_classification(value):
    return ACCOUNT_TYPES[normalize_account_type(value)]['classification']


def account_type_is(value, expected):
    return ALIASES.get(str(value or '').strip().casefold()) == expected


def financial_classification(account):
    key = ALIASES.get(str(getattr(account, 'account_type', '') or '').strip().casefold())
    return ACCOUNT_TYPES[key]['classification'] if key else None


def change_account_type(session, account, value):
    """Preserve the displayed balance on an explicit reclassification.

    Reinterpret only the system-generated opening. Real cash flows retain
    their types; any remaining difference is an excluded balance adjustment.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from sqlmodel import select
    from models import Transaction
    from routes.v1_accounts import _calc_raw_account_balance, _ensure_opening_balance_transaction

    new_type = normalize_account_type(value)
    if account.parent_account_id and new_type != 'credit_card':
        # Settle the old credit-card share before reinterpreting its ledger
        # under the new classification, including callers doing bulk edits.
        account.parent_account_id = None
        session.add(account)
        session.flush()
    old_class = account.classification
    new_class = account_classification(new_type)
    if old_class == new_class:
        account.account_type = new_type
        account.classification = new_class
        return
    from services.card_history import history_exists
    historical = history_exists(session, account.id)
    from routes.v1_accounts import get_account_realtime_balance
    if not historical:
        _ensure_opening_balance_transaction(session, account)
    with session.no_autoflush:
        before = get_account_realtime_balance(session, account.id, old_class, account.balance) if historical else _calc_raw_account_balance(session, account.id, old_class, account.balance)
        openings = session.exec(select(Transaction).where(Transaction.account_id == account.id)).all()
        for row in openings:
            if historical:
                continue
            if not row.excluded_from_stats or (row.extra or {}).get('source') != 'account_opening':
                continue
            if row.transaction_type not in ('income', 'expense'):
                continue
            positive = (row.transaction_type == 'expense') == (old_class == 'liability')
            row.transaction_type = 'expense' if positive == (new_class == 'liability') else 'income'
            row.narration = f"{account.name} ({'期初欠款' if new_class == 'liability' else '期初余额'})"
            session.add(row)
        account.account_type = new_type
        account.classification = new_class
        session.add(account)
    session.flush()
    after = get_account_realtime_balance(session, account.id, new_class, account.balance) if historical else _calc_raw_account_balance(session, account.id, new_class, account.balance)
    diff = before - after
    if diff:
        now = datetime.now(timezone.utc)
        session.add(Transaction(
            account_id=account.id, transacted_at=now.astimezone(ZoneInfo('Asia/Shanghai')).date(), occurred_at=now.replace(tzinfo=None),
            amount=abs(diff), currency=account.currency, transaction_type='adjustment',
            narration='账户类别变更余额调整', category_source='manual', status='cleared',
            reconciled=True, excluded_from_stats=True,
            extra={'source': 'account_type_change', 'diff': str(diff),
                   'direction': 'increase' if diff > Decimal(0) else 'decrease'},
            notes=f'账户类别变更：保持余额 {before}；原分类 {old_class}，新分类 {new_class}',
        ))
        session.flush()


def repair_account_types(session):
    """Repair supported stored type aliases and derived classifications, never names."""
    from sqlmodel import select
    from models import Account, Transaction
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    changed = 0
    for account in session.exec(select(Account).with_for_update()).all():
        try:
            canonical = normalize_account_type(account.account_type)
        except ValueError:
            continue  # An unknown historical type needs an explicit user selection.
        if account.account_type != canonical or account.classification != account_classification(canonical):
            # Repair metadata according to the actual type, rather than treating
            # an incorrect cached classification as a user-requested type change.
            account.account_type = canonical
            account.classification = account_classification(canonical)
            for row in session.exec(select(Transaction).where(Transaction.account_id == account.id)).all():
                if (row.extra or {}).get('source') != 'account_opening' or not row.excluded_from_stats:
                    continue
                # Only an intact system opening has a recorded signed baseline.
                if account.balance and row.amount == abs(account.balance) and row.transaction_type in ('income', 'expense'):
                    row.transaction_type = 'expense' if (account.balance > 0) == (account.classification == 'liability') else 'income'
                    row.narration = f"{account.name} ({'期初欠款' if account.classification == 'liability' else '期初余额'})"
                    session.add(row)
            session.add(account)
            changed += 1
    session.commit()
    return changed

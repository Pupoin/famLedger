"""Authorized account balances and ledger-based historical net worth."""
from decimal import Decimal

from sqlmodel import select, or_

from models import Account, AccountShare, Transaction, Transfer
from services.transaction_direction import transaction_direction
from services.account_types import financial_classification


def visible_balance_accounts(session, user, owner_filter=None):
    """All explicitly authorized accounts, including archived and report opt-outs.

    Balance sheets describe what remains in accounts; spending participation
    and sidebar hiding are separate preferences, not balance filters.
    """
    if not user:
        return []
    if isinstance(user, str) and user.startswith('service:'):
        from services.principals import service_family
        query = select(Account).where(Account.family_id == service_family(session).id)
    else:
        if not getattr(user, 'id', None):
            return []
        query = select(Account).where(Account.owner_id == user.id)
        if user.family_id:
            shared = select(AccountShare.account_id).where(AccountShare.user_id == user.id)
            query = select(Account).where(Account.family_id == user.family_id,
                                           or_(Account.owner_id == user.id, Account.id.in_(shared)))
    if owner_filter is not None:
        query = query.where(Account.owner_id == owner_filter)
    return list(session.exec(query).all())


def ledger_net_worth_history(session, accounts, report_money, periods):
    """Value recorded account activities at each cutoff, including openings.

    PersonalDebt has no dated repayment history, so it cannot safely be
    reconstructed here. The API explicitly labels this as account history.
    """
    if not periods:
        return []
    from services.card_settlement import settlement_anchor
    from services.card_replay import replay_at_dates
    accounts = list(accounts)
    ids = {account.id for account in accounts}
    dates = sorted({day for _, day in periods})
    card_history, projected_ids = {}, set()
    for account in accounts:
        if account.id in projected_ids:
            continue
        anchor = settlement_anchor(session, account)
        if anchor:
            projection = replay_at_dates(session, anchor, dates)
            projected_ids.update(projection[dates[-1]])
            for day, values in projection.items():
                card_history.setdefault(day, {}).update(values)

    ordinary = {account.id: account for account in accounts if account.id not in projected_ids}
    # Ordinary accounts need only signed native amounts, not every ORM field.
    rows = session.exec(select(Transaction.id, Transaction.account_id, Transaction.transacted_at,
        Transaction.amount, Transaction.transaction_type, Transaction.transfer_id,
        Transaction.extra, Transaction.narration, Transaction.notes).where(
        Transaction.account_id.in_(ordinary), Transaction.transacted_at <= dates[-1])
        .order_by(Transaction.transacted_at)).all() if ordinary else []
    paired_ids = list({row.transfer_id for row in rows if row.transfer_id})
    pairs = {}
    for offset in range(0, len(paired_ids), 900):
        pairs.update((row.id, row) for row in session.exec(select(Transfer).where(
            Transfer.id.in_(paired_ids[offset:offset + 900]))).all())
    with_history = {row.account_id for row in rows}
    balances = {key: Decimal(0) for key in ordinary}
    projected, index = {}, 0

    def apply(row):
        amount = row.amount
        kind = row.transaction_type
        account = ordinary[row.account_id]
        if kind in ('income', 'refund'):
            balances[row.account_id] += amount
        elif kind == 'expense':
            balances[row.account_id] -= amount
        elif kind == 'transfer':
            pair = pairs.get(row.transfer_id)
            if pair and row.id in (pair.inflow_transaction_id, pair.outflow_transaction_id):
                incoming = row.id == pair.inflow_transaction_id
            else:
                incoming = transaction_direction(row, None, account) == 'inflow'
            balances[row.account_id] += amount if incoming else -amount
        elif kind == 'adjustment':
            decrease = (row.extra or {}).get('direction') == 'decrease'
            positive = decrease if financial_classification(account) == 'liability' else not decrease
            balances[row.account_id] += amount if positive else -amount

    for cutoff in dates:
        while index < len(rows) and rows[index].transacted_at <= cutoff:
            apply(rows[index]); index += 1
        total = Decimal(0)
        for account in accounts:
            card = card_history.get(cutoff, {}).get(account.id)
            if card:
                root, balance, currency = card
                if root == account.id or root not in ids:
                    total -= report_money.amount(balance, currency, cutoff)
                continue
            balance = balances[account.id]
            if account.id not in with_history and not account.ledger_initialized and account.created_at.date() <= cutoff:
                balance = account.balance * (-1 if financial_classification(account) == 'liability' else 1)
            total += report_money.amount(balance, account.currency, cutoff)
        projected[cutoff] = round(float(total), 2)

    return [{'date': label, 'as_of': cutoff.isoformat(), 'value': projected[cutoff]} for label, cutoff in periods]

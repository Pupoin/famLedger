"""Authorized account balances and ledger-based historical net worth."""
from decimal import Decimal

from fastapi import HTTPException
from sqlmodel import select, or_

from models import Account, AccountShare, Transaction
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
    ids = {account.id for account in accounts}
    rows = session.exec(select(Transaction).where(Transaction.account_id.in_(ids),
                        Transaction.transacted_at <= max(day for _, day in periods))).all() if ids else []
    by_account = {account.id: [] for account in accounts}
    for row in rows:
        by_account[row.account_id].append(row)
    by_id = {account.id: account for account in accounts}
    points = []
    for label, cutoff in periods:
        total = Decimal(0)
        for account in accounts:
            parent = by_id.get(account.parent_account_id)
            balance = Decimal(0)
            currency = parent.currency if parent else account.currency
            history = by_account[account.id]
            for row in history:
                if row.transacted_at > cutoff:
                    continue
                amount = row.amount
                if parent:
                    if row.master_account_id == parent.id and row.master_settlement_amount is not None:
                        amount = row.master_settlement_amount
                    elif account.currency != parent.currency:
                        raise HTTPException(409, '历史外币副卡缺少固定主卡结算，请先核对')
                if row.transaction_type in ('income', 'refund'):
                    balance += amount
                elif row.transaction_type == 'expense':
                    balance -= amount
                elif row.transaction_type == 'transfer':
                    balance += amount if transaction_direction(row, session, account) == 'inflow' else -amount
                elif row.transaction_type == 'adjustment':
                    decrease = (row.extra or {}).get('direction') == 'decrease'
                    positive = decrease if financial_classification(account) == 'liability' else not decrease
                    balance += amount if positive else -amount
            if not history and account.created_at.date() <= cutoff:
                balance = account.balance * (-1 if financial_classification(account) == 'liability' else 1)
            total += report_money.amount(balance, currency, cutoff)
        points.append({'date': label, 'as_of': cutoff.isoformat(), 'value': round(float(total), 2)})
    return points

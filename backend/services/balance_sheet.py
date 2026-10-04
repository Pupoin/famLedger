"""Shared visible personal debts and ledger-based historical net worth."""
from decimal import Decimal

from fastapi import HTTPException
from sqlmodel import select, or_

from models import Account, PersonalDebt, Transaction
from services.transaction_direction import transaction_direction


def debt_accounts(session, user, owner_filter=None):
    if not user or not user.family_id:
        return []
    query = select(PersonalDebt).where(PersonalDebt.family_id == user.family_id,
                                      PersonalDebt.status == 'active', PersonalDebt.remaining_amount > 0)
    if user.role not in ('owner', 'admin'):
        query = query.where(or_(PersonalDebt.owner_id == user.id, PersonalDebt.owner_id.is_(None)))
    if owner_filter is not None:
        query = query.where(PersonalDebt.owner_id == owner_filter)
    result = []
    for debt in session.exec(query).all():
        borrow = debt.debt_type == 'borrow'
        # Display-only account objects. They are never persisted as accounts.
        result.append(Account(id=debt.id, family_id=debt.family_id, owner_id=debt.owner_id,
                              name=debt.notes or f"{'应付借款' if borrow else '应收借款'}：{debt.counterparty}",
                              institution_name=debt.counterparty, currency=debt.currency,
                              account_type='loan' if borrow else 'receivable',
                              classification='liability' if borrow else 'asset', balance=debt.remaining_amount,
                              created_at=debt.created_at))
    return result


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
                    positive = decrease if account.classification == 'liability' else not decrease
                    balance += amount if positive else -amount
            if not history and account.created_at.date() <= cutoff:
                balance = account.balance * (-1 if account.classification == 'liability' else 1)
            total += report_money.amount(balance, currency, cutoff)
        points.append({'date': label, 'as_of': cutoff.isoformat(), 'value': round(float(total), 2)})
    return points

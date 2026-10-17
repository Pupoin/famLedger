"""Recorded investment returns alongside cash flows, without recategorizing them."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlmodel import select

from models import Transaction
from services.account_types import account_type_is
from services.investments import LOCAL, SOURCE, RETURN_SOURCE, is_investment_return, signed
from services.stats_engine import is_genuine_income, is_genuine_expense, is_genuine_refund


def investment_filter(category_name, transaction_type=None):
    """Recognize the captured Sankey links that incorrectly use a category.

    Investment P&L is a transaction attribute. Preserve dates, owners and
    account authorization when correcting only this incompatible filter pair.
    """
    if not isinstance(category_name,str):
        return None
    activity={'投资盈利':'gain','Investment gains':'gain','投资亏损':'loss','Investment losses':'loss'}.get(category_name.strip())
    if activity is None:
        return None
    types={item.strip() for item in transaction_type.split(',') if item.strip()} if isinstance(transaction_type,str) else set()
    allowed={'income'} if activity=='gain' else {'expense','refund'}
    return activity if types <= allowed else None


def recorded_return(row):
    return (is_investment_return(row) and not (row.extra or {}).get('valuation_baseline')
            and row.transacted_at <= datetime.now(LOCAL).date())


def eligible(row, accounts, report_ids, investment_ids):
    return ((row.account_id in investment_ids and recorded_return(row))
            or (row.account_id in report_ids and (is_genuine_income(row,accounts)
                or is_genuine_expense(row,accounts) or is_genuine_refund(row))))


def investment_months(session, accounts, start, end, converter):
    ids={account.id for account in accounts if account_type_is(account.account_type,'investment')}
    rows=session.exec(select(Transaction).where(Transaction.account_id.in_(ids),
        Transaction.transacted_at >= start, Transaction.transacted_at <= min(end,datetime.now(LOCAL).date()),
        Transaction.transaction_type == 'adjustment',
        Transaction.extra['source'].as_string().in_([SOURCE,RETURN_SOURCE]))).all() if ids else []
    converter.prepare(rows)
    buckets=defaultdict(lambda: {'gain':Decimal(0),'loss':Decimal(0)})
    for row in rows:
        if recorded_return(row):
            amount=converter.amount(signed(row,{}),row.currency,row.transacted_at)
            buckets[row.transacted_at.strftime('%Y-%m')]['gain' if amount>=0 else 'loss']+=abs(amount)
    return buckets


def contribution(session, row, accounts, report_ids, investment_ids, converter):
    """Return a positive inflow/outflow contribution; refunds reduce outflows."""
    if row.account_id in investment_ids and recorded_return(row):
        amount=converter.amount(signed(row,{}),row.currency,row.transacted_at)
        return ('income' if amount>=0 else 'expense',abs(amount),'investment')
    if row.account_id not in report_ids:
        return None
    if is_genuine_income(row,accounts):
        return 'income',converter.ledger_amount(row),'cash'
    if is_genuine_expense(row,accounts):
        return 'expense',converter.ledger_amount(row),'cash'
    if is_genuine_refund(row):
        from services.refund_money import spending_refund
        return 'expense',-spending_refund(session,row,report_ids,converter),'cash'
    return None

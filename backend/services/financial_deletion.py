"""Delete account financial records without leaving dangling relations.

Callers authorize the accounts first; this service never commits.
"""
from sqlmodel import select
from models import (Account, AccountShare, Loan, Transaction, TransactionSplit,
                    Transfer, RefundAllocation, RejectedTransfer, Valuation, PendingFxTransaction)


def delete_account_data(session, account_ids):
    account_ids = set(account_ids)
    if not account_ids:
        return []
    from services.schedules import delete_plans_for_accounts
    delete_plans_for_accounts(session, account_ids)
    for pending in session.exec(select(PendingFxTransaction).where(PendingFxTransaction.account_id.in_(account_ids))).all():
        session.delete(pending)
    session.flush()
    transactions = session.exec(select(Transaction).where(Transaction.account_id.in_(account_ids))).all()
    ids = {txn.id for txn in transactions}
    for model, fields in (
        (TransactionSplit, ['transaction_id']),
        (RefundAllocation, ['refund_transaction_id', 'original_transaction_id']),
        (RejectedTransfer, ['outflow_transaction_id', 'inflow_transaction_id']),
    ):
        if not ids:
            continue
        condition = getattr(model, fields[0]).in_(ids)
        for field in fields[1:]:
            condition |= getattr(model, field).in_(ids)
        for record in session.exec(select(model).where(condition)).all():
            session.delete(record)
    if ids:
        transfers = session.exec(select(Transfer).where(
            Transfer.outflow_transaction_id.in_(ids) | Transfer.inflow_transaction_id.in_(ids))).all()
        for transfer in transfers:
            for txn_id, direction in ((transfer.outflow_transaction_id, 'outflow'),
                                      (transfer.inflow_transaction_id, 'inflow')):
                peer = session.get(Transaction, txn_id)
                if peer and peer.id not in ids:
                    # Keep its original financial meaning while removing the relation.
                    peer.transfer_id = None
                    peer.extra = {**(peer.extra or {}), 'direction': direction}
                    session.add(peer)
            session.delete(transfer)
        for txn in session.exec(select(Transaction).where(Transaction.refund_of_transaction_id.in_(ids))).all():
            txn.refund_of_transaction_id = None
            session.add(txn)
        session.flush()
        for txn in transactions:
            txn.refund_of_transaction_id = None
            session.add(txn)
        session.flush()
        for txn in transactions:
            session.delete(txn)
        session.flush()
    for model in (AccountShare, Loan, Valuation):
        for record in session.exec(select(model).where(model.account_id.in_(account_ids))).all():
            session.delete(record)
    for child in session.exec(select(Account).where(Account.parent_account_id.in_(account_ids))).all():
        child.parent_account_id = None
        session.add(child)
    session.flush()
    for account in session.exec(select(Account).where(Account.id.in_(account_ids))).all():
        session.delete(account)
    session.flush()
    return transactions

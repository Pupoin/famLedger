"""Explicit, atomic deletion of one transaction or a validated transfer pair."""
from fastapi import HTTPException
from sqlmodel import select

from models import Account, RefundAllocation, RejectedTransfer, Transaction, TransactionSplit, Transfer
from services.schedules import guard_transaction
from services.transaction_lock import lock_mutation

PAIR_CHANGED = "转账配对已变化，请刷新详情后重新确认删除。"
PAIR_INVALID = "转账关联不完整，请先修复配对后再删除。"


def transfer_pair(session, txn):
    pairs = session.exec(select(Transfer).where(
        (Transfer.outflow_transaction_id == txn.id) | (Transfer.inflow_transaction_id == txn.id)
    )).all()
    if not pairs and not txn.transfer_id:
        return None, None
    if len(pairs) != 1 or pairs[0].id != txn.transfer_id:
        raise HTTPException(409, PAIR_INVALID)
    pair = pairs[0]
    other_id = pair.inflow_transaction_id if pair.outflow_transaction_id == txn.id else pair.outflow_transaction_id
    other = session.get(Transaction, other_id)
    account = session.get(Account, txn.account_id)
    other_account = session.get(Account, other.account_id) if other else None
    if (other_id == txn.id or not other or other.transfer_id != pair.id
            or txn.amount <= 0 or other.amount <= 0
            or txn.transaction_type != 'transfer' or other.transaction_type != 'transfer'
            or not account or not other_account
            or account.family_id != pair.family_id or other_account.family_id != pair.family_id):
        raise HTTPException(409, PAIR_INVALID)
    other_pairs = session.exec(select(Transfer).where(
        (Transfer.outflow_transaction_id == other.id) | (Transfer.inflow_transaction_id == other.id)
    )).all()
    if len(other_pairs) != 1 or other_pairs[0].id != pair.id:
        raise HTTPException(409, PAIR_INVALID)
    return pair, other


def deletion_info(session, actor, txn, authorize):
    """Capabilities for the dialog; the delete request checks them again."""
    info = {"can_edit": False, "can_delete": False, "can_delete_pair": False, "transfer_id": None,
            "reason": None, "pair_reason": None}
    try:
        pair, other = transfer_pair(session, txn)
        info['transfer_id'] = str(pair.id) if pair else None
        authorize(session, actor, txn.account_id, "删除交易")
        guard_transaction(txn)
        info['can_edit'] = True
        if other:
            # Unlinking a protected scheduled peer would break its occurrence.
            guard_transaction(other)
        info['can_delete'] = True
        if other:
            try:
                authorize(session, actor, other.account_id, "删除配对交易")
                info['can_delete_pair'] = True
            except HTTPException:
                info['pair_reason'] = "同时删除需要两侧账户的写入权限。"
    except HTTPException as error:
        info['reason'] = error.detail
    originals = session.exec(select(RefundAllocation).where(
        RefundAllocation.original_transaction_id == txn.id)).all()
    refund_ids = {row.refund_transaction_id for row in originals}
    refund_ids.update(session.exec(select(Transaction.id).where(
        Transaction.refund_of_transaction_id == txn.id)).all())
    info['linked_refund_count'] = len(refund_ids)
    info['has_refund_links'] = bool(txn.refund_of_transaction_id or session.exec(
        select(RefundAllocation.id).where(RefundAllocation.refund_transaction_id == txn.id)).first())
    return info


def delete_transactions(session, actor, txn_id, scope, expected_transfer_id, authorize):
    lock_mutation(session)
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "交易未找到")
    authorize(session, actor, txn.account_id, "删除交易")
    guard_transaction(txn)
    pair, other = transfer_pair(session, txn)
    if pair:
        if scope is None:
            raise HTTPException(409, "该交易已配对，请选择只删除这笔或同时删除两笔。")
        if expected_transfer_id != pair.id:
            raise HTTPException(409, PAIR_CHANGED)
        guard_transaction(other)
    elif scope == 'pair' or expected_transfer_id is not None:
        raise HTTPException(409, PAIR_CHANGED)

    to_delete = [txn]
    if scope == 'pair':
        authorize(session, actor, other.account_id, "删除配对交易")
        to_delete.append(other)
    ids = {row.id for row in to_delete}

    # Validate all permissions before touching either side. Remove referencing
    # rows first so SQLite and PostgreSQL both enforce foreign keys normally.
    for model, fields in (
        (TransactionSplit, ['transaction_id']),
        (RefundAllocation, ['refund_transaction_id', 'original_transaction_id']),
        (RejectedTransfer, ['outflow_transaction_id', 'inflow_transaction_id']),
    ):
        condition = getattr(model, fields[0]).in_(ids)
        for field in fields[1:]:
            condition |= getattr(model, field).in_(ids)
        for record in session.exec(select(model).where(condition)).all():
            session.delete(record)
    if pair:
        if other.id not in ids:
            # This derived-link cleanup never changes the peer's monetary data
            # or promotes a transfer into reportable income/expense.
            direction = 'outflow' if other.id == pair.outflow_transaction_id else 'inflow'
            other.transfer_id = None
            other.extra = {**(other.extra or {}), 'direction': direction}
            session.add(other)
        session.delete(pair)
    for refund in session.exec(select(Transaction).where(
        Transaction.refund_of_transaction_id.in_(ids))).all():
        refund.refund_of_transaction_id = None
        session.add(refund)
    for row in to_delete:
        row.refund_of_transaction_id = None
        session.add(row)
    session.flush()
    for row in to_delete:
        session.delete(row)
    session.commit()
    return {"status": "ok", "message": "交易已成功删除", "deleted_id": str(txn_id),
            "deleted_ids": [str(row.id) for row in to_delete], "scope": scope or 'single'}

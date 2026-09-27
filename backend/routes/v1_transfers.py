"""Transfers Arbitration and Blacklist Management REST API."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select, desc

from database import get_session
from models import Family, RejectedTransfer, Transaction, Transfer
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/transfers", tags=["Transfers"])


class ManualPairPayload(BaseModel):
    outflow_transaction_id: uuid.UUID
    inflow_transaction_id: uuid.UUID


@router.get("")
@router.get("/")
def list_transfers(
    status: Optional[str] = Query(None, description="confirmed | pending"),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取所有已配对或待确认的转账记录列表。"""
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    stmt = select(Transfer).where(Transfer.family_id == family.id)
    if status:
        stmt = stmt.where(Transfer.status == status)

    transfers = session.exec(stmt.order_by(desc(Transfer.created_at))).all()

    items = []
    for t in transfers:
        out_txn = session.get(Transaction, t.outflow_transaction_id)
        in_txn = session.get(Transaction, t.inflow_transaction_id)

        items.append({
            "id": str(t.id),
            "amount": str(Decimal(str(t.amount)).quantize(Decimal("0.01"))),
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "outflow": {
                "id": str(out_txn.id) if out_txn else None,
                "account_id": str(out_txn.account_id) if out_txn else None,
                "amount": str(out_txn.amount) if out_txn else None,
                "name": out_txn.name if out_txn else None,
                "transacted_at": out_txn.transacted_at.isoformat() if out_txn else None,
            } if out_txn else None,
            "inflow": {
                "id": str(in_txn.id) if in_txn else None,
                "account_id": str(in_txn.account_id) if in_txn else None,
                "amount": str(in_txn.amount) if in_txn else None,
                "name": in_txn.name if in_txn else None,
                "transacted_at": in_txn.transacted_at.isoformat() if in_txn else None,
            } if in_txn else None,
        })

    return {"transfers": items, "count": len(items)}


@router.post("/{transfer_id}/reject")
def reject_transfer(
    transfer_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    人工仲裁驳回转账：
    解除流水的转账绑定，恢复为独立收支，并将该对交易写入 RejectedTransfer 黑名单，
    彻底杜绝后台定时任务再次对它们进行静默自动撮合！
    """
    transfer = session.get(Transfer, transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")

    out_id = transfer.outflow_transaction_id
    in_id = transfer.inflow_transaction_id

    # 1. 恢复交易原始属性并解除绑定
    out_txn = session.get(Transaction, out_id)
    if out_txn:
        out_txn.transfer_id = None
        out_txn.transaction_type = "expense"
        session.add(out_txn)

    in_txn = session.get(Transaction, in_id)
    if in_txn:
        in_txn.transfer_id = None
        in_txn.transaction_type = "income"
        session.add(in_txn)

    # 2. 写入永久黑名单表
    rejected = session.exec(
        select(RejectedTransfer).where(
            RejectedTransfer.outflow_transaction_id == out_id,
            RejectedTransfer.inflow_transaction_id == in_id,
        )
    ).first()

    if not rejected:
        rejected = RejectedTransfer(
            outflow_transaction_id=out_id,
            inflow_transaction_id=in_id,
            reason="User manually rejected transfer merge",
        )
        session.add(rejected)

    # 3. 移除转账记录
    session.delete(transfer)
    session.commit()

    logger.info("已成功驳回转账对并拉黑: outflow=%s, inflow=%s", out_id, in_id)
    return {"status": "ok", "message": "转账已拆分解除，并已加入防自动合并黑名单"}


@router.post("/manual-pair")
def manual_pair_transfer(
    payload: ManualPairPayload,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """人工手动撮合转账对。"""
    out_txn = session.get(Transaction, payload.outflow_transaction_id)
    in_txn = session.get(Transaction, payload.inflow_transaction_id)

    if not out_txn or not in_txn:
        raise HTTPException(status_code=404, detail="One or both transactions not found")

    if out_txn.account_id == in_txn.account_id:
        raise HTTPException(status_code=400, detail="Cannot transfer within the same account")

    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    transfer = Transfer(
        family_id=family.id,
        outflow_transaction_id=out_txn.id,
        inflow_transaction_id=in_txn.id,
        amount=out_txn.amount,
        status="confirmed",
    )
    session.add(transfer)
    session.commit()
    session.refresh(transfer)

    out_txn.transfer_id = transfer.id
    out_txn.transaction_type = "transfer"
    in_txn.transfer_id = transfer.id
    in_txn.transaction_type = "transfer"
    session.add(out_txn)
    session.add(in_txn)
    session.commit()

    return {"status": "ok", "transfer_id": str(transfer.id)}


@router.get("/candidates")
def get_transfer_candidates(
    transaction_id: uuid.UUID = Query(..., description="源交易流水 ID"),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    智能查找与指定流水潜在匹配的转账对端候选交易。
    若传入支出，则检索相近时间、金额相同的收入流水；
    若传入收入，则检索相近时间、金额相同的支出流水。
    """
    from datetime import timedelta
    from models import Account

    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    target_amount = abs(txn.amount)
    cutoff_start = txn.transacted_at - timedelta(days=7)
    cutoff_end = txn.transacted_at + timedelta(days=7)

    # 寻找对端
    is_outflow = txn.transaction_type == "expense" or txn.amount < 0

    stmt = select(Transaction).where(
        Transaction.id != txn.id,
        Transaction.account_id != txn.account_id,
        Transaction.transacted_at >= cutoff_start,
        Transaction.transacted_at <= cutoff_end,
    )

    if is_outflow:
        stmt = stmt.where(
            (Transaction.transaction_type == "income") | (Transaction.amount > 0)
        )
    else:
        stmt = stmt.where(
            (Transaction.transaction_type == "expense") | (Transaction.amount < 0)
        )

    # 排除已是 confirmed transfer 的
    stmt = stmt.where(Transaction.transfer_id.is_(None))

    rows = session.exec(stmt.order_by(desc(Transaction.transacted_at)).limit(50)).all()

    accounts_map = {a.id: a.name for a in session.exec(select(Account)).all()}

    candidates = []
    for r in rows:
        diff = abs(abs(r.amount) - target_amount)
        # 精确或接近同额（误差不超过 0.05 或 5%）
        if diff < Decimal("0.05") or (target_amount > 0 and diff / target_amount < Decimal("0.05")):
            candidates.append({
                "id": str(r.id),
                "account_id": str(r.account_id),
                "account_name": accounts_map.get(r.account_id, "外部账户"),
                "name": r.name,
                "merchant_name": r.merchant_name,
                "amount": str(r.amount.quantize(Decimal("0.01"))),
                "currency": r.currency,
                "transacted_at": r.transacted_at.isoformat(),
                "time_diff_days": abs((r.transacted_at - txn.transacted_at).days),
            })
            if len(candidates) >= limit:
                break

    return {
        "source_transaction": {
            "id": str(txn.id),
            "amount": str(txn.amount.quantize(Decimal("0.01"))),
            "is_outflow": is_outflow,
            "account_name": accounts_map.get(txn.account_id, "当前账户"),
        },
        "candidates": candidates,
        "count": len(candidates),
    }

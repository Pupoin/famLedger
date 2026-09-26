"""Refunds Management and Multi-split Allocation REST API."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func, desc

from database import get_session
from models import Family, RefundAllocation, Transaction
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/refunds", tags=["Refunds"])


class RefundAllocationCreate(BaseModel):
    original_transaction_id: uuid.UUID
    allocated_amount: Decimal


@router.get("/unmatched")
def list_unmatched_refunds(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """查询尚未完成原消费关联或尚未完全抵扣的退款流水。"""
    refunds = session.exec(
        select(Transaction).where(
            Transaction.transaction_type == "refund",
            Transaction.refund_of_transaction_id.is_(None),
        ).order_by(desc(Transaction.transacted_at))
    ).all()

    items = []
    for r in refunds:
        items.append({
            "id": str(r.id),
            "account_id": str(r.account_id),
            "amount": str(r.amount),
            "currency": r.currency,
            "name": r.name,
            "merchant_name": r.merchant_name,
            "transacted_at": r.transacted_at.isoformat(),
            "notes": r.notes,
        })
    return {"unmatched_refunds": items, "count": len(items)}


@router.post("/{refund_id}/allocate")
def allocate_refund_to_expense(
    refund_id: uuid.UUID,
    payload: RefundAllocationCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    人工指定退款与原消费的抵消关联。
    严格执行防御规则：单笔原消费累计被抵扣金额不得超过其原始金额！
    """
    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn or refund_txn.transaction_type != "refund":
        raise HTTPException(status_code=404, detail="Refund transaction not found")

    orig_txn = session.get(Transaction, payload.original_transaction_id)
    if not orig_txn or orig_txn.transaction_type != "expense":
        raise HTTPException(status_code=400, detail="Target transaction must be an expense")

    # 校验累计抵扣上限
    existing_allocations = session.exec(
        select(RefundAllocation).where(
            RefundAllocation.original_transaction_id == orig_txn.id
        )
    ).all()
    already_allocated = sum((a.allocated_amount for a in existing_allocations), Decimal("0"))

    if already_allocated + payload.allocated_amount > orig_txn.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Allocation exceeds original expense amount! (Original: {orig_txn.amount}, already allocated: {already_allocated})"
        )

    allocation = RefundAllocation(
        refund_transaction_id=refund_txn.id,
        original_transaction_id=orig_txn.id,
        allocated_amount=payload.allocated_amount,
    )
    session.add(allocation)

    refund_txn.refund_of_transaction_id = orig_txn.id
    session.add(refund_txn)
    session.commit()

    return {
        "status": "ok",
        "refund_id": str(refund_txn.id),
        "original_id": str(orig_txn.id),
        "allocated_amount": str(payload.allocated_amount),
    }

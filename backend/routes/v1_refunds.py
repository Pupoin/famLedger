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


@router.get("/{refund_id}/candidates")
def get_refund_candidates(
    refund_id: uuid.UUID,
    search: Optional[str] = Query(None, description="搜索商户名或流水名称"),
    limit: int = Query(15, ge=1, le=50),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    智能检索可供退款冲抵的候选原消费流水。
    支持按商户名称、关键词筛选，或根据商户相似度自动检索过去 90 天内的同名/相关消费支出。
    """
    from datetime import timedelta

    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn:
        raise HTTPException(status_code=404, detail="Refund transaction not found")

    stmt = select(Transaction).where(
        Transaction.transaction_type == "expense",
        Transaction.id != refund_txn.id,
    )

    if search:
        search_pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            (Transaction.name.ilike(search_pattern)) | 
            (Transaction.merchant_name.ilike(search_pattern))
        )
    else:
        # 默认推荐过去 90 天内的消费
        cutoff = refund_txn.transacted_at - timedelta(days=90)
        stmt = stmt.where(Transaction.transacted_at >= cutoff)
        if refund_txn.merchant_name:
            stmt = stmt.where(Transaction.merchant_name.ilike(f"%{refund_txn.merchant_name[:4]}%"))

    candidates = session.exec(stmt.order_by(desc(Transaction.transacted_at)).limit(limit)).all()

    results = []
    for c in candidates:
        existing = session.exec(
            select(RefundAllocation).where(RefundAllocation.original_transaction_id == c.id)
        ).all()
        already_allocated = sum((a.allocated_amount for a in existing), Decimal("0"))
        remaining = c.amount - already_allocated

        # 仅返回仍有可抵扣额度的流水
        if remaining > Decimal("0"):
            results.append({
                "id": str(c.id),
                "name": c.name,
                "merchant_name": c.merchant_name,
                "amount": str(c.amount.quantize(Decimal("0.01"))),
                "currency": c.currency,
                "already_allocated": str(already_allocated.quantize(Decimal("0.01"))),
                "remaining_refundable": str(remaining.quantize(Decimal("0.01"))),
                "transacted_at": c.transacted_at.isoformat(),
                "account_id": str(c.account_id),
            })

    return {"candidates": results, "count": len(results)}


@router.post("/{refund_id}/link/{original_id}")
def link_refund_to_original(
    refund_id: uuid.UUID,
    original_id: uuid.UUID,
    allocated_amount: Optional[Decimal] = Query(None),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    符合系统蓝图 10.4 规范：一键将退款关联至原消费支出。
    若未指定冲抵金额，自动默认为 min(退款金额, 原消费剩余可退额)。
    """
    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn:
        raise HTTPException(status_code=404, detail="Refund transaction not found")

    orig_txn = session.get(Transaction, original_id)
    if not orig_txn:
        raise HTTPException(status_code=404, detail="Original expense transaction not found")

    existing = session.exec(
        select(RefundAllocation).where(RefundAllocation.original_transaction_id == orig_txn.id)
    ).all()
    already_allocated = sum((a.allocated_amount for a in existing), Decimal("0"))
    remaining = orig_txn.amount - already_allocated

    if remaining <= Decimal("0"):
        raise HTTPException(status_code=400, detail="Original transaction has no remaining refundable balance")

    alloc_amt = allocated_amount if allocated_amount is not None else min(refund_txn.amount, remaining)
    if alloc_amt > remaining:
        raise HTTPException(status_code=400, detail=f"Allocated amount {alloc_amt} exceeds remaining balance {remaining}")

    # 清理该退款历史的旧 allocation
    old_allocs = session.exec(
        select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund_txn.id)
    ).all()
    for oa in old_allocs:
        session.delete(oa)

    allocation = RefundAllocation(
        refund_transaction_id=refund_txn.id,
        original_transaction_id=orig_txn.id,
        allocated_amount=alloc_amt,
    )
    session.add(allocation)
    refund_txn.refund_of_transaction_id = orig_txn.id
    session.add(refund_txn)
    session.commit()

    return {
        "status": "ok",
        "message": "成功关联退款至原消费",
        "refund_id": str(refund_txn.id),
        "original_id": str(orig_txn.id),
        "allocated_amount": str(alloc_amt.quantize(Decimal("0.01"))),
    }


@router.post("/{refund_id}/unlink")
def unlink_refund(
    refund_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    解除退款与原消费的冲抵关联（Unlink）。
    清理关联的 refund_allocations 记录，并将 refund_of_transaction_id 置空。
    """
    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn:
        raise HTTPException(status_code=404, detail="Refund transaction not found")

    allocs = session.exec(
        select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund_txn.id)
    ).all()
    for a in allocs:
        session.delete(a)

    refund_txn.refund_of_transaction_id = None
    session.add(refund_txn)
    session.commit()

    logger.info("已成功解除退款冲抵绑定: refund_id=%s", refund_id)
    return {"status": "ok", "message": "已成功解除退款冲抵关联"}


@router.get("/{refund_id}/status")
def get_refund_status(
    refund_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """查询退款与原消费的冲抵绑定状态详情。"""
    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn:
        raise HTTPException(status_code=404, detail="Refund transaction not found")

    orig_txn = None
    if refund_txn.refund_of_transaction_id:
        orig_txn = session.get(Transaction, refund_txn.refund_of_transaction_id)

    allocs = session.exec(
        select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund_txn.id)
    ).all()

    return {
        "refund": {
            "id": str(refund_txn.id),
            "amount": str(refund_txn.amount.quantize(Decimal("0.01"))),
            "currency": refund_txn.currency,
            "name": refund_txn.name,
            "merchant_name": refund_txn.merchant_name,
            "transacted_at": refund_txn.transacted_at.isoformat(),
        },
        "is_linked": orig_txn is not None,
        "original_transaction": {
            "id": str(orig_txn.id),
            "amount": str(orig_txn.amount.quantize(Decimal("0.01"))),
            "currency": orig_txn.currency,
            "name": orig_txn.name,
            "merchant_name": orig_txn.merchant_name,
            "transacted_at": orig_txn.transacted_at.isoformat(),
        } if orig_txn else None,
        "allocations": [
            {
                "id": str(a.id),
                "original_id": str(a.original_transaction_id),
                "allocated_amount": str(a.allocated_amount.quantize(Decimal("0.01"))),
                "created_at": a.created_at.isoformat(),
            }
            for a in allocs
        ],
    }

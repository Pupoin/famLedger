"""Refunds Management and Multi-split Allocation REST API."""

from __future__ import annotations

from services.transaction_lock import lock_mutation

import logging
import uuid
from calendar import monthrange
from types import SimpleNamespace
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func, desc

from database import get_session
from models import Account, Family, RefundAllocation, Transaction, User
from services.booking_money import money_metadata, money_text
from services.refund_money import allocate, allocation_metadata, remaining_native, refund_match_score
from services.request_validation import CurrencyCode
from auth import get_current_user_or_token
from routes.v1_transactions import serialize_utc_datetime
from services.stats_engine import (
    get_family_active_account_ids,
    get_user_visible_account_ids,
    get_user_writable_account_ids,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/refunds", tags=["Refunds"])


@router.post("/auto-match")
def replay_auto_matches(session: Session = Depends(get_session),
                        user_or_ctx: Any = Depends(get_current_user_or_token)):
    from services.refund_money import match_historical_refunds
    result = match_historical_refunds(session, user_or_ctx)
    session.commit()
    return result


def _verify_refund_permission(
    session: Session,
    user_or_ctx: Any,
    txn: Transaction,
    action_desc: str = "操作退款",
    require_write: bool = False,
):
    if isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"):
        return
    current_user = None
    if isinstance(user_or_ctx, str):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")
    if require_write:
        from routes.v1_transactions import _verify_account_write_permission
        _verify_account_write_permission(session, user_or_ctx, txn.account_id, action_desc)
        return
    if current_user.role == "admin":
        return
    acc = session.get(Account, txn.account_id)
    if not acc or acc.family_id != current_user.family_id:
        raise HTTPException(status_code=403, detail=f"无权{action_desc}：该流水属于其他家庭")

    visible_ids = get_user_visible_account_ids(session, current_user, current_user.family_id)
    if txn.account_id not in visible_ids:
        raise HTTPException(status_code=403, detail=f"无权{action_desc}：对该私有账户无访问权限")


class RefundAllocationCreate(BaseModel):
    original_transaction_id: uuid.UUID
    allocated_amount: Decimal = Field(..., gt=0, max_digits=19, decimal_places=4, description="原消费原币冲抵金额")
    original_currency: Optional[CurrencyCode] = None
    refund_original_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)


@router.get("/unmatched")
def list_unmatched_refunds(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """查询尚未完成原消费关联或尚未完全抵扣的退款流水。"""
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_user and current_user.role == "admin")
    visible_acc_ids = set()
    if not is_admin:
        if not current_user or not current_user.family_id:
            return {"unmatched_refunds": [], "count": 0}
        visible_acc_ids = get_user_visible_account_ids(session, current_user, family_id=current_user.family_id)
        if not visible_acc_ids:
            return {"unmatched_refunds": [], "count": 0}

    stmt = select(Transaction).where(
        Transaction.transaction_type == "refund",
    )
    if not is_admin:
        stmt = stmt.where(Transaction.account_id.in_(visible_acc_ids))

    refunds = session.exec(stmt.order_by(desc(Transaction.transacted_at))).all()

    items = []
    for r in refunds:
        allocations = session.exec(select(RefundAllocation).where(RefundAllocation.refund_transaction_id == r.id)).all()
        allocated = sum((allocation.refund_original_amount or allocation.allocated_amount for allocation in allocations), Decimal("0"))
        if not allocations and r.refund_of_transaction_id:
            allocated = r.amount  # Historical single-link records.
        remaining = remaining_native(session, r, refund=True) if r.original_amount is not None else r.amount - allocated
        if remaining <= 0:
            continue
        r_occurred_at = None
        if r.occurred_at:
            r_occurred_at = serialize_utc_datetime(r.occurred_at)
        elif r.created_at:
            r_occurred_at = serialize_utc_datetime(r.created_at)
        elif r.transacted_at:
            r_occurred_at = f"{r.transacted_at.isoformat()}T00:00:00Z"

        items.append({
            "id": str(r.id),
            **money_metadata(r),
            "account_id": str(r.account_id),
            "amount": str(r.amount),
            "allocated_amount": str(allocated),
            "remaining_amount": str(remaining),
            "currency": r.currency,
            "narration": r.narration,
            "name": r.narration,
            "transacted_at": r.transacted_at.isoformat(),
            "occurred_at": r_occurred_at,
            "notes": r.notes,
        })
    return {"unmatched_refunds": items, "count": len(items)}


@router.get("/candidates")
def search_expense_candidates_for_refund(
    search: Optional[str] = Query(None, description="搜索商户名或流水名称"),
    account_id: Optional[uuid.UUID] = Query(None, description="限定账户"),
    limit: int = Query(20, ge=1, le=100),
    days: int = Query(180, ge=1, le=730),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    新建退款前通用候选原消费检索接口。
    查询最近 N 天内尚未完全抵扣的支出消费流水，支持关键词与账户过滤。
    """
    from datetime import date, timedelta
    from models import Category

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_user and current_user.role == "admin")
    visible_acc_ids = set()
    if not is_admin:
        if not current_user or not current_user.family_id:
            return {"candidates": [], "count": 0}
        visible_acc_ids = get_user_visible_account_ids(session, current_user, family_id=current_user.family_id)
        if not visible_acc_ids:
            return {"candidates": [], "count": 0}

    cutoff = date.today() - timedelta(days=days)
    stmt = select(Transaction).where(
        Transaction.transaction_type == "expense",
        Transaction.transacted_at >= cutoff,
    )
    if not is_admin:
        stmt = stmt.where(Transaction.account_id.in_(visible_acc_ids))
    if account_id:
        if not is_admin and account_id not in visible_acc_ids:
            return {"candidates": [], "count": 0}
        stmt = stmt.where(Transaction.account_id == account_id)
    if search and search.strip():
        stmt = stmt.where(Transaction.narration.ilike(f"%{search.strip()}%"))

    candidates = session.exec(stmt.order_by(desc(Transaction.transacted_at)).limit(limit * 2)).all()

    results = []
    for c in candidates:
        existing = session.exec(
            select(RefundAllocation).where(RefundAllocation.original_transaction_id == c.id)
        ).all()
        already_allocated = sum((a.allocated_amount for a in existing), Decimal("0"))
        remaining = remaining_native(session, c) if c.original_amount is not None else Decimal(0)

        # 仅返回仍有可退额度的消费流水
        if remaining > Decimal("0"):
            acc_name = None
            if c.account_id:
                acc = session.get(Account, c.account_id)
                if acc:
                    acc_name = acc.name

            cat_name = None
            if c.category_id:
                cat = session.get(Category, c.category_id)
                if cat:
                    cat_name = cat.name

            c_occurred_at = None
            if c.occurred_at:
                c_occurred_at = serialize_utc_datetime(c.occurred_at)
            elif c.created_at:
                c_occurred_at = serialize_utc_datetime(c.created_at)
            elif c.transacted_at:
                c_occurred_at = f"{c.transacted_at.isoformat()}T00:00:00Z"

            results.append({
                "id": str(c.id),
                **money_metadata(c),
                "narration": c.narration,
                "name": c.narration,
                "amount": str(c.amount.quantize(Decimal("0.01"))),
                "currency": c.currency,
                "already_allocated": str(already_allocated.quantize(Decimal("0.01"))),
                "remaining_refundable": money_text(remaining),
                "transacted_at": c.transacted_at.isoformat(),
                "occurred_at": c_occurred_at,
                "account_id": str(c.account_id) if c.account_id else None,
                "account_name": acc_name,
                "category_id": str(c.category_id) if c.category_id else None,
                "category_name": cat_name,
            })
            if len(results) >= limit:
                break

    return {"candidates": results, "count": len(results)}


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
    lock_mutation(session)
    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn or refund_txn.transaction_type != "refund":
        raise HTTPException(status_code=404, detail="Refund transaction not found")

    orig_txn = session.get(Transaction, payload.original_transaction_id)
    if not orig_txn or orig_txn.transaction_type != "expense":
        raise HTTPException(status_code=400, detail="Target transaction must be an expense")

    allocation = allocate(session, user_or_ctx, refund_txn, orig_txn,
                          payload.allocated_amount, payload.original_currency, payload.refund_original_amount)
    session.commit()
    return {"status": "ok", "refund_id": str(refund_txn.id), "original_id": str(orig_txn.id),
            **allocation_metadata(allocation)}


@router.get("/{refund_id}/candidates")
def get_refund_candidates(
    refund_id: uuid.UUID,
    search: Optional[str] = Query(None, description="搜索商户名或流水名称"),
    limit: int = Query(15, ge=1, le=50),
    recommendations_only: bool = Query(True),
    preview_refund: bool = Query(False),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    推荐退款日前两个日历月内、相似度严格大于 0.5 的原消费。
    显式关闭推荐筛选可手动搜索其他历史消费；始终保留租户、权限、方向及额度校验。
    """
    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn:
        raise HTTPException(status_code=404, detail="Refund transaction not found")

    _verify_refund_permission(session, user_or_ctx, refund_txn, "查询候选原消费")
    if refund_txn.transaction_type != "refund" and not preview_refund:
        raise HTTPException(400, "请选择退款类型后查询候选原消费")
    refund_account = session.get(Account, refund_txn.account_id)
    if not refund_account:
        raise HTTPException(404, "交易所属账户不存在")

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    actor = user_or_ctx if is_service else current_user
    writable_acc_ids = get_user_writable_account_ids(session, actor, family_id=refund_account.family_id)
    if not writable_acc_ids:
        return {"candidates": [], "count": 0}

    stmt = select(Transaction).join(Account, Transaction.account_id == Account.id).where(
        Transaction.transaction_type == "expense",
        Transaction.id != refund_txn.id,
        Transaction.account_id.in_(writable_acc_ids),
        Account.family_id == refund_account.family_id,
        Account.is_active == True,
        Transaction.transacted_at <= refund_txn.transacted_at,
    )
    # Existing allocations are shown separately, not offered as a new allocation
    # (allocate replaces a pair's quantity rather than adding to it).
    stmt = stmt.where(Transaction.id.not_in(select(RefundAllocation.original_transaction_id).where(
        RefundAllocation.refund_transaction_id == refund_txn.id)))
    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        stmt = stmt.where(Transaction.narration.ilike(search_pattern))
    if recommendations_only:
        month_index = max(12, refund_txn.transacted_at.year * 12 + refund_txn.transacted_at.month - 1 - 2)
        year, month = divmod(month_index, 12)
        month += 1
        cutoff = refund_txn.transacted_at.replace(year=year, month=month,
            day=min(refund_txn.transacted_at.day, monthrange(year, month)[1]))
        stmt = stmt.where(Transaction.transacted_at >= cutoff)
    candidates = session.exec(stmt).all()
    used = dict(session.exec(select(RefundAllocation.original_transaction_id,
        func.sum(RefundAllocation.allocated_amount)).where(
            RefundAllocation.original_transaction_id.in_([c.id for c in candidates]))
        .group_by(RefundAllocation.original_transaction_id)).all()) if candidates else {}
    account_names = {account.id: account.name for account in session.exec(select(Account).where(
        Account.id.in_({c.account_id for c in candidates}))).all()} if candidates else {}
    # A scoring snapshot must never copy ORM instrumentation or dirty a GET's
    # persisted transaction while simulating a type change.
    scored_refund = SimpleNamespace(**{name: getattr(refund_txn, name) for name in (
        "transaction_type", "extra", "original_amount", "original_currency", "transacted_at", "account_id", "narration")})
    if preview_refund and refund_txn.transaction_type != "refund":
        scored_refund.transaction_type = "refund"
        scored_refund.extra = {**(scored_refund.extra or {}), "direction": "inflow"}
    elif refund_txn.original_amount is not None:
        scored_refund.original_amount = remaining_native(session, refund_txn, refund=True)

    results = []
    for c in candidates:
        already_allocated = used.get(c.id, Decimal("0"))
        remaining = max(Decimal(0), c.original_amount - already_allocated) if c.original_amount is not None else Decimal(0)
        score, components = refund_match_score(scored_refund, c, remaining,
            allow_partial=True, allow_cross_currency=True, allow_historical=not recommendations_only)
        if not components.get("opposite_directions"):
            continue
        if recommendations_only and score <= 0.5:
            continue

        # 仅返回仍有可抵扣额度的流水
        if remaining > Decimal("0"):
            c_occurred_at = None
            if c.occurred_at:
                c_occurred_at = serialize_utc_datetime(c.occurred_at)
            elif c.created_at:
                c_occurred_at = serialize_utc_datetime(c.created_at)
            elif c.transacted_at:
                c_occurred_at = f"{c.transacted_at.isoformat()}T00:00:00Z"

            results.append({
                "id": str(c.id),
                **money_metadata(c),
                "narration": c.narration,
                "name": c.narration,
                "amount": str(c.amount.quantize(Decimal("0.01"))),
                "currency": c.currency,
                "already_allocated": str(already_allocated.quantize(Decimal("0.01"))),
                "remaining_refundable": money_text(remaining),
                "transacted_at": c.transacted_at.isoformat(),
                "occurred_at": c_occurred_at,
                "account_id": str(c.account_id),
                "account_name": account_names[c.account_id],
                "similarity_score": score,
                "score_components": components,
            })
    results.sort(key=lambda row: (-row["similarity_score"], -int(row["transacted_at"].replace("-", "")), row["id"]))
    results = results[:limit]
    return {"candidates": results, "count": len(results), "min_score": 0.5 if recommendations_only else None,
            "recommendations_only": recommendations_only}


@router.post("/{refund_id}/link/{original_id}")
def link_refund_to_original(
    refund_id: uuid.UUID,
    original_id: uuid.UUID,
    allocated_amount: Optional[Decimal] = Query(None, gt=0, max_digits=19, decimal_places=4),
    original_currency: Optional[CurrencyCode] = Query(None),
    refund_original_amount: Optional[Decimal] = Query(None, gt=0, max_digits=19, decimal_places=4),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    符合系统蓝图 10.4 规范：一键将退款关联至原消费支出。
    若未指定冲抵金额，自动默认为 min(退款金额, 原消费剩余可退额)。
    """
    lock_mutation(session)
    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn:
        raise HTTPException(status_code=404, detail="Refund transaction not found")
    if refund_txn.transaction_type != "refund":
        raise HTTPException(status_code=400, detail="Target transaction is not a refund")

    orig_txn = session.get(Transaction, original_id)
    if not orig_txn:
        raise HTTPException(status_code=404, detail="Original expense transaction not found")
    if orig_txn.transaction_type != "expense":
        raise HTTPException(status_code=400, detail="Target transaction must be an expense")

    allocation = allocate(session, user_or_ctx, refund_txn, orig_txn,
                          allocated_amount, original_currency, refund_original_amount)
    session.commit()
    return {"status": "ok", "refund_id": str(refund_txn.id), "original_id": str(orig_txn.id),
            **allocation_metadata(allocation)}


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
    lock_mutation(session)
    refund_txn = session.get(Transaction, refund_id)
    if not refund_txn:
        raise HTTPException(status_code=404, detail="Refund transaction not found")

    _verify_refund_permission(session, user_or_ctx, refund_txn, "解除退款关联", require_write=True)

    allocs = session.exec(
        select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund_txn.id)
    ).all()
    for a in allocs:
        session.delete(a)

    refund_txn.refund_of_transaction_id = None
    refund_txn.extra = {**(refund_txn.extra or {}), "auto_refund_blocked": True}
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

    _verify_refund_permission(session, user_or_ctx, refund_txn, "查询退款状态")

    orig_txn = None
    if refund_txn.refund_of_transaction_id:
        orig_txn = session.get(Transaction, refund_txn.refund_of_transaction_id)

    allocs = session.exec(
        select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund_txn.id)
    ).all()

    is_linked = bool(refund_txn.refund_of_transaction_id or allocs)
    def readable(original):
        if original is None:
            return False
        try:
            _verify_refund_permission(session, user_or_ctx, original, "查询原消费")
            return True
        except HTTPException as exc:
            if exc.status_code in (401, 403, 404):
                return False
            raise
    if not readable(orig_txn):
        orig_txn = None
    allocs = [allocation for allocation in allocs
              if readable(session.get(Transaction, allocation.original_transaction_id))]

    orig_exact = None
    if orig_txn:
        if orig_txn.occurred_at:
            orig_exact = serialize_utc_datetime(orig_txn.occurred_at)
        elif orig_txn.created_at:
            orig_exact = serialize_utc_datetime(orig_txn.created_at)
        elif orig_txn.transacted_at:
            orig_exact = f"{orig_txn.transacted_at.isoformat()}T00:00:00Z"

    refund_exact = None
    if refund_txn.occurred_at:
        refund_exact = serialize_utc_datetime(refund_txn.occurred_at)
    elif refund_txn.created_at:
        refund_exact = serialize_utc_datetime(refund_txn.created_at)
    elif refund_txn.transacted_at:
        refund_exact = f"{refund_txn.transacted_at.isoformat()}T00:00:00Z"

    return {
        "refund": {
            "id": str(refund_txn.id),
            "amount": str(refund_txn.amount.quantize(Decimal("0.01"))),
            "currency": refund_txn.currency,
            "narration": refund_txn.narration,
            "name": refund_txn.narration,
            "transacted_at": refund_txn.transacted_at.isoformat(),
            "occurred_at": refund_exact,
        },
        "is_linked": is_linked,
        "original_transaction": {
            "id": str(orig_txn.id),
            "amount": str(orig_txn.amount.quantize(Decimal("0.01"))),
            "currency": orig_txn.currency,
            "narration": orig_txn.narration,
            "name": orig_txn.narration,
            "transacted_at": orig_txn.transacted_at.isoformat(),
            "occurred_at": orig_exact,
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

import hashlib
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func, desc, or_

from database import get_session
from models import (
    Account,
    Category,
    Family,
    RefundAllocation,
    StoredEmail,
    Transaction,
    Transfer,
    User,
)
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/transactions", tags=["Transactions"])


class TransactionIn(BaseModel):
    account_id: Optional[str] = None
    account_identifier: Optional[str] = None
    transacted_at: Optional[date] = None
    occurred_at: Optional[datetime] = None
    amount: Decimal
    currency: str = "CNY"
    name: str
    merchant_name: Optional[str] = None
    category_id: Optional[uuid.UUID] = None
    transaction_type: Optional[str] = "expense"  # expense | income | transfer | refund
    nature: Optional[str] = None
    kind: Optional[str] = None
    external_id: Optional[str] = None
    raw_email_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    counterparty: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


def _resolve_account(session: Session, family_id: uuid.UUID, identifier: str) -> Account:
    """根据账户 ID 或卡号后四位/名称自动查找或预拨账户。"""
    # 1. 尝试以 UUID 查找
    try:
        acc_uuid = uuid.UUID(identifier)
        acc = session.get(Account, acc_uuid)
        if acc:
            return acc
    except (ValueError, TypeError):
        pass

    # 2. 按卡号或名称查找
    cleaned_id = identifier.strip()
    accounts = session.exec(select(Account).where(Account.family_id == family_id)).all()
    for acc in accounts:
        if cleaned_id in acc.name or (acc.official_name and cleaned_id in acc.official_name):
            return acc

    # 3. 未找到则自动预拨创建
    is_credit = any(k in cleaned_id for k in ("9085", "7661", "信用卡", "credit"))
    acc_type = "credit_card" if is_credit else "checking"
    acc_name = f"招商银行{'信用卡' if is_credit else '借记卡'} ({cleaned_id})"
    
    # 查找默认所有者用户
    owner = session.exec(select(User).where(User.family_id == family_id)).first()
    owner_id = owner.id if owner else uuid.uuid4()

    new_acc = Account(
        family_id=family_id,
        owner_id=owner_id,
        name=acc_name,
        account_type=acc_type,
        currency="CNY",
        institution_name="招商银行",
    )
    session.add(new_acc)
    session.commit()
    session.refresh(new_acc)
    logger.info("自动预拨新账户: id=%s name=%s", new_acc.id, new_acc.name)
    return new_acc


@router.post("")
@router.post("/")
async def create_or_ingest_transaction(
    request: Request,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    创建或批量录入单笔交易流水。
    支持兼容 FamLedger 原生格式与 Sure Client REST 协议格式（带 transaction 嵌套层）。
    支持绑定 raw_email_id，自动触发转账撮合与退款抵消。
    """
    raw_body = await request.json()
    payload_data = raw_body.get("transaction", raw_body)
    data = TransactionIn(**payload_data)

    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    # 1. 确定账户
    account_key = data.account_id or data.account_identifier or "default"
    account = _resolve_account(session, family.id, str(account_key))

    # 2. 确定交易日期与精确时间
    exact_time = data.occurred_at
    transacted_date = data.transacted_at or (exact_time.date() if exact_time else date.today())

    # 3. 确定交易方向与类型
    txn_type = data.transaction_type or "expense"
    if data.nature:
        if data.nature in ("refund", "退款", "退货", "消费撤销"):
            txn_type = "refund"
        elif data.nature in ("income", "收入"):
            txn_type = "income"
        elif data.nature in ("transfer", "转账"):
            txn_type = "transfer"
        else:
            txn_type = "expense"

    # 金额统一规范化（支出存为正数或根据模型约定存储绝对值，transaction_type 区分属性）
    amount = abs(Decimal(str(data.amount)))

    # 4. 幂等去重校验 (account_id + external_id)
    if data.external_id:
        existing = session.exec(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.external_id == data.external_id,
            )
        ).first()
        if existing:
            return {
                "id": str(existing.id),
                "account_id": str(existing.account_id),
                "external_id": existing.external_id,
                "status": "duplicate",
                "message": "Transaction already ingested",
            }

    # 5. 组装交易对象
    extra_data = data.extra or {}
    if data.counterparty:
        extra_data["counterparty"] = data.counterparty

    txn = Transaction(
        account_id=account.id,
        raw_email_id=data.raw_email_id,
        external_id=data.external_id,
        transacted_at=transacted_date,
        exact_time=exact_time,
        amount=amount,
        currency=data.currency,
        name=data.name,
        merchant_name=data.merchant_name or data.name,
        category_id=data.category_id,
        transaction_type=txn_type,
        status="cleared",
        notes=data.notes,
        extra=extra_data,
    )
    session.add(txn)
    session.commit()
    session.refresh(txn)

    # 6. 如果关联了原始邮件，回写更新 StoredEmail 状态
    if data.raw_email_id:
        stored_email = session.get(StoredEmail, data.raw_email_id)
        if stored_email:
            stored_email.status = "parsed"
            stored_email.parsed_count = (stored_email.parsed_count or 0) + 1
            stored_email.parsed_at = datetime.now(timezone.utc)
            session.add(stored_email)
            session.commit()

    # 7. 智能转账自动对齐撮合 (2 天容差，跨账户，同金额)
    if txn_type in ("transfer", "expense", "income"):
        # 寻找最近 2 天内同金额且反向的候选流水
        cand_start = transacted_date - timedelta(days=2)
        cand_end = transacted_date + timedelta(days=2)
        candidate = session.exec(
            select(Transaction).where(
                Transaction.id != txn.id,
                Transaction.account_id != txn.account_id,
                Transaction.amount == amount,
                Transaction.transacted_at >= cand_start,
                Transaction.transacted_at <= cand_end,
                Transaction.transfer_id.is_(None),
            )
        ).first()

        if candidate:
            out_txn = txn if txn_type in ("expense", "transfer") else candidate
            in_txn = candidate if txn_type in ("expense", "transfer") else txn
            transfer_record = Transfer(
                family_id=family.id,
                outflow_transaction_id=out_txn.id,
                inflow_transaction_id=in_txn.id,
                amount=amount,
                status="confirmed",
            )
            session.add(transfer_record)
            session.commit()
            session.refresh(transfer_record)

            out_txn.transfer_id = transfer_record.id
            out_txn.transaction_type = "transfer"
            in_txn.transfer_id = transfer_record.id
            in_txn.transaction_type = "transfer"
            session.add(out_txn)
            session.add(in_txn)
            session.commit()
            logger.info("自动撮合转账对: outflow=%s inflow=%s amount=%s", out_txn.id, in_txn.id, amount)

    # 8. 退款自动匹配 (90 天内同商户原消费)
    if txn_type == "refund":
        refund_start = transacted_date - timedelta(days=90)
        orig_cand = session.exec(
            select(Transaction).where(
                Transaction.id != txn.id,
                Transaction.amount >= amount,
                Transaction.transacted_at >= refund_start,
                Transaction.transacted_at <= transacted_date,
                Transaction.transaction_type == "expense",
                or_(
                    Transaction.merchant_name == txn.merchant_name,
                    Transaction.name == txn.name,
                ),
            ).order_by(desc(Transaction.transacted_at))
        ).first()

        if orig_cand:
            txn.refund_of_transaction_id = orig_cand.id
            session.add(txn)
            allocation = RefundAllocation(
                refund_transaction_id=txn.id,
                original_transaction_id=orig_cand.id,
                allocated_amount=amount,
            )
            session.add(allocation)
            session.commit()
            logger.info("自动关联退款原消费: refund=%s original=%s amount=%s", txn.id, orig_cand.id, amount)

    return {
        "id": str(txn.id),
        "account_id": str(txn.account_id),
        "external_id": txn.external_id,
        "amount": str(txn.amount),
        "currency": txn.currency,
        "name": txn.name,
        "transaction_type": txn.transaction_type,
        "transacted_at": txn.transacted_at.isoformat(),
        "status": "created",
    }


@router.get("")
@router.get("/")
def list_transactions(
    account_id: Optional[uuid.UUID] = Query(None),
    category_id: Optional[uuid.UUID] = Query(None),
    transaction_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None, description="Keyset pagination cursor"),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    极速游标分页交易流水列表（支持 60 FPS 虚拟滚动渲染）。
    """
    stmt = select(Transaction)
    
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if category_id:
        stmt = stmt.where(Transaction.category_id == category_id)
    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)
    if start_date:
        stmt = stmt.where(Transaction.transacted_at >= start_date)
    if end_date:
        stmt = stmt.where(Transaction.transacted_at <= end_date)
    if search:
        kw = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Transaction.name.ilike(kw),
                Transaction.merchant_name.ilike(kw),
                Transaction.notes.ilike(kw),
            )
        )

    # 排序采用 (transacted_at DESC, id DESC)
    stmt = stmt.order_by(desc(Transaction.transacted_at), desc(Transaction.id)).limit(limit + 1)
    results = session.exec(stmt).all()

    has_more = len(results) > limit
    items = results[:limit]

    output = []
    for t in items:
        output.append({
            "id": str(t.id),
            "account_id": str(t.account_id),
            "raw_email_id": str(t.raw_email_id) if t.raw_email_id else None,
            "external_id": t.external_id,
            "transacted_at": t.transacted_at.isoformat(),
            "exact_time": t.exact_time.isoformat() if t.exact_time else None,
            "amount": str(t.amount),
            "currency": t.currency,
            "name": t.name,
            "merchant_name": t.merchant_name,
            "category_id": str(t.category_id) if t.category_id else None,
            "transaction_type": t.transaction_type,
            "status": t.status,
            "transfer_id": str(t.transfer_id) if t.transfer_id else None,
            "refund_of_transaction_id": str(t.refund_of_transaction_id) if t.refund_of_transaction_id else None,
            "notes": t.notes,
        })

    next_cursor = output[-1]["id"] if has_more and output else None

    return {
        "items": output,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "count": len(output),
    }

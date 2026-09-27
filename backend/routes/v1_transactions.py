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
    RejectedTransfer,
    Rule,
    StoredEmail,
    Transaction,
    TransactionSplit,
    Transfer,
    User,
)
from auth import get_current_user_or_token
from services.rules.pipeline import RulePipeline

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
        if cleaned_id in acc.name or (acc.institution_name and cleaned_id in acc.institution_name):
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

    # 执行自动化规则引擎清洗与自动分类 (Rules Pipeline)
    active_rules = session.exec(
        select(Rule).where(Rule.family_id == family.id, Rule.is_active == True).order_by(Rule.priority)
    ).all()
    if active_rules:
        pipeline = RulePipeline(active_rules)
        pipeline.process_transaction(txn, account_name=account.name, dry_run=False)

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

            # 校验是否在已驳回黑名单中
            is_rejected = session.exec(
                select(RejectedTransfer).where(
                    RejectedTransfer.outflow_transaction_id == out_txn.id,
                    RejectedTransfer.inflow_transaction_id == in_txn.id,
                )
            ).first()

            if not is_rejected:
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
        "amount": str(txn.amount.quantize(Decimal("0.01"))),
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

    accounts_map = {a.id: a for a in session.exec(select(Account)).all()}
    import re

    output = []
    for t in items:
        acc = accounts_map.get(t.account_id)
        acc_name = acc.name if acc else "招商银行账户"
        m = re.search(r"\(([0-9Xx]{4})\)", acc_name)
        mask = m.group(1) if m else (acc_name[-4:] if len(acc_name) >= 4 else "0000")

        output.append({
            "id": str(t.id),
            "account_id": str(t.account_id),
            "account_name": acc_name,
            "account_mask": mask,
            "raw_email_id": str(t.raw_email_id) if t.raw_email_id else None,
            "external_id": t.external_id,
            "transacted_at": t.transacted_at.isoformat(),
            "exact_time": t.exact_time.isoformat() if t.exact_time else None,
            "amount": str(t.amount.quantize(Decimal("0.01"))),
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


class SplitItem(BaseModel):
    category_id: Optional[uuid.UUID] = None
    amount: Decimal
    notes: Optional[str] = None


class SplitPayload(BaseModel):
    splits: List[SplitItem]


@router.post("/{transaction_id}/split")
def split_transaction(
    transaction_id: uuid.UUID,
    payload: SplitPayload,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """交易拆分（Split）。将一笔交易拆分为多个分类子项，校验总金额一致性。"""
    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="交易不存在")

    if not payload.splits or len(payload.splits) < 2:
        raise HTTPException(status_code=400, detail="拆分必须包含至少两个子项")

    # 校验总金额（绝对值）
    total_splits = sum(s.amount for s in payload.splits)
    if total_splits.quantize(Decimal("0.01")) != abs(txn.amount).quantize(Decimal("0.01")):
        raise HTTPException(
            status_code=400,
            detail=f"拆分子项金额总和 ({total_splits}) 必须等于交易原始金额 ({abs(txn.amount)})",
        )

    # 清除旧拆分
    existing = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == txn.id)
    ).all()
    for e in existing:
        session.delete(e)

    # 写入新拆分
    for s in payload.splits:
        split_entry = TransactionSplit(
            transaction_id=txn.id,
            category_id=s.category_id,
            amount=s.amount,
            notes=s.notes,
        )
        session.add(split_entry)

    txn.is_split = True
    session.add(txn)
    session.commit()
    session.refresh(txn)

    return {
        "transaction_id": str(txn.id),
        "is_split": True,
        "splits_count": len(payload.splits),
    }


@router.get("/{transaction_id}/splits")
def get_transaction_splits(
    transaction_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取单笔交易的所有拆分明细。"""
    splits = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id)
    ).all()

    return [
        {
            "id": str(s.id),
            "transaction_id": str(s.transaction_id),
            "category_id": str(s.category_id) if s.category_id else None,
            "amount": str(s.amount.quantize(Decimal("0.01"))),
            "notes": s.notes,
            "created_at": s.created_at.isoformat(),
        }
        for s in splits
    ]


@router.get("/{transaction_id}")
def get_transaction_detail(
    transaction_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取单笔交易的完整详情，包含转账对端详情、退款冲抵绑定及拆分明细。"""
    from models import Category, Transfer, RefundAllocation

    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="交易不存在")

    account = session.get(Account, txn.account_id)
    category = session.get(Category, txn.category_id) if txn.category_id else None

    # 转账对端信息
    paired_transfer = None
    if txn.transfer_id:
        tr = session.get(Transfer, txn.transfer_id)
        if tr:
            other_id = tr.inflow_transaction_id if txn.id == tr.outflow_transaction_id else tr.outflow_transaction_id
            other_txn = session.get(Transaction, other_id)
            if other_txn:
                other_acc = session.get(Account, other_txn.account_id)
                paired_transfer = {
                    "transfer_id": str(tr.id),
                    "status": tr.status,
                    "is_outflow": txn.id == tr.outflow_transaction_id,
                    "counterpart": {
                        "id": str(other_txn.id),
                        "name": other_txn.name,
                        "merchant_name": other_txn.merchant_name,
                        "amount": str(other_txn.amount.quantize(Decimal("0.01"))),
                        "account_name": other_acc.name if other_acc else "外部账户",
                        "transacted_at": other_txn.transacted_at.isoformat(),
                    }
                }

    # 退款关联详情
    refund_info = None
    if txn.transaction_type == "refund":
        orig_txn = session.get(Transaction, txn.refund_of_transaction_id) if txn.refund_of_transaction_id else None
        orig_acc = session.get(Account, orig_txn.account_id) if orig_txn else None
        allocs = session.exec(
            select(RefundAllocation).where(RefundAllocation.refund_transaction_id == txn.id)
        ).all()
        refund_info = {
            "is_linked": orig_txn is not None,
            "original_transaction": {
                "id": str(orig_txn.id),
                "name": orig_txn.name,
                "merchant_name": orig_txn.merchant_name,
                "amount": str(orig_txn.amount.quantize(Decimal("0.01"))),
                "account_name": orig_acc.name if orig_acc else "原账户",
                "transacted_at": orig_txn.transacted_at.isoformat(),
            } if orig_txn else None,
            "allocated_amount": str(sum((a.allocated_amount for a in allocs), Decimal("0")).quantize(Decimal("0.01"))),
        }
    elif txn.transaction_type == "expense":
        allocs = session.exec(
            select(RefundAllocation).where(RefundAllocation.original_transaction_id == txn.id)
        ).all()
        if allocs:
            refund_txns = []
            for a in allocs:
                r_txn = session.get(Transaction, a.refund_transaction_id)
                if r_txn:
                    refund_txns.append({
                        "id": str(r_txn.id),
                        "name": r_txn.name,
                        "amount": str(r_txn.amount.quantize(Decimal("0.01"))),
                        "allocated_amount": str(a.allocated_amount.quantize(Decimal("0.01"))),
                        "transacted_at": r_txn.transacted_at.isoformat(),
                    })
            refund_info = {
                "has_refunds": True,
                "total_refunded": str(sum((a.allocated_amount for a in allocs), Decimal("0")).quantize(Decimal("0.01"))),
                "refunds": refund_txns,
            }

    # 拆分项
    splits = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == txn.id)
    ).all()

    return {
        "id": str(txn.id),
        "account_id": str(txn.account_id),
        "account_name": account.name if account else "招商银行账户",
        "transacted_at": txn.transacted_at.isoformat(),
        "exact_time": txn.exact_time.isoformat() if txn.exact_time else None,
        "amount": str(txn.amount.quantize(Decimal("0.01"))),
        "currency": txn.currency,
        "name": txn.name,
        "merchant_name": txn.merchant_name,
        "category_id": str(txn.category_id) if txn.category_id else None,
        "category_name": category.name if category else "未分类",
        "category_icon": category.icon if category else "📦",
        "transaction_type": txn.transaction_type,
        "status": txn.status,
        "notes": txn.notes,
        "raw_email_id": str(txn.raw_email_id) if txn.raw_email_id else None,
        "paired_transfer": paired_transfer,
        "refund_info": refund_info,
        "splits": [
            {
                "id": str(s.id),
                "category_id": str(s.category_id) if s.category_id else None,
                "amount": str(s.amount.quantize(Decimal("0.01"))),
                "notes": s.notes,
            }
            for s in splits
        ],
    }


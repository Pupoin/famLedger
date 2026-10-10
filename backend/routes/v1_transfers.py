"""Transfers Arbitration and Blacklist Management REST API."""

from __future__ import annotations

from services.transaction_lock import lock_mutation

import logging
import uuid
from decimal import Decimal
from datetime import date, datetime, timezone, time as DayTime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select, desc

from database import get_session
from models import (
    Account,
    AccountShare,
    Family,
    RejectedTransfer,
    Transaction,
    Transfer,
    User,
)
from auth import get_current_user_or_token
from routes.v1_transactions import serialize_utc_datetime, _verify_account_write_permission, _verify_account_transfer_in_permission, clean_to_utc, get_local_date
from services.stats_engine import (
    get_family_active_account_ids,
    get_user_visible_account_ids,
    get_user_writable_account_ids,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/transfers", tags=["Transfers"])


class ManualPairPayload(BaseModel):
    outflow_transaction_id: uuid.UUID
    inflow_transaction_id: uuid.UUID


class TransferCreatePayload(BaseModel):
    """新建一笔内部转账：同时创建转出和转入两条流水，并自动配对。"""
    from_account_id: uuid.UUID   # 转出账户
    to_account_id: uuid.UUID     # 转入账户
    amount: Decimal = Field(gt=0) # 转账金额（正数）
    narration: Optional[str] = Field(default=None, max_length=255)      # 交易摘要/名称
    name: Optional[str] = Field(default=None, max_length=255)           # 兼容旧字段
    transacted_at: Optional[date] = None   # 日期 YYYY-MM-DD，默认今日
    notes: Optional[str] = None
    currency: str = "CNY"
    time: Optional[str] = None
    occurred_at: Optional[datetime] = None


    @field_validator("occurred_at", mode="before")
    @classmethod
    def normalize_timestamp(cls, value):
        return clean_to_utc(value)


@router.post("")
@router.post("/create")
def create_transfer(
    payload: TransferCreatePayload,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    新建内部转账：原子地创建转出和转入两笔流水，并生成已确认的 transfer 配对记录。
    保证两侧账户余额同时正确更新。
    """
    lock_mutation(session)
    from datetime import date as dt_date
    from models import Account, User

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    from_acc = session.get(Account, payload.from_account_id)
    to_acc = session.get(Account, payload.to_account_id)
    if not from_acc:
        raise HTTPException(status_code=404, detail="转出账户不存在")
    if not to_acc:
        raise HTTPException(status_code=404, detail="转入账户不存在")
    if not from_acc.is_active or not to_acc.is_active:
        raise HTTPException(status_code=409, detail="转账账户已停用")
    if from_acc.currency != to_acc.currency or payload.currency != from_acc.currency:
        raise HTTPException(status_code=400, detail="跨币种转账需要明确兑换金额")
    if from_acc.id == to_acc.id:
        raise HTTPException(status_code=400, detail="转出和转入账户不能相同")
    if from_acc.family_id != to_acc.family_id:
        raise HTTPException(status_code=400, detail="转出和转入账户必须属于同一家庭")

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_user and current_user.role == "admin")
    if not is_admin:
        if not current_user or from_acc.family_id != current_user.family_id:
            raise HTTPException(status_code=403, detail="无权操作其他家庭的账户进行转账")

        writable_ids = get_user_writable_account_ids(session, current_user, from_acc.family_id)
        if from_acc.id not in writable_ids:
            raise HTTPException(status_code=403, detail=f"您没有权限从账户「{from_acc.name}」转出资金")

    _verify_account_write_permission(session, user_or_ctx, from_acc.id, "转出资金")
    _verify_account_transfer_in_permission(session, user_or_ctx, to_acc.id, "转入资金")

    amt = abs(payload.amount)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="转账金额必须大于 0")

    local_tz = ZoneInfo("Asia/Shanghai")
    txn_date = payload.transacted_at or datetime.now(local_tz).date()
    family_id = from_acc.family_id
    if not family_id:
        raise HTTPException(400, "转账账户必须属于有效家庭")
    if payload.occurred_at:
        occurred_at_dt = payload.occurred_at.astimezone(timezone.utc)
        local_date = get_local_date(occurred_at_dt)
        if payload.transacted_at and payload.transacted_at != local_date:
            raise HTTPException(422, "转账日期与精确时间不一致")
        txn_date = local_date
    elif payload.transacted_at or payload.time:
        try:
            clock = DayTime.fromisoformat(payload.time) if payload.time else DayTime(0)
            if clock.tzinfo is not None:
                raise ValueError("time must be local")
            occurred_at_dt = datetime.combine(txn_date, clock, tzinfo=local_tz).astimezone(timezone.utc)
        except ValueError:
            raise HTTPException(422, "转账时间格式必须为 HH:MM[:SS]")
    else:
        occurred_at_dt = datetime.now(timezone.utc)
    occurred_at_dt = occurred_at_dt.replace(tzinfo=None)

    transfer_desc = payload.narration or payload.name or "内部转账"

    # 1. 创建转出流水（from_account）
    out_txn = Transaction(
        account_id=from_acc.id,
        amount=amt,
        currency=payload.currency,
        narration=transfer_desc,
        transaction_type="transfer",
        transacted_at=txn_date,
        occurred_at=occurred_at_dt,
        notes=payload.notes,
        status="posted",
    )
    session.add(out_txn)

    # 2. 创建转入流水（to_account）
    in_name = transfer_desc if transfer_desc != "内部转账" else f"收到{from_acc.name}转入"
    in_txn = Transaction(
        account_id=to_acc.id,
        amount=amt,
        currency=payload.currency,
        narration=in_name,
        transaction_type="transfer",
        transacted_at=txn_date,
        occurred_at=occurred_at_dt,
        notes=payload.notes,
        status="posted",
    )
    session.add(in_txn)
    session.flush()

    # 3. 创建 transfer 配对记录并回写 transfer_id（单事务原子提交）
    transfer = Transfer(
        family_id=family_id,
        outflow_transaction_id=out_txn.id,
        inflow_transaction_id=in_txn.id,
        amount=amt,
        status="confirmed",
    )
    session.add(transfer)
    session.flush()

    out_txn.transfer_id = transfer.id
    in_txn.transfer_id = transfer.id
    session.add(out_txn)
    session.add(in_txn)
    session.commit()

    logger.info("新建内部转账: %s -> %s 金额 %s", from_acc.name, to_acc.name, amt)
    return {
        "status": "ok",
        "transfer_id": str(transfer.id),
        "outflow_transaction_id": str(out_txn.id),
        "inflow_transaction_id": str(in_txn.id),
        "from_account": from_acc.name,
        "to_account": to_acc.name,
        "amount": str(amt),
    }


@router.get("")
@router.get("/")
def list_transfers(
    status: Optional[str] = Query(None, description="confirmed | pending"),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取所有已配对或待确认的转账记录列表。"""
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    stmt = select(Transfer)
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_user and current_user.role == "admin")
    visible_acc_ids = set()
    if not is_admin:
        if not current_user or not current_user.family_id:
            stmt = stmt.where(False)
        else:
            stmt = stmt.where(Transfer.family_id == current_user.family_id)
            visible_acc_ids = get_user_visible_account_ids(session, current_user, current_user.family_id)

    if status:
        stmt = stmt.where(Transfer.status == status)

    transfers = session.exec(stmt.order_by(desc(Transfer.created_at))).all()

    items = []
    for t in transfers:
        out_txn = session.get(Transaction, t.outflow_transaction_id)
        in_txn = session.get(Transaction, t.inflow_transaction_id)

        # 核心隔离机制：普通成员仅能查看涉及自己有权限访问的账户的转账记录
        if not is_admin:
            out_acc_id = out_txn.account_id if out_txn else None
            in_acc_id = in_txn.account_id if in_txn else None
            if out_acc_id not in visible_acc_ids and in_acc_id not in visible_acc_ids:
                continue

        out_visible = is_admin or (out_txn and out_txn.account_id in visible_acc_ids)
        in_visible = is_admin or (in_txn and in_txn.account_id in visible_acc_ids)

        out_exact = None
        if out_txn and out_visible:
            if out_txn.occurred_at:
                out_exact = serialize_utc_datetime(out_txn.occurred_at)
            elif out_txn.created_at:
                out_exact = serialize_utc_datetime(out_txn.created_at)
            elif out_txn.transacted_at:
                out_exact = f"{out_txn.transacted_at.isoformat()}T00:00:00Z"

        in_exact = None
        if in_txn and in_visible:
            if in_txn.occurred_at:
                in_exact = serialize_utc_datetime(in_txn.occurred_at)
            elif in_txn.created_at:
                in_exact = serialize_utc_datetime(in_txn.created_at)
            elif in_txn.transacted_at:
                in_exact = f"{in_txn.transacted_at.isoformat()}T00:00:00Z"

        # 若其中一端为未授权私密账户，对该端流水详情实施脱敏保护
        outflow_payload = None
        if out_txn:
            if out_visible:
                outflow_payload = {
                    "id": str(out_txn.id),
                    "account_id": str(out_txn.account_id),
                    "amount": str(out_txn.amount),
                    "narration": out_txn.narration,
                    "name": out_txn.narration,
                    "transacted_at": out_txn.transacted_at.isoformat() if out_txn.transacted_at else None,
                    "occurred_at": out_exact,
                }
            else:
                outflow_payload = {
                    "id": None,
                    "account_id": None,
                    "amount": str(out_txn.amount),
                    "narration": "私密账户交易",
                    "name": "私密账户交易",
                    "transacted_at": None,
                    "occurred_at": None,
                }

        inflow_payload = None
        if in_txn:
            if in_visible:
                inflow_payload = {
                    "id": str(in_txn.id),
                    "account_id": str(in_txn.account_id),
                    "amount": str(in_txn.amount),
                    "narration": in_txn.narration,
                    "name": in_txn.narration,
                    "transacted_at": in_txn.transacted_at.isoformat() if in_txn.transacted_at else None,
                    "occurred_at": in_exact,
                }
            else:
                inflow_payload = {
                    "id": None,
                    "account_id": None,
                    "amount": str(in_txn.amount),
                    "narration": "私密账户交易",
                    "name": "私密账户交易",
                    "transacted_at": None,
                    "occurred_at": None,
                }

        items.append({
            "id": str(t.id),
            "amount": str(Decimal(str(t.amount)).quantize(Decimal("0.01"))),
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "outflow": outflow_payload,
            "inflow": inflow_payload,
        })

    return {"transfers": items, "items": items, "count": len(items)}


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
    lock_mutation(session)
    transfer = session.get(Transfer, transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    out_id = transfer.outflow_transaction_id
    in_id = transfer.inflow_transaction_id
    out_txn = session.get(Transaction, out_id)
    in_txn = session.get(Transaction, in_id)
    for txn in (out_txn, in_txn):
        if txn:
            _verify_account_write_permission(session, user_or_ctx, txn.account_id, "解除转账绑定")
            from services.schedules import guard_transaction
            guard_transaction(txn)

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_user and current_user.role == "admin")
    if not is_admin:
        if not current_user or transfer.family_id != current_user.family_id:
            raise HTTPException(status_code=403, detail="无权操作其他家庭的转账记录")
        writable_ids = get_user_writable_account_ids(session, current_user, transfer.family_id)
        out_acc_id = out_txn.account_id if out_txn else None
        in_acc_id = in_txn.account_id if in_txn else None
        if (out_acc_id and out_acc_id not in writable_ids) or (in_acc_id and in_acc_id not in writable_ids):
            raise HTTPException(status_code=403, detail="解除转账绑定需要同时具备转出与转入两端账户的写权限")

    # 1. 恢复交易原始属性并解除绑定
    if out_txn:
        out_txn.transfer_id = None
        out_txn.transaction_type = "expense"
        session.add(out_txn)

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
    """
    人工手动撮合转账对。
    严格校验方向（支出转入收入）、金额绝对值相等且大于0、未绑定其他转账及防驳回黑名单。
    """
    lock_mutation(session)
    out_txn = session.get(Transaction, payload.outflow_transaction_id)
    in_txn = session.get(Transaction, payload.inflow_transaction_id)

    if not out_txn or not in_txn:
        raise HTTPException(status_code=404, detail="One or both transactions not found")
    from services.schedules import guard_transaction
    guard_transaction(out_txn)
    guard_transaction(in_txn)

    if out_txn.account_id == in_txn.account_id:
        raise HTTPException(status_code=400, detail="Cannot transfer within the same account")

    out_acc = session.get(Account, out_txn.account_id)
    in_acc = session.get(Account, in_txn.account_id)
    if not out_acc or not in_acc:
        raise HTTPException(status_code=404, detail="关联账户不存在")

    if out_txn.currency != in_txn.currency:
        raise HTTPException(status_code=400, detail="跨币种流水不能直接配对")
    if out_acc.family_id != in_acc.family_id:
        raise HTTPException(status_code=400, detail="转账双方交易必须属于同一家庭的账户")

    # 1. 交易不可已被配对
    if out_txn.transfer_id is not None or in_txn.transfer_id is not None:
        raise HTTPException(status_code=400, detail="其中一笔或两笔交易已属于其他转账配对")

    # 2. 方向校验：转出方必须是 expense 或 transfer，转入方必须是 income 或 transfer
    from services.transaction_direction import transaction_direction
    if transaction_direction(out_txn, session, out_acc) != "outflow":
        raise HTTPException(status_code=400, detail="转出方交易类型必须为支出或转账")
    if in_txn.transaction_type not in ("income", "transfer") or transaction_direction(in_txn, session, in_acc) != "inflow":
        raise HTTPException(status_code=400, detail="转入方交易类型必须为收入或转账")

    # 3. 金额校验：绝对值必须大于 0 且两侧严格相等
    out_amt = abs(Decimal(str(out_txn.amount)))
    in_amt = abs(Decimal(str(in_txn.amount)))
    if out_amt <= Decimal("0") or in_amt <= Decimal("0"):
        raise HTTPException(status_code=400, detail="转账金额必须大于 0")
    if out_amt.quantize(Decimal("0.01")) != in_amt.quantize(Decimal("0.01")):
        raise HTTPException(status_code=400, detail=f"转出金额 ({out_amt}) 与转入金额 ({in_amt}) 不一致，无法配对")

    # 4. 黑名单校验
    rejected = session.exec(
        select(RejectedTransfer).where(
            RejectedTransfer.outflow_transaction_id == out_txn.id,
            RejectedTransfer.inflow_transaction_id == in_txn.id,
        )
    ).first()
    if rejected:
        raise HTTPException(status_code=400, detail="该转账对已被用户手动驳回并拉黑，无法重新配对")

    # 5. 权限校验
    _verify_account_write_permission(session, user_or_ctx, out_txn.account_id, "配对转账")
    _verify_account_write_permission(session, user_or_ctx, in_txn.account_id, "配对转账")
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_user and current_user.role == "admin")
    if not is_admin:
        if not current_user or out_acc.family_id != current_user.family_id:
            raise HTTPException(status_code=403, detail="无权操作其他家庭的交易进行配对")
        writable_ids = get_user_writable_account_ids(session, current_user, out_acc.family_id)
        if out_acc.id not in writable_ids or in_acc.id not in writable_ids:
            raise HTTPException(status_code=403, detail="您对转出或转入私有账户无写入管理权限")

    transfer = Transfer(
        family_id=out_acc.family_id,
        outflow_transaction_id=out_txn.id,
        inflow_transaction_id=in_txn.id,
        amount=out_amt,
        status="confirmed",
    )
    session.add(transfer)
    session.flush()

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
    from models import Account, User
    from services.stats_engine import get_family_active_account_ids

    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    src_acc = session.get(Account, txn.account_id)
    if not src_acc:
        raise HTTPException(status_code=404, detail="交易关联账户不存在")

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_user and current_user.role == "admin")
    if not is_admin:
        if not current_user or src_acc.family_id != current_user.family_id:
            raise HTTPException(status_code=403, detail="无权查看其他家庭的交易候选对端")
        visible_ids = get_user_visible_account_ids(session, current_user, src_acc.family_id)
        if txn.account_id not in visible_ids:
            raise HTTPException(status_code=403, detail="无权查看该私有账户流水的候选对端")
        family_acc_ids = visible_ids
    else:
        family_acc_ids = get_family_active_account_ids(session, family_id=src_acc.family_id)

    target_amount = abs(txn.amount)
    cutoff_start = txn.transacted_at - timedelta(days=7)
    cutoff_end = txn.transacted_at + timedelta(days=7)

    # 寻找对端
    from services.transaction_direction import transaction_direction
    source_direction = transaction_direction(txn, session, src_acc)
    if txn.transaction_type not in ("expense", "income", "transfer") or source_direction is None:
        raise HTTPException(400, "该流水不支持转账配对")
    is_outflow = source_direction == "outflow"

    stmt = select(Transaction).where(
        Transaction.id != txn.id,
        Transaction.account_id != txn.account_id,
        Transaction.transacted_at >= cutoff_start,
        Transaction.transacted_at <= cutoff_end,
    )
    if not family_acc_ids:
        stmt = stmt.where(False)
    else:
        stmt = stmt.where(Transaction.account_id.in_(family_acc_ids))

    if is_outflow:
        stmt = stmt.where(
            Transaction.transaction_type.in_(("income", "transfer"))
        )
    else:
        stmt = stmt.where(
            Transaction.transaction_type.in_(("expense", "transfer"))
        )

    # 排除已是 confirmed transfer 的
    stmt = stmt.where(Transaction.transfer_id.is_(None))

    accounts = session.exec(select(Account).where(Account.family_id == src_acc.family_id)).all()
    if not is_admin:
        accounts = [a for a in accounts if a.id in family_acc_ids]
    accounts_map = {a.id: a.name for a in accounts}
    accounts_obj_map = {a.id: a for a in accounts}
    users_map = {u.id: (u.display_name or u.username) for u in session.exec(select(User).where(User.family_id == src_acc.family_id)).all()}

    rows = session.exec(stmt).all()

    candidates = []
    for r in rows:
        if r.currency != txn.currency or transaction_direction(r, session, accounts_obj_map.get(r.account_id)) == source_direction:
            continue
        diff = abs(abs(r.amount) - target_amount)
        # 精确或接近同额（误差不超过 0.05 或 5%）
        if diff < Decimal("0.05") or (target_amount > 0 and diff / target_amount < Decimal("0.05")):
            r_occurred_at = None
            if r.occurred_at:
                r_occurred_at = serialize_utc_datetime(r.occurred_at)
            elif r.created_at:
                r_occurred_at = serialize_utc_datetime(r.created_at)
            elif r.transacted_at:
                r_occurred_at = f"{r.transacted_at.isoformat()}T00:00:00Z"

            acc_obj = accounts_obj_map.get(r.account_id)
            c_owner = users_map.get(acc_obj.owner_id) if (acc_obj and acc_obj.owner_id) else None
            c_is_owner = bool(current_user and acc_obj and acc_obj.owner_id == current_user.id)

            candidates.append({
                "id": str(r.id),
                "account_id": str(r.account_id),
                "account_name": accounts_map.get(r.account_id, "外部账户"),
                "owner_name": c_owner,
                "is_owner": c_is_owner,
                "narration": r.narration,
                "name": r.narration,
                "amount": str(r.amount.quantize(Decimal("0.01"))),
                "currency": r.currency,
                "transacted_at": r.transacted_at.isoformat(),
                "occurred_at": r_occurred_at,
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

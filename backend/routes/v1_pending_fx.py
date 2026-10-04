"""Authorized pending-FX queue, retries and bank settlement confirmation."""
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from auth import get_current_user_or_token
from database import get_session
from models import Account, PendingFxTransaction, User
from services.request_validation import CurrencyCode
from services.transaction_lock import lock_mutation

router = APIRouter(prefix="/v1/pending-transactions", tags=["Pending FX"])


def serialize_pending(row, duplicate=False):
    body = row.payload or {}
    return {"id": str(row.id), "account_id": str(row.account_id), "status": row.status,
            "duplicate": duplicate, "narration": body.get("narration"),
            "transaction_type": body.get("transaction_type"), "external_id": row.external_id,
            "transacted_at": body.get("transacted_at") or body.get("date") or (body.get("occurred_at") or "")[:10],
            "original_amount": body.get("original_amount") or body.get("amount"),
            "original_currency": body.get("original_currency") or body.get("currency"),
            "last_error": row.last_error, "attempts": row.attempts,
            "posted_transaction_id": str(row.posted_transaction_id) if row.posted_transaction_id else None,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def pending_for_user(session, principal, row_id, write=False):
    from routes.v1_transactions import _verify_account_read_permission, _verify_account_write_permission
    row = session.get(PendingFxTransaction, row_id)
    if not row:
        raise HTTPException(404, "待入账记录不存在")
    checker = _verify_account_write_permission if write else _verify_account_read_permission
    checker(session, principal, row.account_id, "处理待入账记录" if write else "查看待入账记录")
    return row


@router.get("")
def list_pending(session: Session = Depends(get_session), user_or_ctx: Any = Depends(get_current_user_or_token)):
    from services.stats_engine import get_user_visible_account_ids, get_user_writable_account_ids
    from services.principals import resolve_family_id
    actor = user_or_ctx if isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:") else session.exec(select(User).where(User.username == user_or_ctx)).first()
    family_id = resolve_family_id(session, user_or_ctx)
    visible = get_user_visible_account_ids(session, actor, family_id)
    writable = get_user_writable_account_ids(session, actor, family_id)
    rows = session.exec(select(PendingFxTransaction).where(PendingFxTransaction.account_id.in_(visible),
        PendingFxTransaction.status == "pending_fx").order_by(PendingFxTransaction.created_at).limit(200)).all() if visible else []
    return {"items": [{**serialize_pending(row), "read_only": row.account_id not in writable} for row in rows]}


class SettlementConfirmation(BaseModel):
    settlement_amount: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    settlement_currency: CurrencyCode
    master_settlement_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    master_settlement_currency: Optional[CurrencyCode] = None


def retry_record(session, row, principal, confirmation=None):
    from routes.v1_transactions import TransactionIn, ingest_transaction, _verify_account_write_permission
    lock_mutation(session)
    if row.status != "pending_fx":
        return serialize_pending(row, duplicate=True)
    account = session.get(Account, row.account_id)
    if not account or not account.is_active or account.family_id != row.family_id:
        raise HTTPException(409, "账户状态或家庭归属已改变，请重新核对这条记录")
    _verify_account_write_permission(session, principal, account.id, "完成待换汇入账")
    payload = dict(row.payload)
    if confirmation is not None:
        payload.update(confirmation.model_dump(mode="json", exclude_none=True))
        payload["settlement_source"] = "manual_confirmation"
        row.payload = payload
    data = TransactionIn.model_validate(payload)
    row.attempts += 1
    row.updated_at = datetime.now(timezone.utc)
    row.retry_after = row.updated_at + timedelta(seconds=min(3600, 60 * (2 ** min(row.attempts, 6))))
    result = ingest_transaction(data, session, principal, pending_record=row)
    session.add(row)
    return result


@router.post("/{row_id}/retry")
def retry_pending(row_id: UUID, session: Session = Depends(get_session), user_or_ctx: Any = Depends(get_current_user_or_token)):
    lock_mutation(session)
    row = pending_for_user(session, user_or_ctx, row_id, write=True)
    result = retry_record(session, row, user_or_ctx)
    session.commit()
    return result


@router.post("/{row_id}/confirm")
def confirm_pending(row_id: UUID, payload: SettlementConfirmation,
                    session: Session = Depends(get_session), user_or_ctx: Any = Depends(get_current_user_or_token)):
    lock_mutation(session)
    row = pending_for_user(session, user_or_ctx, row_id, write=True)
    result = retry_record(session, row, user_or_ctx, payload)
    session.commit()
    return result


@router.post("/{row_id}/cancel")
def cancel_pending(row_id: UUID, session: Session = Depends(get_session), user_or_ctx: Any = Depends(get_current_user_or_token)):
    lock_mutation(session)
    row = pending_for_user(session, user_or_ctx, row_id, write=True)
    if row.status == "posted":
        raise HTTPException(409, "已入账记录不能从待换汇队列取消，请在流水中处理")
    row.status = "canceled"
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    return serialize_pending(row)


def retry_due_records(engine, stopped=None):
    """The stored user UUID/service family is rechecked for every automatic retry."""
    with Session(engine) as session:
        ids = session.exec(select(PendingFxTransaction.id).where(
            PendingFxTransaction.status == "pending_fx", PendingFxTransaction.retry_after <= datetime.now(timezone.utc)
        ).order_by(PendingFxTransaction.created_at).limit(10)).all()
    for row_id in ids:
        if stopped is not None and stopped.is_set():
            break
        with Session(engine) as session:
            try:
                lock_mutation(session)
                row = session.get(PendingFxTransaction, row_id)
                if not row or row.status != "pending_fx":
                    continue
                if row.requested_by_service:
                    from services.principals import service_family
                    if service_family(session).id != row.family_id:
                        raise HTTPException(403, "服务家庭绑定已改变")
                    principal = "service:pending-fx"
                else:
                    user = session.get(User, row.requested_by_user_id) if row.requested_by_user_id else None
                    if not user or not user.is_active or user.family_id != row.family_id:
                        raise HTTPException(403, "原操作用户或家庭权限已失效")
                    principal = user.username
                retry_record(session, row, principal)
                session.commit()
            except HTTPException as error:
                session.rollback()
                row = session.get(PendingFxTransaction, row_id)
                if row:
                    row.last_error = str(error.detail)[:500]
                    row.retry_after = datetime.now(timezone.utc) + timedelta(minutes=10)
                    session.add(row)
                    session.commit()


def start_retry_worker(engine):
    stopped = threading.Event()
    def run():
        import logging
        while not stopped.wait(30):
            try:
                retry_due_records(engine, stopped)
            except Exception:
                logging.getLogger(__name__).exception("Pending FX retry failed")
    worker = threading.Thread(target=run, name="pending-fx", daemon=True)
    worker.start()
    return stopped, worker

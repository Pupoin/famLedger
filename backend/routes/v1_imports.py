import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func, desc

from database import get_session
from models import Family, StoredEmail, Transaction, User
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/imports", tags=["Imports"])


def _calculate_fingerprint(
    sender: str, received_at: datetime, subject: str, raw_content: str
) -> str:
    parts = [
        (sender or "").strip().casefold(),
        received_at.isoformat() if received_at else "",
        (subject or "").strip(),
        (raw_content or "").strip()[:5000],  # first 5000 chars of body
    ]
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EmailImportPayload(BaseModel):
    message_id: str = Field(description="Unique email message ID (e.g. Microsoft Graph ID)")
    content_fingerprint: Optional[str] = Field(default=None, description="SHA256 content fingerprint for deduplication")
    mail_kind: str = Field(default="other", description="credit_daily | credit_recent | debit | other")
    subject: str = Field(default="", description="Email subject")
    sender: str = Field(default="", description="Sender email address")
    recipient: Optional[str] = Field(default=None, description="Recipient email address")
    received_at: datetime = Field(description="Email received timestamp")
    raw_html: Optional[str] = Field(default=None, description="Raw HTML email body")
    raw_text: Optional[str] = Field(default=None, description="Plaintext or sanitized body")
    raw_payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Raw JSON message payload from Graph")


class StoredEmailOut(BaseModel):
    id: uuid.UUID
    family_id: uuid.UUID
    message_id: str
    content_fingerprint: str
    mail_kind: str
    subject: str
    sender: str
    recipient: Optional[str]
    received_at: datetime
    status: str
    error_message: Optional[str]
    parsed_count: int
    created_at: datetime


@router.post("/emails")
def import_raw_email(
    payload: EmailImportPayload,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    保存原始邮件到数据库中，并在有新邮件时提供给后续解析流程。
    具备 message_id 与 content_fingerprint 双重幂等去重保护。
    """
    # 获取默认或当前家庭
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    fingerprint = payload.content_fingerprint or _calculate_fingerprint(
        payload.sender, payload.received_at, payload.subject, payload.raw_html or payload.raw_text or ""
    )

    # 1. 检查是否已经存储过
    existing = session.exec(
        select(StoredEmail).where(
            (StoredEmail.message_id == payload.message_id) |
            (StoredEmail.content_fingerprint == fingerprint)
        )
    ).first()

    if existing:
        return {
            "id": str(existing.id),
            "message_id": existing.message_id,
            "status": existing.status,
            "parsed_count": existing.parsed_count,
            "is_new": False,
        }

    # 2. 存储新邮件
    stored = StoredEmail(
        family_id=family.id,
        message_id=payload.message_id,
        content_fingerprint=fingerprint,
        mail_kind=payload.mail_kind,
        subject=payload.subject,
        sender=payload.sender,
        recipient=payload.recipient,
        received_at=payload.received_at,
        raw_html=payload.raw_html,
        raw_text=payload.raw_text,
        raw_payload=payload.raw_payload or {},
        status="pending",
        parsed_count=0,
    )
    session.add(stored)
    session.commit()
    session.refresh(stored)

    logger.info("成功持久化原始邮件: id=%s subject=%s sender=%s", stored.id, stored.subject, stored.sender)

    return {
        "id": str(stored.id),
        "message_id": stored.message_id,
        "status": stored.status,
        "parsed_count": 0,
        "is_new": True,
    }


@router.get("/emails")
def list_stored_emails(
    status: Optional[str] = Query(None, description="pending | parsed | failed | ignored"),
    mail_kind: Optional[str] = Query(None, description="credit_daily | credit_recent | debit | other"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    分页查询已归档的原始账单邮件列表。
    """
    stmt = select(StoredEmail)
    count_stmt = select(func.count(StoredEmail.id))

    if status:
        stmt = stmt.where(StoredEmail.status == status)
        count_stmt = count_stmt.where(StoredEmail.status == status)
    if mail_kind:
        stmt = stmt.where(StoredEmail.mail_kind == mail_kind)
        count_stmt = count_stmt.where(StoredEmail.mail_kind == mail_kind)

    total = session.exec(count_stmt).one()
    emails = session.exec(
        stmt.order_by(desc(StoredEmail.received_at)).offset(offset).limit(limit)
    ).all()

    items = []
    for e in emails:
        items.append({
            "id": str(e.id),
            "message_id": e.message_id,
            "content_fingerprint": e.content_fingerprint,
            "mail_kind": e.mail_kind,
            "subject": e.subject,
            "sender": e.sender,
            "recipient": e.recipient,
            "received_at": e.received_at.isoformat() if e.received_at else None,
            "status": e.status,
            "error_message": e.error_message,
            "parsed_count": e.parsed_count,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/emails/{email_id}")
def get_stored_email(
    email_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取单封原始邮件的完整内容（含 HTML 正文、文本与关联生成的交易流水）。
    """
    email = session.get(StoredEmail, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # 查询该邮件已关联的交易流水
    txns = session.exec(
        select(Transaction).where(Transaction.raw_email_id == email.id)
    ).all()

    txn_list = [
        {
            "id": str(t.id),
            "account_id": str(t.account_id),
            "amount": str(t.amount),
            "currency": t.currency,
            "name": t.name,
            "merchant_name": t.merchant_name,
            "transaction_type": t.transaction_type,
            "transacted_at": t.transacted_at.isoformat() if t.transacted_at else None,
        }
        for t in txns
    ]

    return {
        "id": str(email.id),
        "family_id": str(email.family_id),
        "message_id": email.message_id,
        "content_fingerprint": email.content_fingerprint,
        "mail_kind": email.mail_kind,
        "subject": email.subject,
        "sender": email.sender,
        "recipient": email.recipient,
        "received_at": email.received_at.isoformat() if email.received_at else None,
        "raw_html": email.raw_html,
        "raw_text": email.raw_text,
        "raw_payload": email.raw_payload,
        "status": email.status,
        "error_message": email.error_message,
        "parsed_count": email.parsed_count,
        "parsed_transactions": txn_list,
        "created_at": email.created_at.isoformat() if email.created_at else None,
    }

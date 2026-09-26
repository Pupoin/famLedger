import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func

from database import get_session
from models import Account, AccountShare, Family, User
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/accounts", tags=["Accounts"])


class AccountCreate(BaseModel):
    name: str
    account_type: str = "checking"  # checking | savings | credit_card | investment | loan | other
    currency: str = "CNY"
    institution_name: Optional[str] = None
    balance: Optional[Decimal] = Decimal("0")
    color: Optional[str] = None
    icon: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[str] = None
    currency: Optional[str] = None
    institution_name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    is_archived: Optional[bool] = None


@router.get("")
@router.get("/")
def list_accounts(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取家庭名下所有可用资产与负债账户列表。
    """
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    accounts = session.exec(
        select(Account).where(Account.family_id == family.id)
    ).all()

    from models import Transaction
    import re

    tx_counts = dict(
        session.exec(
            select(Transaction.account_id, func.count(Transaction.id))
            .group_by(Transaction.account_id)
        ).all()
    )

    items = []
    for a in accounts:
        # Extract card mask like 7931 from name "招商银行借记卡 (7931)"
        mask_match = re.search(r"\(([0-9Xx]{4})\)", a.name or "")
        mask = mask_match.group(1) if mask_match else (a.name[-4:] if len(a.name or "") >= 4 else "0000")

        items.append({
            "id": str(a.id),
            "name": a.name,
            "mask": mask,
            "account_type": a.account_type,
            "classification": getattr(a, "classification", "asset"),
            "currency": a.currency,
            "institution_name": a.institution_name or "招商银行",
            "balance": str(a.balance or 0),
            "transaction_count": tx_counts.get(a.id, 0),
            "is_active": getattr(a, "is_active", True),
        })
    return {"accounts": items, "items": items, "count": len(items)}


@router.post("")
@router.post("/")
def create_account(
    data: AccountCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    创建新账户。
    """
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    owner = session.exec(select(User).where(User.family_id == family.id)).first()
    owner_id = owner.id if owner else uuid.uuid4()

    account = Account(
        family_id=family.id,
        owner_id=owner_id,
        name=data.name,
        account_type=data.account_type,
        currency=data.currency,
        institution_name=data.institution_name,
        balance=data.balance or Decimal("0"),
        color=data.color,
        icon=data.icon,
    )
    session.add(account)
    session.commit()
    session.refresh(account)

    return {
        "id": str(account.id),
        "name": account.name,
        "account_type": account.account_type,
        "currency": account.currency,
        "institution_name": account.institution_name,
        "balance": str(account.balance),
    }

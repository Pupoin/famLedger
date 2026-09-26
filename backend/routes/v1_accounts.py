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

    items = []
    for a in accounts:
        items.append({
            "id": str(a.id),
            "name": a.name,
            "account_type": a.account_type,
            "currency": a.currency,
            "institution_name": a.institution_name,
            "balance": str(a.balance),
            "color": a.color,
            "icon": a.icon,
            "is_archived": a.is_archived,
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

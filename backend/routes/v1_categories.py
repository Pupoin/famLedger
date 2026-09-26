import logging
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import Category, Family
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/categories", tags=["Categories"])


class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[uuid.UUID] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    i18n_key: Optional[str] = None


@router.get("")
@router.get("/")
def list_categories(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取交易分类体系。
    """
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    cats = session.exec(
        select(Category).where(Category.family_id == family.id)
    ).all()

    items = []
    for c in cats:
        items.append({
            "id": str(c.id),
            "name": c.name,
            "parent_id": str(c.parent_id) if c.parent_id else None,
            "icon": c.icon,
            "color": c.color,
            "i18n_key": c.i18n_key,
        })
    return {"categories": items, "items": items, "count": len(items)}


@router.post("")
@router.post("/")
async def create_category(
    request: Request,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    创建交易分类（兼容 Sure 嵌套结构 {"category": {"name": ...}} 与直传结构）。
    """
    raw_body = await request.json()
    payload = raw_body.get("category", raw_body)
    data = CategoryCreate(**payload)

    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    cat = Category(
        family_id=family.id,
        name=data.name,
        parent_id=data.parent_id,
        icon=data.icon,
        color=data.color,
        i18n_key=data.i18n_key,
    )
    session.add(cat)
    session.commit()
    session.refresh(cat)

    return {
        "id": str(cat.id),
        "name": cat.name,
        "parent_id": str(cat.parent_id) if cat.parent_id else None,
        "icon": cat.icon,
        "color": cat.color,
    }

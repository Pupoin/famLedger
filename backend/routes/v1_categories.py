import logging
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func

from database import get_session
from models import Category, Family, User
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/categories", tags=["Categories"])


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: Optional[uuid.UUID] = None
    icon: Optional[str] = Field(default=None, max_length=50)
    color: Optional[str] = Field(default=None, max_length=30)
    i18n_key: Optional[str] = Field(default=None, max_length=100)
    category_type: Optional[str] = "expense"  # expense | income


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    parent_id: Optional[uuid.UUID] = None
    icon: Optional[str] = Field(default=None, max_length=50)
    color: Optional[str] = Field(default=None, max_length=30)
    i18n_key: Optional[str] = Field(default=None, max_length=100)
    category_type: Optional[str] = None  # expense | income


def seed_default_categories_for_family(session: Session, family_id: uuid.UUID):
    from services.rules.defaults import initialize_family_rules
    initialize_family_rules(session, family_id)
    return session.exec(select(Category).where(Category.family_id == family_id)).all()


def _resolve_user_family_id(session: Session, user_or_ctx: Any) -> Optional[uuid.UUID]:
    from services.principals import resolve_family_id
    return resolve_family_id(session, user_or_ctx)

def _require_admin_or_owner(session: Session, user_or_ctx: Any, action: str = "操作分类"):
    """权限校验：仅系统超级管理员 (admin) 或家庭创建者 (owner) 允许操作分类创建、修改、删除与全局配置。"""
    from models import User
    if isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"):
        return
    curr_user = None
    if isinstance(user_or_ctx, str):
        curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first()
    elif isinstance(user_or_ctx, User):
        curr_user = user_or_ctx
    if not curr_user:
        raise HTTPException(status_code=401, detail="用户未认证")
    if curr_user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail=f"权限不足：仅家庭管理员(owner)或系统管理员可{action}")


@router.get("")
@router.get("/")
def list_categories(
    category_type: Optional[str] = Query(None, description="分类类型筛选: expense, income, all"),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取交易分类体系及每个分类关联的交易计数。
    支持按 category_type (expense | income | all) 进行分类视图隔离。
    """
    from models import Account, Transaction

    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        return {"categories": [], "items": [], "count": 0}

    # 1. 查询数据库中已存在的分类
    query = select(Category).where(Category.family_id == family_id)
    if category_type and category_type.strip() not in ("all", "ALL", ""):
        query = query.where(Category.category_type == category_type.strip().lower())
    cats = session.exec(query).all()
    existing_by_name = {c.name: c for c in cats}

    # 预统计当前用户可见账户每个分类的交易数量
    from services.stats_engine import get_user_visible_account_ids
    user_db = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:") else None
    visible_accs = get_user_visible_account_ids(session, user_db, family_id=family_id)
    if visible_accs:
        # 数据库原生 GROUP BY 聚合，秒级完成频次汇总，零内存瓶颈
        cat_counts = session.exec(
            select(Transaction.category_id, func.count(Transaction.id))
            .where(
                Transaction.account_id.in_(visible_accs),
                Transaction.category_id.is_not(None)
            )
            .group_by(Transaction.category_id)
        ).all()
        count_map = dict(cat_counts)
    else:
        count_map = {}

    items = []
    seen_names = set()
    for c in cats:
        seen_names.add(c.name)
        items.append({
            "id": str(c.id),
            "name": c.name,
            "parent_id": str(c.parent_id) if c.parent_id else None,
            "icon": c.icon or "📦",
            "color": c.color or "#6366f1",
            "category_type": getattr(c, "category_type", "expense") or "expense",
            "i18n_key": c.i18n_key,
            "transaction_count": count_map.get(c.id, 0),
        })

    # 按关联交易数量降序排列，高频分类优先展示
    items.sort(key=lambda x: x["transaction_count"], reverse=True)

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
    支持 category_type ("expense" | "income")。
    """
    _require_admin_or_owner(session, user_or_ctx, "创建分类")
    from services.request_validation import parse_body
    data = await parse_body(request, CategoryCreate, "category")

    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        raise HTTPException(status_code=400, detail="您尚未加入家庭组，无法创建自定义分类")

    cat_type = (data.category_type or "expense").strip().lower()
    if cat_type not in ("expense", "income"):
        cat_type = "expense"

    if data.parent_id:
        parent_cat = session.get(Category, data.parent_id)
        if not parent_cat or parent_cat.family_id != family_id:
            raise HTTPException(status_code=400, detail="父分类不存在或属于其他家庭")

    cat = Category(
        family_id=family_id,
        name=data.name.strip(),
        parent_id=data.parent_id,
        icon=data.icon or "📦",
        color=data.color or "#6366f1",
        category_type=cat_type,
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
        "category_type": cat.category_type,
        "transaction_count": 0,
    }


@router.put("/{category_id}")
@router.patch("/{category_id}")
async def update_category(
    category_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    修改指定分类属性（名称、图标、颜色、分类类型、父级分类）。
    严格校验父分类归属与循环继承关系。
    """
    _require_admin_or_owner(session, user_or_ctx, "修改分类")
    family_id = _resolve_user_family_id(session, user_or_ctx)
    from models import User
    u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    is_admin = (u and u.role == "admin") or (isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"))
    cat = session.get(Category, category_id)
    if not cat or (not is_admin and cat.family_id != family_id):
        raise HTTPException(status_code=404, detail="分类不存在")

    from services.request_validation import parse_body
    data = await parse_body(request, CategoryUpdate, "category")

    if data.name is not None:
        cat.name = data.name.strip()
    if data.icon is not None:
        cat.icon = data.icon
    if data.color is not None:
        cat.color = data.color
    if "parent_id" in data.model_fields_set:
        if data.parent_id == category_id:
            raise HTTPException(status_code=400, detail="不能将父分类设置为自身")
        parent_cat = session.get(Category, data.parent_id) if data.parent_id else None
        if data.parent_id and (not parent_cat or parent_cat.family_id != cat.family_id):
            raise HTTPException(status_code=400, detail="父分类不存在或属于其他家庭")

        # 环路检测：沿父级链向上查找，确保不包含自身
        curr = parent_cat
        visited = set()
        while curr:
            if curr.id == category_id or curr.id in visited:
                raise HTTPException(status_code=400, detail="检测到循环分类引用，不能将子分类设置为自身的父级")
            visited.add(curr.id)
            curr = session.get(Category, curr.parent_id) if curr.parent_id else None

        cat.parent_id = data.parent_id
    if data.category_type is not None:
        c_type = data.category_type.strip().lower()
        if c_type in ("expense", "income"):
            cat.category_type = c_type

    session.add(cat)
    session.commit()
    session.refresh(cat)

    return {
        "id": str(cat.id),
        "name": cat.name,
        "parent_id": str(cat.parent_id) if cat.parent_id else None,
        "icon": cat.icon,
        "color": cat.color,
        "category_type": cat.category_type,
    }


@router.delete("/{category_id}")
def delete_category(
    category_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    删除指定分类，并将关联该分类的交易 category_id 置为 None。
    仅管理员或家庭 Owner 允许操作。
    """
    _require_admin_or_owner(session, user_or_ctx)
    family_id = _resolve_user_family_id(session, user_or_ctx)
    from models import User
    u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    is_admin = (u and u.role == "admin") or (isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"))
    cat = session.get(Category, category_id)
    if not cat or (not is_admin and cat.family_id != family_id):
        raise HTTPException(status_code=404, detail="分类不存在")

    # 1. 解除子分类循环关联
    sub_cats = session.exec(select(Category).where(Category.parent_id == category_id)).all()
    for sc in sub_cats:
        sc.parent_id = None
        session.add(sc)

    # 2. 解除交易拆分项外键
    from models import TransactionSplit, Transaction
    for sp in session.exec(select(TransactionSplit).where(TransactionSplit.category_id == category_id)).all():
        sp.category_id = None
        session.add(sp)

    # 3. 解除主交易外键
    linked_txns = session.exec(select(Transaction).where(Transaction.category_id == category_id)).all()
    cleaned_count = len(linked_txns)
    for txn in linked_txns:
        txn.category_id = None
        session.add(txn)

    session.delete(cat)
    session.commit()
    return {"ok": True, "message": f"分类 '{cat.name}' 已删除，{cleaned_count} 笔相关交易已转为未分类"}

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


# 系统官方标准分类母版（单一事实来源，解耦具体人员与特定账号）
CANONICAL_CATEGORIES_TEMPLATE = [
    {"name": "餐饮美食", "icon": "🍴", "color": "#8b5cf6", "category_type": "expense", "kws": ["餐饮", "烧烤", "拉扎斯", "饿了么", "食欲主义", "鑫牛", "酒家", "小馆", "美食", "咖啡", "星巴克", "麦当劳", "肯德基", "厨房", "友宝", "外卖", "火锅", "面馆"]},
    {"name": "超市便利", "icon": "🛒", "color": "#10b981", "category_type": "expense", "kws": ["超市", "生鲜", "好蔬果", "物美", "便利", "果蔬", "买菜", "沃尔玛", "山姆", "全家", "罗森"]},
    {"name": "生活缴费", "icon": "⚡", "color": "#ef4444", "category_type": "expense", "kws": ["自来水", "燃气", "供暖", "电费", "电网", "物业", "移动", "联通", "电信", "水务", "缴费"]},
    {"name": "交通出行", "icon": "🚗", "color": "#06b6d4", "category_type": "expense", "kws": ["高德打车", "滴滴", "地铁", "公交", "铁路", "12306", "打车", "加油", "停车", "出行", "中石化", "中石油"]},
    {"name": "购物消费", "icon": "🛍️", "color": "#eab308", "category_type": "expense", "kws": ["京东", "拼多多", "淘宝", "天猫", "环胜电子", "虞唯", "宽达", "商贸", "商行", "数码", "服饰", "唯品会"]},
    {"name": "人情往来", "icon": "🤝", "color": "#0ea5e9", "category_type": "expense", "kws": ["微信红包", "红包", "人情", "随礼", "份子钱", "礼金"]},
    {"name": "其他", "icon": "🍪", "color": "#f97316", "category_type": "expense", "kws": []},
    # 默认收入分类
    {"name": "工资薪酬", "icon": "💰", "color": "#10b981", "category_type": "income", "kws": ["工资", "薪资", "薪水", "薪酬", "收入", "转账工资"]},
    {"name": "理财收益", "icon": "📈", "color": "#06b6d4", "category_type": "income", "kws": ["理财", "基金", "利息", "投资", "收益", "分红"]},
    {"name": "奖金补贴", "icon": "🧧", "color": "#f59e0b", "category_type": "income", "kws": ["奖金", "年终奖", "补贴", "津贴"]},
    {"name": "兼职副业", "icon": "💼", "color": "#8b5cf6", "category_type": "income", "kws": ["兼职", "稿费", "劳务报酬", "外快"]},
    {"name": "其他收入", "icon": "🪙", "color": "#64748b", "category_type": "income", "kws": []},
]

# 保持老命名兼容
DEFAULT_TRANSACTION_CATEGORIES = CANONICAL_CATEGORIES_TEMPLATE


def get_template_categories(session: Optional[Session] = None) -> list[dict]:
    """获取系统标准分类模板（完全解耦人名，以官方 Canonical Template 为单一事实来源）。"""
    return CANONICAL_CATEGORIES_TEMPLATE


def init_family_canonical_categories(session: Session, family_id: uuid.UUID) -> list[Category]:
    """
    生命周期钩子：为新创建或空的家庭组显式初始化官方标准分类体系。
    """
    if not family_id:
        return []
    existing_count = session.exec(
        select(func.count(Category.id)).where(Category.family_id == family_id)
    ).one()
    if existing_count > 0:
        return session.exec(select(Category).where(Category.family_id == family_id)).all()

    new_cats = []
    for tmpl in CANONICAL_CATEGORIES_TEMPLATE:
        cat = Category(
            family_id=family_id,
            name=tmpl["name"],
            icon=tmpl.get("icon") or "📦",
            color=tmpl.get("color") or ("#10b981" if tmpl.get("category_type") == "income" else "#8b5cf6"),
            category_type=tmpl.get("category_type", "expense"),
            i18n_key=tmpl.get("i18n_key"),
        )
        session.add(cat)
        new_cats.append(cat)
    session.flush()
    for cat in new_cats:
        session.refresh(cat)
    return new_cats


# 保持原函数名兼容
seed_default_categories_for_family = init_family_canonical_categories


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
        preset_items = []
        templates = get_template_categories(session)
        for dc in templates:
            if category_type and category_type != "all" and dc["category_type"] != category_type:
                continue
            preset_id = dc.get("id") or str(uuid.uuid5(uuid.NAMESPACE_DNS, f"preset_category_{dc['name']}"))
            preset_items.append({
                "id": preset_id,
                "name": dc["name"],
                "icon": dc["icon"],
                "color": dc["color"],
                "category_type": dc["category_type"],
                "transaction_count": 0,
            })
        return {"categories": preset_items, "items": preset_items, "count": len(preset_items)}

    # 若当前家庭分类总数仍为 0（空家庭/新注册用户/空账户），自动为该家庭持久化初始化 Qq 的默认支出/收入分类
    total_family_cats = session.exec(
        select(func.count(Category.id)).where(Category.family_id == family_id)
    ).one()
    if total_family_cats == 0:
        seed_default_categories_for_family(session, family_id)
        session.commit()

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

    # 若模板基础分类尚未持久化，在内存中动态补充展示
    for dc in get_template_categories(session):
        if dc["name"] not in seen_names:
            if category_type and category_type != "all" and dc["category_type"] != category_type:
                continue
            preset_id = dc.get("id") or str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{family_id}_{dc['name']}"))
            items.append({
                "id": preset_id,
                "name": dc["name"],
                "parent_id": None,
                "icon": dc["icon"],
                "color": dc["color"],
                "category_type": dc["category_type"],
                "i18n_key": None,
                "transaction_count": 0,
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

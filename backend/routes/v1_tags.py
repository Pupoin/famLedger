import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from database import get_session
from models import Family, Tag, Transaction, User
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/tags", tags=["Tags"])


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: Optional[str] = "#71717a"


class TagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    color: Optional[str] = Field(default=None, max_length=30)


def _resolve_user_family_id(session: Session, user_or_ctx: Any) -> Optional[uuid.UUID]:
    from services.principals import resolve_family_id
    return resolve_family_id(session, user_or_ctx)

@router.get("")
@router.get("/")
def list_tags(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取当前家庭定义的所有交易标签，并自动同步交易流水中已使用的新标签与频次统计。
    """
    from models import Account
    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        return {"tags": []}

    # 1. 查询数据库中已持久化的 Tag 实体
    persisted_tags = session.exec(
        select(Tag).where(Tag.family_id == family_id, Tag.is_archived == False)
    ).all()
    persisted_map = {t.name: t for t in persisted_tags}

    # 2. 扫描属于当前用户有权查阅账户的交易中的 tags 使用频次
    from services.stats_engine import get_user_visible_account_ids
    curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    visible_acc_ids = get_user_visible_account_ids(session, curr_user, family_id=family_id)

    if visible_acc_ids:
        all_txns_tags = session.exec(
            select(Transaction.tags).where(Transaction.account_id.in_(visible_acc_ids))
        ).all()
    else:
        all_txns_tags = []
    from services.tags import tag_resolver
    resolve = tag_resolver(session, family_id)
    tag_counter = Counter()
    for tag_list in all_txns_tags:
        if tag_list and isinstance(tag_list, list):
            for tg in resolve(tag_list):
                if tg and isinstance(tg, str):
                    cleaned = tg.strip()
                    if cleaned:
                        tag_counter[cleaned] += 1

    # 3. 排序输出（已持久化标签 + 流水中动态统计的新标签，GET 只读接口绝不隐式写入数据库）
    items = []
    seen_names = set()
    for name, tag_obj in persisted_map.items():
        seen_names.add(name)
        items.append({
            "id": str(tag_obj.id),
            "name": tag_obj.name,
            "color": tag_obj.color or "#71717a",
            "transaction_count": tag_counter.get(name, 0),
            "created_at": tag_obj.created_at.isoformat() if hasattr(tag_obj.created_at, "isoformat") else str(tag_obj.created_at),
        })

    for tag_name, cnt in tag_counter.items():
        if tag_name not in seen_names:
            items.append({
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{family_id}_{tag_name}")),
                "name": tag_name,
                "color": "#71717a",
                "transaction_count": cnt,
                "created_at": None,
            })

    items.sort(key=lambda x: (-x["transaction_count"], x["name"]))
    return {"tags": items, "items": items, "count": len(items)}


@router.post("")
@router.post("/")
def create_tag(
    data: TagCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    新建交易标签。仅限家庭组管理员或系统管理员操作。
    """
    cleaned_name = data.name.strip()
    if not cleaned_name:
        raise HTTPException(status_code=400, detail="标签名称不能为空")

    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        raise HTTPException(status_code=400, detail="您尚未加入或创建任何家庭，无法创建标签")

    from models import User
    curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    is_admin = curr_user and curr_user.role == "admin"
    is_owner = curr_user and curr_user.role == "owner" and curr_user.family_id == family_id
    if not (is_admin or is_owner or (isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"))):
        raise HTTPException(status_code=403, detail="仅系统管理员或家庭组管理员有权创建新标签")

    existing = next((tag for tag in session.exec(select(Tag).where(Tag.family_id == family_id)).all()
                     if cleaned_name == tag.name or cleaned_name in (tag.aliases or [])), None)
    if existing:
        if existing.is_archived:
            existing.is_archived = False
            session.add(existing)
            session.commit()
        return {
            "id": str(existing.id),
            "name": existing.name,
            "color": existing.color,
            "transaction_count": 0,
        }

    tag = Tag(
        family_id=family_id,
        name=cleaned_name,
        color=data.color or "#71717a",
    )
    session.add(tag)
    session.commit()
    session.refresh(tag)

    return {
        "id": str(tag.id),
        "name": tag.name,
        "color": tag.color,
        "transaction_count": 0,
    }


@router.put("/{tag_id}")
@router.patch("/{tag_id}")
def update_tag(
    tag_id: uuid.UUID,
    data: TagUpdate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    更新标签名称或颜色。当修改名称时，自动级联更新所有交易历史中的标签。
    """
    from models import Account, User
    from services.stats_engine import get_user_writable_account_ids
    family_id = _resolve_user_family_id(session, user_or_ctx)
    curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    is_admin = (curr_user and curr_user.role == "admin") or (isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"))
    is_owner = curr_user and curr_user.role == "owner" and curr_user.family_id == family_id
    if not (is_admin or is_owner):
        raise HTTPException(status_code=403, detail="仅系统管理员或家庭组管理员有权编辑标签")

    tag = session.get(Tag, tag_id)
    if not tag or tag.is_archived or (not is_admin and tag.family_id != family_id):
        raise HTTPException(status_code=404, detail="标签不存在")

    old_name = tag.name
    new_name = data.name.strip() if data.name else None

    if new_name and new_name != old_name:
        others = session.exec(select(Tag).where(Tag.family_id == tag.family_id, Tag.id != tag.id)).all()
        if any(new_name in [other.name, *(other.aliases or [])] for other in others):
            raise HTTPException(409, "该标签名称已被使用")
        tag.aliases = list(dict.fromkeys([*(tag.aliases or []), old_name]))
        tag.name = new_name
        # 仅级联更新当前用户有写权限的账户流水
        writable_accs = get_user_writable_account_ids(session, curr_user, family_id=family_id)
        if writable_accs:
            txns = session.exec(
                select(Transaction).where(Transaction.account_id.in_(writable_accs))
            ).all()
            for txn in txns:
                if txn.tags and isinstance(txn.tags, list) and old_name in txn.tags:
                    txn.tags = [new_name if t == old_name else t for t in txn.tags]
                    session.add(txn)

    if data.color is not None:
        tag.color = data.color

    session.add(tag)
    session.commit()
    session.refresh(tag)

    return {
        "id": str(tag.id),
        "name": tag.name,
        "color": tag.color,
    }


@router.delete("/{tag_id}")
def delete_tag(
    tag_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    删除标签，并从当前家庭具备写权限的交易中移除该标签。
    """
    from models import Account, User
    from services.stats_engine import get_user_writable_account_ids
    family_id = _resolve_user_family_id(session, user_or_ctx)
    curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    is_admin = (curr_user and curr_user.role == "admin") or (isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"))
    is_owner = curr_user and curr_user.role == "owner" and curr_user.family_id == family_id
    if not (is_admin or is_owner):
        raise HTTPException(status_code=403, detail="仅系统管理员或家庭组管理员有权删除标签")

    tag = session.get(Tag, tag_id)
    if not tag or tag.is_archived or (not is_admin and tag.family_id != family_id):
        raise HTTPException(status_code=404, detail="标签不存在")

    tag_name = tag.name
    # 仅从具备写权限的关联交易中移除该标签
    writable_accs = get_user_writable_account_ids(session, curr_user, family_id=family_id)
    cleaned_count = 0
    if writable_accs:
        txns = session.exec(
            select(Transaction).where(Transaction.account_id.in_(writable_accs))
        ).all()
        for txn in txns:
            if txn.tags and isinstance(txn.tags, list) and tag_name in txn.tags:
                txn.tags = [t for t in txn.tags if t != tag_name]
                session.add(txn)
                cleaned_count += 1

    tag.is_archived = True
    session.add(tag)
    session.commit()

    return {"ok": True, "message": f"标签 '{tag_name}' 已删除，从 {cleaned_count} 笔交易中解绑"}

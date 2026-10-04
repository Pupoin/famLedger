import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func, or_
from sqlalchemy import not_

from database import get_session
from models import (
    Family, User, Account, AccountShare, Transaction, UserSession,
    Category, Tag, Transfer, RejectedTransfer, RefundAllocation,
    Rule, Loan, PersonalDebt, Valuation, TransactionSplit, OIDCIdentity, UserPreference, ApiKey,
    FamilyInvitation, FamilyBudget
)
from auth import get_current_user_or_token, hash_password, _check_password, _SAFE_USERNAME_RE
from services.tenant_migration import migrate_user_to_family

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/family", tags=["Family"])



class FamilyRenameRequest(BaseModel):
    name: str = Field(..., description="新的家庭组名称")


class FamilyCreateRequest(BaseModel):
    name: str = Field(..., description="新家庭组名称")
    currency: Optional[str] = Field("CNY", description="家庭默认货币")


def _resolve_family_user(session: Session, user_or_ctx: Any) -> Optional[User]:
    if isinstance(user_or_ctx, str):
        if user_or_ctx.startswith("service:"):
            return session.exec(select(User).where(User.role == "admin")).first() or session.exec(select(User)).first()
        return session.exec(select(User).where(User.username == user_or_ctx)).first()
    return None


@router.get("")
@router.get("/")
@router.get("/current")
def get_current_family(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取当前用户所在的家庭组详情与成员列表。
    """
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    current_user = _resolve_family_user(session, user_or_ctx)

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    family = session.get(Family, current_user.family_id) if current_user.family_id else None
    if not family:
        return {
            "id": None,
            "name": "未加入家庭组",
            "currency": "CNY",
            "created_at": None,
            "role": "none",
            "role_label": "系统管理员" if current_user.role == "admin" else "独立用户 (未加入家庭)",
            "is_solo": True,
            "is_owner": False,
            "can_dissolve": False,
            "is_super_admin": current_user.role == "admin",
            "is_family_admin": False,
            "is_member": False,
            "accounts_count": 0,
            "members": [],
        }

    # 查询该家庭组下所有成员
    members = session.exec(select(User).where(User.family_id == family.id)).all()
    accounts_count = session.exec(
        select(func.count(Account.id)).where(Account.family_id == family.id)
    ).one()

    # 判定是否为单人独立空间（解散后过渡态或私有空间）
    is_solo = bool(getattr(family, "is_solo", False) or (family.name.endswith("的个人空间") and len(members) <= 1))

    role = current_user.role or "member"
    is_super_admin = role == "admin"
    is_family_admin = (role == "owner" or is_super_admin) and not is_solo

    def get_role_label(r):
        if r == "admin":
            return "系统管理员"
        if r == "owner":
            return "家庭组管理员"
        return "家庭成员"

    other_admins_count = len([m for m in members if m.id != current_user.id and (m.role or "member") in ("owner", "admin")])
    can_leave = not is_solo and not (is_family_admin and len(members) > 1 and other_admins_count == 0)

    return {
        "id": str(family.id),
        "name": family.name,
        "currency": family.currency,
        "created_at": family.created_at.isoformat() if family.created_at else None,
        "role": role if not is_solo else "none",
        "role_label": "系统管理员" if is_super_admin else ("个人独立空间" if is_solo else get_role_label(role)),
        "is_solo": is_solo,
        "kind": getattr(family, "kind", "personal" if is_solo else "collaborative"),
        "status": getattr(family, "status", "active"),
        "is_owner": is_family_admin,
        "can_dissolve": not is_solo and is_family_admin and family.status == "active",
        "can_leave": can_leave,
        "can_invite": not is_solo and is_family_admin,
        "is_super_admin": is_super_admin,
        "is_family_admin": is_family_admin,
        "other_admins_count": other_admins_count,
        "is_member": not is_solo,
        "accounts_count": accounts_count,
        # 单人独立模式下成员列表置空，明确提示无家庭协作成员
        "members": [] if is_solo else [
            {
                "id": str(m.id),
                "username": m.username,
                "display_name": m.display_name or m.username,
                "role": m.role or "member",
                "role_label": get_role_label(m.role),
                "email": m.email,
                "is_current_user": m.id == current_user.id,
            }
            for m in members
        ],
    }


@router.patch("/rename")
def rename_family(
    req: FamilyRenameRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    修改当前家庭组名称。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="仅家庭组管理者或系统管理员有权修改家庭名称")

    new_name = req.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="名称不能为空")

    family = session.get(Family, current_user.family_id)
    if not family:
        raise HTTPException(status_code=404, detail="家庭组不存在")

    family.name = new_name
    session.add(family)
    session.commit()
    session.refresh(family)

    return {
        "status": "ok",
        "message": "家庭组名称修改成功",
        "family": {
            "id": str(family.id),
            "name": family.name,
        },
    }


@router.get("/list")
def list_available_families(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取家庭组信息。防全系统租户枚举：普通成员仅能查看自身家庭；系统管理员可查看全量。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")

    is_admin = current_user.role == "admin" or (isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"))
    if is_admin:
        query = select(Family).where(
            Family.is_solo == False,
            not_(Family.name.like("%的个人空间")),
        )
        if current_user.family_id:
            query = query.where(Family.id != current_user.family_id)
        families = session.exec(query).all()
    else:
        # 普通用户防租户枚举，且绝不把自身已有家庭或个人空间推荐为“待加入家庭”
        families = []

    res = []
    for f in families:
        m_count = session.exec(
            select(func.count(User.id)).where(User.family_id == f.id)
        ).one()
        res.append({
            "id": str(f.id),
            "name": f.name,
            "currency": f.currency,
            "kind": f.kind,
            "status": f.status,
            "members_count": m_count,
        })
    return {"families": res}


@router.post("/create")
def create_family(
    req: FamilyCreateRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    显式创建新的家庭组，并将当前用户切换为该家庭组的 owner。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    from services.membership import ensure_can_leave
    ensure_can_leave(session, current_user)

    target_name = req.name.strip()
    if not target_name:
        raise HTTPException(status_code=400, detail="家庭组名称不能为空")

    # 检查是否已有同名家庭组
    existing = session.exec(
        select(Family).where(func.lower(Family.name) == target_name.lower())
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"已存在同名家庭组「{existing.name}」，请联系该家庭管理员发送邀请或更换名称")

    from routes.v1_categories import seed_default_categories_for_family

    new_family = Family(
        name=target_name,
        currency=req.currency or "CNY",
        kind="collaborative",
        status="active",
        is_solo=False,
    )
    session.add(new_family)
    session.flush()

    # 初始化新家庭的标准分类体系
    seed_default_categories_for_family(session, new_family.id)

    # 迁移当前用户及其名下账户、借贷与流水至新家庭组
    migrate_user_to_family(session, current_user, new_family.id, role="owner")

    session.commit()

    logger.info(f"User {current_user.username} created new family {new_family.name} ({new_family.id})")

    return {
        "status": "ok",
        "message": f"成功创建家庭组「{new_family.name}」",
        "family": {
            "id": str(new_family.id),
            "name": new_family.name,
            "currency": new_family.currency,
        },
    }


@router.delete("/current")
@router.delete("/{family_id}")
def delete_family(
    family_id: Optional[str] = None,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    解散协作家庭组。仅限家庭组所有者(owner)操作。
    执行停止协作并归档（status="dissolved"）：
    1. 杜绝物理删除，保留 FamilyBudget、历史规则及配置归档，零外键异常；
    2. 为每位成员复用或创建个人独立空间（kind="personal"），名下账户、流水与个人借贷（PersonalDebt）完整保留并迁移；
    3. 取消该家庭下所有未决的 pending 邀请。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    target_family_id = current_user.family_id
    if family_id and family_id != "current":
        try:
            target_family_id = uuid.UUID(family_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的家庭组 ID")

    family = session.get(Family, target_family_id)
    if not family:
        raise HTTPException(status_code=404, detail="家庭组不存在")

    is_super = current_user.role == "admin"
    is_fam_owner = (current_user.family_id == family.id and current_user.role == "owner")

    if not (is_super or is_fam_owner):
        raise HTTPException(status_code=403, detail="仅系统管理员或家庭组管理员有权解散家庭组")

    # 查询该家庭组下所有成员
    members = session.exec(select(User).where(User.family_id == family.id)).all()

    # 检查是否已经是个人独立空间或已解散归档
    is_personal_space = (
        getattr(family, "kind", "collaborative") == "personal"
        or getattr(family, "is_solo", False)
        or (family.name.endswith("的个人空间") and len(members) <= 1)
    )
    if is_personal_space:
        raise HTTPException(status_code=400, detail="当前处于个人独立空间，无法再次解散")

    if getattr(family, "status", "active") == "dissolved":
        raise HTTPException(status_code=400, detail="该家庭组已处于解散归档状态")

    member_ids = [m.id for m in members]

    # 检查是否有未指定明确归属成员的公用账户（防止公用资产在解散中无主丢失）
    unowned_accounts = session.exec(
        select(Account).where(
            Account.family_id == family.id,
            or_(Account.owner_id == None, ~Account.owner_id.in_(member_ids)),
        )
    ).all()
    if unowned_accounts:
        acc_names = ", ".join([a.name for a in unowned_accounts[:3]])
        raise HTTPException(
            status_code=400,
            detail=f"解散被拦截：家庭内存在未明确归属特定成员的公用账户（{acc_names}等）。请先在账户设置中指定账户拥有者后再解散。",
        )

    from routes.v1_categories import seed_default_categories_for_family

    now_utc = datetime.now(timezone.utc)

    # 1. 迁移每个成员至其专属个人空间
    for m in members:
        # 查找该成员是否已有可复用的活动个人空间
        solo_family = session.exec(
            select(Family).where(
                Family.kind == "personal",
                Family.personal_owner_user_id == m.id,
                Family.status == "active",
            )
        ).first()

        if not solo_family:
            solo_family = Family(
                name=f"{m.display_name or m.username}的个人空间",
                currency=family.currency or "CNY",
                kind="personal",
                status="active",
                personal_owner_user_id=m.id,
                is_solo=True,
            )
            session.add(solo_family)
            session.flush()
            session.refresh(solo_family)
            # 初始化个人空间分类体系
            seed_default_categories_for_family(session, solo_family.id)

        # 统一迁移该成员名下所有账户、借贷及流水映射
        migrate_user_to_family(session, m, solo_family.id, role="owner", dissolving=True)

    # 2. 取消该家庭下所有未决的邀请记录
    pending_invites = session.exec(
        select(FamilyInvitation).where(
            FamilyInvitation.family_id == family.id,
            FamilyInvitation.status == "pending",
        )
    ).all()
    for inv in pending_invites:
        inv.status = "canceled"
        inv.cancel_reason = "家庭组已解散"
        inv.processed_at = now_utc
        session.add(inv)

    # 3. 将原家庭标记为已解散归档（保留配置、预算与历史数据，绝对不物理删除）
    family.status = "dissolved"
    family.dissolved_at = now_utc
    family.dissolved_by_user_id = current_user.id
    session.add(family)
    session.commit()

    logger.info(f"User {current_user.username} successfully dissolved family {family.name} ({family.id}) to archive.")

    return {
        "status": "ok",
        "message": f"家庭组「{family.name}」已成功解散，所有成员已平稳恢复至个人独立空间，账户与历史账务完整保留。",
    }


@router.post("/leave")
def leave_family(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    用户主动退出当前家庭组。
    退出后，为其分配或复用专属个人独立空间（kind='personal', is_solo=True），
    其名下所有账户、流水、个人债务无损迁移到个人独立空间中。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if not current_user.family_id:
        raise HTTPException(status_code=400, detail="您当前未加入任何家庭组")

    curr_fam = session.get(Family, current_user.family_id)
    if not curr_fam:
        raise HTTPException(status_code=400, detail="未找到当前家庭组信息")

    is_personal_space = (
        getattr(curr_fam, "kind", "collaborative") == "personal"
        or getattr(curr_fam, "is_solo", False)
        or (curr_fam.name.endswith("的个人空间") and getattr(curr_fam, "personal_owner_user_id", None) == current_user.id)
    )
    if is_personal_space:
        raise HTTPException(status_code=400, detail="您当前处于个人独立空间，无需退出家庭组")

    # 查询当前家庭成员数与除当前用户外的其他管理员/拥有者数量
    members_count = session.exec(
        select(func.count(User.id)).where(User.family_id == curr_fam.id)
    ).one()

    other_admins_count = session.exec(
        select(func.count(User.id)).where(
            User.family_id == curr_fam.id,
            User.id != current_user.id,
            User.role.in_(["owner", "admin"]),
        )
    ).one()

    # 仅当当前用户是管理员/拥有者，且家庭内【没有其他管理员】且还有其他普通成员时，才阻止直接退出
    if current_user.role in ("owner", "admin") and members_count > 1 and other_admins_count == 0:
        raise HTTPException(
            status_code=400,
            detail="您是当前家庭组内唯一的管理员。为避免家庭账本失控，请先在成员列表中将其他成员设为管理员，或直接解散家庭组后再退出。",
        )

    # 查找或创建该用户的个人独立空间
    solo_family = session.exec(
        select(Family).where(
            Family.kind == "personal",
            Family.personal_owner_user_id == current_user.id,
            Family.status == "active",
        )
    ).first()

    display = current_user.display_name or current_user.username
    user_pref = session.exec(
        select(UserPreference).where(UserPreference.username == current_user.username)
    ).first()
    target_currency = (user_pref.currency if user_pref and user_pref.currency else None) or curr_fam.currency or "CNY"

    if not solo_family:
        solo_family = Family(
            name=f"{display}的个人空间",
            currency=target_currency,
            kind="personal",
            status="active",
            personal_owner_user_id=current_user.id,
            is_solo=True,
        )
        session.add(solo_family)
        session.flush()
        session.refresh(solo_family)
        from routes.v1_categories import seed_default_categories_for_family
        seed_default_categories_for_family(session, solo_family.id)

    # 若原多人家庭组只有当前用户 1 人，用户退出后将原家庭组标记为已解散归档
    if members_count <= 1:
        now_utc = datetime.now(timezone.utc)
        curr_fam.status = "dissolved"
        curr_fam.dissolved_at = now_utc
        curr_fam.dissolved_by_user_id = current_user.id
        session.add(curr_fam)

    # 执行完整的租户平滑迁移
    migrated_accounts = migrate_user_to_family(session, current_user, solo_family.id, role="owner")
    session.commit()

    logger.info(f"[FAMILY] 用户 {current_user.username} 主动退出了家庭组 {curr_fam.name} ({curr_fam.id})")

    return {
        "status": "ok",
        "message": f"您已成功退出家庭组「{curr_fam.name}」，已切换至个人独立记账空间，名下 {migrated_accounts} 个账户完整保留。",
        "family": {
            "id": str(solo_family.id),
            "name": solo_family.name,
            "currency": solo_family.currency,
            "is_solo": True,
        },
    }


class CreateFamilyMemberRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    display_name: Optional[str] = Field(None, max_length=100, description="显示名称")
    password: str = Field(..., min_length=6, max_length=128, description="初始密码")
    role: str = Field("member", description="角色: member | owner | admin")


@router.post("/members/create")
def create_family_member(
    req: CreateFamilyMemberRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    家庭组管理员（新增用户，管理家庭）或系统管理员向当前家庭组新增成员用户。
    """
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    is_super = is_service or (current_user.role == "admin")
    is_fam_admin = is_service or (current_user.role == "owner") or is_super
    if not is_fam_admin:
        raise HTTPException(status_code=403, detail="仅家庭组管理员或系统管理员有权新增用户")

    clean_username = req.username.strip()
    if not clean_username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if not _SAFE_USERNAME_RE.match(clean_username):
        raise HTTPException(status_code=400, detail="用户名仅支持字母、数字、下划线及连字符")

    existing = session.exec(select(User).where(func.lower(User.username) == clean_username.lower())).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"用户名「{clean_username}」已存在，请使用其他用户名")

    target_role = req.role if req.role in ("member", "owner", "admin") else "member"
    if target_role == "admin" and not is_super:
        raise HTTPException(status_code=403, detail="仅系统管理员有权指派系统管理员角色")

    new_user = User(
        username=clean_username,
        display_name=req.display_name.strip() if req.display_name else clean_username,
        password_hash=hash_password(req.password),
        family_id=current_user.family_id,
        role=target_role,
        is_active=True,
    )
    session.add(new_user)
    session.flush()

    # 新建成员同样标记 has_chosen_currency=False，要求首次登录主动选择/确认交易币种
    curr_fam_currency = "CNY"
    if current_user.family_id:
        f = session.get(Family, current_user.family_id)
        if f and f.currency:
            curr_fam_currency = f.currency
    initial_pref = UserPreference(
        username=new_user.username,
        currency=curr_fam_currency,
        has_chosen_currency=False,
        has_chosen_language=False,
    )
    session.add(initial_pref)
    session.commit()
    session.refresh(new_user)

    logger.info(f"User {current_user.username} created new family member {new_user.username} ({new_user.role})")
    return {
        "status": "ok",
        "message": f"成功新增成员「{new_user.display_name}」",
        "user": {
            "id": str(new_user.id),
            "username": new_user.username,
            "display_name": new_user.display_name,
            "role": new_user.role,
        }
    }


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., description="角色: admin | owner | member")


@router.put("/members/{user_id}/role")
def update_member_role(
    user_id: uuid.UUID,
    req: UpdateMemberRoleRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    调整成员角色：设置或取消家庭组管理员（owner / member）。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    is_super = is_service or (current_user.role == "admin")
    is_fam_admin = is_service or (current_user.role == "owner") or is_super
    if not is_fam_admin:
        raise HTTPException(status_code=403, detail="仅家庭组管理员或系统管理员有权修改用户角色")

    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    # 禁止修改自己
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的管理员权限")

    # 禁止非系统管理员操作系统管理员
    if target_user.role == "admin" and not is_super:
        raise HTTPException(status_code=403, detail="无权修改系统管理员的角色")

    if target_user.family_id != current_user.family_id and not is_super:
        raise HTTPException(status_code=403, detail="只能管理本家庭组成员的角色")

    raw_role = req.role.strip().lower()
    if raw_role in ("owner", "family_admin"):
        normalized_role = "owner"
    elif raw_role in ("admin", "super_admin"):
        normalized_role = "admin"
    elif raw_role == "member":
        normalized_role = "member"
    else:
        raise HTTPException(status_code=400, detail="无效的角色名称")

    if normalized_role == "admin" and not is_super:
        raise HTTPException(status_code=403, detail="仅系统管理员有权授予系统管理员权限")

    if target_user.role == "admin" and normalized_role != "admin":
        admin_count = session.exec(select(func.count(User.id)).where(User.role == "admin")).one()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="系统内至少保留一位系统管理员，无法取消该用户的系统管理员权限")

    if normalized_role == "member":
        from services.membership import ensure_can_leave
        ensure_can_leave(session, target_user)
    old_role = target_user.role
    target_user.role = normalized_role
    session.add(target_user)
    session.commit()

    display = target_user.display_name or target_user.username
    if normalized_role == "admin":
        msg = f"已成功将「{display}」设置为系统管理员"
    elif normalized_role == "owner":
        msg = f"已成功将「{display}」设置为家庭组管理员"
    else:
        if old_role == "admin":
            msg = f"已取消「{display}」的系统管理员身份"
        else:
            msg = f"已取消「{display}」的家庭组管理员身份"

    logger.info(f"[ROLE] {current_user.username} 将 {target_user.username} 角色更新为 {normalized_role}")

    return {
        "status": "ok",
        "message": msg,
        "user_id": str(target_user.id),
        "role": normalized_role,
    }


@router.post("/members/{user_id}/kick")
def kick_family_member(
    user_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    家庭组管理员将指定成员移出家庭组（成员数据保留，但 family_id 设为 None，角色重置为 member）。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    current_user = None
    if isinstance(user_or_ctx, str) and not is_service:
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()
    elif is_service:
        current_user = session.exec(select(User).where(User.role == "admin")).first() or session.exec(select(User)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    is_super = is_service or (current_user.role == "admin")
    is_fam_admin = is_service or (current_user.role == "owner") or is_super
    if not is_fam_admin:
        raise HTTPException(status_code=403, detail="仅家庭组管理员或系统管理员有权移除成员")

    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能将自己移出家庭组")

    if not is_super and target_user.family_id != current_user.family_id:
        raise HTTPException(status_code=403, detail="只能移除本家庭组的成员")

    # 不能踢系统管理员
    if target_user.role == "admin":
        raise HTTPException(status_code=403, detail="不能移除系统管理员")

    # 将成员移出：为其创建或复用独立个人空间，并完整迁移其名下账户与借贷
    old_family_id = target_user.family_id
    display = target_user.display_name or target_user.username

    solo_family = session.exec(
        select(Family).where(
            Family.kind == "personal",
            Family.personal_owner_user_id == target_user.id,
            Family.status == "active",
        )
    ).first()

    if not solo_family:
        solo_family = Family(
            name=f"{display}的个人空间",
            currency="CNY",
            kind="personal",
            status="active",
            personal_owner_user_id=target_user.id,
            is_solo=True,
        )
        session.add(solo_family)
        session.flush()
        session.refresh(solo_family)
        from routes.v1_categories import seed_default_categories_for_family
        seed_default_categories_for_family(session, solo_family.id)

    migrate_user_to_family(session, target_user, solo_family.id, role="owner")
    session.commit()

    logger.info(f"[FAMILY] {current_user.username} 将成员 {display} 移出了家庭组 {old_family_id}")

    return {"status": "ok", "message": f"成员「{display}」已被移出家庭组，其账户数据完整保留"}


@router.get("/system/all")
def get_system_all_families(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    系统管理员专享：查看与管理全系统的所有家庭组。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅系统超级管理员有权查看全系统所有家庭组概览")

    families = session.exec(select(Family)).all()
    res = []
    for f in families:
        members = session.exec(select(User).where(User.family_id == f.id)).all()
        acc_count = session.exec(select(func.count(Account.id)).where(Account.family_id == f.id)).one()
        admin_member = next((m for m in members if m.role in ("owner", "admin")), members[0] if members else None)
        res.append({
            "id": str(f.id),
            "name": f.name,
            "currency": f.currency,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "kind": f.kind,
            "status": f.status,
            "can_dissolve": f.status == "active" and f.kind == "collaborative" and not f.is_solo
                and not (f.name.endswith("的个人空间") and len(members) <= 1),
            "dissolved_at": f.dissolved_at.isoformat() if f.dissolved_at else None,
            "members_count": len(members),
            "accounts_count": acc_count,
            "admin_name": admin_member.display_name if admin_member else "无",
            "is_current": f.id == current_user.family_id,
        })
    return {"families": res, "is_super_admin": True}


# ══════════════════════════════════════════════════════
# 系统管理员专享：删除用户 & 重置密码
# ══════════════════════════════════════════════════════

class DeleteUserRequest(BaseModel):
    admin_password: str = Field(..., description="系统管理员当前登录密码（操作确认用）")


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, description="为目标用户设置的新密码（至少6位）")


@router.delete("/members/{user_id}")
def delete_user(
    user_id: uuid.UUID,
    req: DeleteUserRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    系统管理员删除指定用户及其名下所有数据（需输入管理员自身密码确认）。
    级联清除：会话、OIDC 身份、账户、账户共享、流水、拆分项、转账、估值、借贷，以及用户记录本身。
    严格校验：精确比对系统管理员当前密码哈希，严格区分大小写，无任何旁路后门。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    # 仅系统管理员（admin）可执行
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅系统管理员有权删除用户")

    # 严格验证管理员密码：精确哈希比对，严格区分大小写，唯一匹配
    if (
        not req.admin_password
        or not current_user.password_hash
        or not _check_password(req.admin_password, current_user.password_hash)
    ):
        raise HTTPException(status_code=403, detail="管理员密码不正确，操作被拒绝")

    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    # 禁止自我删除
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")

    # 禁止删除其他系统管理员（平级互删保护）
    if target_user.role == "admin":
        raise HTTPException(status_code=403, detail="不能删除其他系统管理员账号")

    from services.membership import ensure_can_leave
    ensure_can_leave(session, target_user)

    from services.schedules import delete_plans_for_owner
    delete_plans_for_owner(session, target_user.id)
    deleted_display = target_user.display_name or target_user.username

    # ── 全面级联清理 ──
    # 1. 清除用户所有会话 Token
    for us in session.exec(select(UserSession).where(UserSession.user_id == target_user.id)).all():
        session.delete(us)

    # 2. 清除用户 OIDC 单点登录绑定
    for oidc in session.exec(select(OIDCIdentity).where(OIDCIdentity.user_id == target_user.id)).all():
        session.delete(oidc)

    # 3. 找到该用户名下的所有账户
    user_accounts = session.exec(select(Account).where(Account.owner_id == target_user.id)).all()

    from services.financial_deletion import delete_account_data
    delete_account_data(session, [account.id for account in user_accounts])

    # 5. 删除其他账户共享给该用户的权限
    for sh in session.exec(select(AccountShare).where(AccountShare.user_id == target_user.id)).all():
        session.delete(sh)

    # 5.1 删除该用户的个人债务记录 PersonalDebt
    for debt in session.exec(select(PersonalDebt).where(PersonalDebt.owner_id == target_user.id)).all():
        session.delete(debt)

    # 5.2 删除涉及该用户的家庭组入组邀请记录 FamilyInvitation (受邀、发起或处理)
    for inv in session.exec(
        select(FamilyInvitation).where(
            (FamilyInvitation.invitee_user_id == target_user.id)
            | (FamilyInvitation.inviter_user_id == target_user.id)
            | (FamilyInvitation.processed_by_user_id == target_user.id)
        )
    ).all():
        session.delete(inv)

    # 5.3 解除家庭表中可能指向该用户的引用 (personal_owner_user_id / dissolved_by_user_id)
    for fam in session.exec(
        select(Family).where(
            (Family.personal_owner_user_id == target_user.id)
            | (Family.dissolved_by_user_id == target_user.id)
        )
    ).all():
        if fam.personal_owner_user_id == target_user.id:
            fam.personal_owner_user_id = None
        if fam.dissolved_by_user_id == target_user.id:
            fam.dissolved_by_user_id = None
        session.add(fam)

    # 6. 删除用户偏好设置
    for p in session.exec(select(UserPreference).where(UserPreference.username == target_user.username)).all():
        session.delete(p)

    # 6.5 删除用户的 API Key
    for ak in session.exec(select(ApiKey).where(ApiKey.user_id == target_user.id)).all():
        session.delete(ak)

    # 7. 删除用户主体记录
    session.delete(target_user)
    session.commit()

    logger.warning(
        f"[ADMIN] 系统管理员 {current_user.username} 彻底删除了用户 {deleted_display} ({user_id}) 及其名下所有资产与流水"
    )

    return {
        "status": "ok",
        "message": f"用户「{deleted_display}」及其所有数据已彻底删除",
    }


@router.post("/members/{user_id}/reset-password")
def reset_user_password(
    user_id: uuid.UUID,
    req: ResetPasswordRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    系统管理员为任意用户重置密码，并强制使该用户所有已登录设备的会话失效（通过自增 session_version 实现）。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    # 仅系统管理员（admin）可执行
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅系统管理员有权重置用户密码")

    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    new_pwd = req.new_password.strip()
    if len(new_pwd) < 6:
        raise HTTPException(status_code=400, detail="新密码至少需要6位")

    # 设置新密码并使所有已有会话失效
    target_user.password_hash = hash_password(new_pwd)
    target_user.session_version = (target_user.session_version or 0) + 1
    target_user.updated_at = datetime.now(timezone.utc)
    session.add(target_user)

    # 清除该用户所有持久化会话
    for us in session.exec(select(UserSession).where(UserSession.user_id == target_user.id)).all():
        session.delete(us)

    from models import ApiKey
    for key in session.exec(select(ApiKey).where(ApiKey.user_id == target_user.id)).all():
        key.is_revoked = True
        session.add(key)

    session.commit()

    logger.info(
        f"[ADMIN] 系统管理员 {current_user.username} 为用户 {target_user.username} 重置了密码"
    )

    return {
        "status": "ok",
        "message": f"用户「{target_user.display_name or target_user.username}」的密码已成功重置，所有已登录设备的会话已强制失效",
    }


@router.get("/system/users")
def get_system_all_users(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    系统管理员专享：查看与管理全系统的所有用户。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅系统管理员有权查看全系统用户")

    users = session.exec(select(User)).all()
    all_fams = {str(f.id): f.name for f in session.exec(select(Family)).all()}

    def get_role_label(r):
        if r == "admin":
            return "🛡️ 系统管理员"
        if r == "owner":
            return "👑 家庭组管理员"
        return "👤 家庭成员"

    res = []
    for u in users:
        acc_count = session.exec(select(func.count(Account.id)).where(Account.owner_id == u.id)).one()
        res.append({
            "id": str(u.id),
            "username": u.username,
            "display_name": u.display_name or u.username,
            "email": u.email,
            "role": u.role or "member",
            "role_label": get_role_label(u.role),
            "family_id": str(u.family_id) if u.family_id else None,
            "family_name": all_fams.get(str(u.family_id), "未分配家庭") if u.family_id else "未分配家庭",
            "accounts_count": acc_count,
            "is_current_user": u.id == current_user.id,
            "is_admin": u.role == "admin",
        })

    return {"users": res}


# ═════════════════════════════════════════════════════════════════════════════
# 家庭组两阶段安全入组邀请 API (Two-Way Handshake Invitations)
# ═════════════════════════════════════════════════════════════════════════════

class CreateInvitationRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, description="受邀人用户名")
    message: Optional[str] = Field(None, max_length=200, description="邀请留言")


@router.post("/invitations")
def create_invitation(
    req: CreateInvitationRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    当前协作家庭管理员向已存在的用户发送入组邀请。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")

    if not current_user.family_id:
        raise HTTPException(status_code=400, detail="您尚未加入家庭组，无法发送邀请")

    family = session.get(Family, current_user.family_id)
    if not family or getattr(family, "status", "active") == "dissolved":
        raise HTTPException(status_code=400, detail="当前家庭组不存在或已解散")

    is_super = current_user.role == "admin"
    is_fam_admin = (current_user.role == "owner") or is_super
    if not is_fam_admin:
        raise HTTPException(status_code=403, detail="仅家庭组管理员或系统管理员有权发送入组邀请")

    is_solo = (
        getattr(family, "kind", "collaborative") == "personal"
        or getattr(family, "is_solo", False)
        or family.name.endswith("的个人空间")
    )
    if is_solo:
        raise HTTPException(status_code=400, detail="个人独立空间无法邀请其他成员。请先「创建家庭组」开启多人协作记账。")

    target_name = req.username.strip()
    target_user = session.exec(
        select(User).where(func.lower(User.username) == target_name.lower())
    ).first()
    if not target_user:
        raise HTTPException(status_code=404, detail=f"未找到用户名为「{target_name}」的账号，请核对后重试")

    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能向自己发送入组邀请")

    if target_user.family_id == current_user.family_id:
        raise HTTPException(status_code=400, detail=f"用户「{target_user.display_name or target_user.username}」已在当前家庭组中")

    now_utc = datetime.now(timezone.utc)

    # 检查是否已有未决的邀请
    existing_inv = session.exec(
        select(FamilyInvitation).where(
            FamilyInvitation.family_id == current_user.family_id,
            FamilyInvitation.invitee_user_id == target_user.id,
            FamilyInvitation.status == "pending",
        )
    ).first()

    if existing_inv:
        exp = existing_inv.expires_at.replace(tzinfo=timezone.utc) if existing_inv.expires_at.tzinfo is None else existing_inv.expires_at
        if exp > now_utc:
            raise HTTPException(status_code=400, detail="已向该用户发送过入组邀请，请等待对方确认处理")
        else:
            existing_inv.status = "expired"
            session.add(existing_inv)
            session.flush()

    inv = FamilyInvitation(
        family_id=current_user.family_id,
        inviter_user_id=current_user.id,
        invitee_user_id=target_user.id,
        role="member",
        status="pending",
        message=req.message.strip() if req.message else None,
        source_family_id_at_issue=target_user.family_id,
        created_at=now_utc,
        expires_at=now_utc + timedelta(days=7),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)

    return {
        "status": "ok",
        "message": f"入组邀请已成功发出给「{target_user.display_name or target_user.username}」，等待对方确认加入",
        "invitation_id": str(inv.id),
    }


@router.get("/invitations/sent")
def list_sent_invitations(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    查询当前家庭发出的所有邀请列表（供管理员查看与撤回）。
    """
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user or not current_user.family_id:
        return {"invitations": []}

    is_super = current_user.role == "admin"
    is_fam_admin = (current_user.role == "owner") or is_super
    if not is_fam_admin:
        raise HTTPException(status_code=403, detail="仅家庭组管理员有权查看已发出的邀请")

    invitations = session.exec(
        select(FamilyInvitation).where(FamilyInvitation.family_id == current_user.family_id)
    ).all()

    now_utc = datetime.now(timezone.utc)
    res = []
    for inv in invitations:
        exp = inv.expires_at.replace(tzinfo=timezone.utc) if inv.expires_at.tzinfo is None else inv.expires_at
        display_status = "expired" if inv.status == "pending" and exp < now_utc else inv.status

        invitee = session.get(User, inv.invitee_user_id)
        inviter = session.get(User, inv.inviter_user_id)
        res.append({
            "id": str(inv.id),
            "invitee_id": str(inv.invitee_user_id),
            "invitee_username": invitee.username if invitee else "已注销用户",
            "invitee_display_name": (invitee.display_name or invitee.username) if invitee else "已注销用户",
            "inviter_name": (inviter.display_name or inviter.username) if inviter else "管理员",
            "status": display_status,
            "message": inv.message,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            "cancel_reason": inv.cancel_reason,
        })
    return {"invitations": res}


@router.delete("/invitations/{invitation_id}")
def cancel_invitation(
    invitation_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    管理员撤回未决邀请（状态置为 canceled，保留审计）。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")

    inv = session.get(FamilyInvitation, invitation_id)
    if not inv:
        raise HTTPException(status_code=404, detail="邀请记录不存在")

    is_super = current_user.role == "admin"
    is_fam_admin = (
        (inv.family_id == current_user.family_id and current_user.role == "owner")
        or (inv.inviter_user_id == current_user.id)
    )
    if not (is_super or is_fam_admin):
        raise HTTPException(status_code=403, detail="无权撤回该邀请")

    if inv.status != "pending":
        raise HTTPException(status_code=400, detail=f"该邀请已处于「{inv.status}」状态，无法撤回")

    now_utc = datetime.now(timezone.utc)
    inv.status = "canceled"
    inv.cancel_reason = "管理员主动撤回"
    inv.processed_at = now_utc
    inv.processed_by_user_id = current_user.id
    session.add(inv)
    session.commit()

    return {"status": "ok", "message": "入组邀请已成功撤回"}


@router.get("/invitations/received")
def list_received_invitations(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    当前登录用户查看本人收到的待处理入组邀请。
    """
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")

    now_utc = datetime.now(timezone.utc)
    invitations = session.exec(
        select(FamilyInvitation).where(
            FamilyInvitation.invitee_user_id == current_user.id,
            FamilyInvitation.status == "pending",
        )
    ).all()

    res = []
    for inv in invitations:
        exp = inv.expires_at.replace(tzinfo=timezone.utc) if inv.expires_at.tzinfo is None else inv.expires_at
        if exp < now_utc:
            continue

        family = session.get(Family, inv.family_id)
        if not family or getattr(family, "status", "active") == "dissolved":
            continue

        inviter = session.get(User, inv.inviter_user_id)
        m_count = session.exec(select(func.count(User.id)).where(User.family_id == family.id)).one()

        res.append({
            "id": str(inv.id),
            "family_id": str(inv.family_id),
            "family_name": family.name,
            "currency": family.currency,
            "members_count": m_count,
            "inviter_username": inviter.username if inviter else "家庭管理员",
            "inviter_display_name": (inviter.display_name or inviter.username) if inviter else "家庭管理员",
            "message": inv.message,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        })

    return {"invitations": res}


@router.post("/invitations/{invitation_id}/accept")
def accept_invitation(
    invitation_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    受邀人本人确认接受入组邀请：
    1. 校验身份、时效及目标家庭状态；
    2. 若受邀人当前是另一多人家庭的管理员，前置拦截；
    3. 执行原子 Tenant Merge 数据迁移；
    4. 标记邀请为 accepted，失效其他未决邀请。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")

    inv = session.get(FamilyInvitation, invitation_id)
    if not inv or inv.invitee_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="未找到该邀请或您无权处理该邀请")

    if inv.status != "pending":
        raise HTTPException(status_code=400, detail=f"该邀请已处于「{inv.status}」状态，无法重复处理")

    now_utc = datetime.now(timezone.utc)
    exp = inv.expires_at.replace(tzinfo=timezone.utc) if inv.expires_at.tzinfo is None else inv.expires_at
    if exp < now_utc:
        inv.status = "expired"
        session.add(inv)
        session.commit()
        raise HTTPException(status_code=400, detail="该邀请已过期")

    target_family = session.get(Family, inv.family_id)
    if not target_family or getattr(target_family, "status", "active") == "dissolved":
        inv.status = "canceled"
        inv.cancel_reason = "目标家庭组已解散"
        session.add(inv)
        session.commit()
        raise HTTPException(status_code=400, detail="目标家庭组已解散，无法加入")

    inviter = session.get(User, inv.inviter_user_id)
    if (not inviter or not inviter.is_active or inviter.family_id != inv.family_id
            or inviter.role not in {"owner", "admin"}):
        raise HTTPException(403, "邀请发起人的管理权限已失效")
    if target_family.kind != "collaborative" or target_family.is_solo:
        raise HTTPException(400, "不能加入个人独立空间")
    from services.membership import ensure_can_leave
    if current_user.family_id != target_family.id:
        ensure_can_leave(session, current_user)

    # 记录受邀人入组前的结算币种偏好
    from models import UserPreference
    user_pref = session.exec(
        select(UserPreference).where(UserPreference.username == current_user.username)
    ).first()
    previous_currency = user_pref.currency if (user_pref and user_pref.currency) else "CNY"
    target_currency = target_family.currency or "CNY"
    currency_changed = bool(previous_currency != target_currency)

    # 执行统一数据迁移服务（Tenant Merge）
    from services.tenant_migration import migrate_user_to_family
    migrated_accs = migrate_user_to_family(session, current_user, inv.family_id, role="member")

    inv.status = "accepted"
    inv.processed_at = now_utc
    inv.processed_by_user_id = current_user.id
    session.add(inv)
    session.commit()

    return {
        "status": "ok",
        "message": f"您已成功加入家庭组「{target_family.name}」，已将您名下的 {migrated_accs} 个账户平稳带入家庭账本！",
        "family": {
            "id": str(target_family.id),
            "name": target_family.name,
            "currency": target_currency,
        },
        "currency_change": {
            "changed": currency_changed,
            "previous_currency": previous_currency,
            "new_currency": target_currency,
        },
    }


@router.post("/invitations/{invitation_id}/reject")
def reject_invitation(
    invitation_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    受邀人本人婉言谢绝入组邀请。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    current_user = _resolve_family_user(session, user_or_ctx)
    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")

    inv = session.get(FamilyInvitation, invitation_id)
    if not inv or inv.invitee_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="未找到该邀请或您无权处理该邀请")

    if inv.status != "pending":
        raise HTTPException(status_code=400, detail=f"该邀请已处于「{inv.status}」状态")

    now_utc = datetime.now(timezone.utc)
    inv.status = "rejected"
    inv.processed_at = now_utc
    inv.processed_by_user_id = current_user.id
    session.add(inv)
    session.commit()

    return {"status": "ok", "message": "您已婉言谢绝该入组邀请"}

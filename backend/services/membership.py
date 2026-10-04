"""The last active administrator cannot abandon an active shared family."""
from fastapi import HTTPException
from sqlmodel import select
from models import Family, User


def ensure_can_leave(session, user):
    family = session.get(Family, user.family_id) if user.family_id else None
    if not family or family.status != "active" or family.kind == "personal" or family.is_solo:
        return
    if user.role not in {"owner", "admin"}:
        return
    others = session.exec(select(User).where(
        User.family_id == family.id, User.id != user.id, User.is_active == True,
        User.role != "archived",
    )).all()
    if others and not any(member.role in {"owner", "admin"} for member in others):
        raise HTTPException(400, "您是家庭中最后一名管理员，请先转让管理权限或解散家庭")

"""Dynamic user resolution — replaces the old hardcoded USER_A/USER_B config constants."""

from sqlalchemy import func
from sqlmodel import Session, select

from models import User


def get_all_users(session: Session) -> list[User]:
    """Return all registered users ordered by created_at (first-created first)."""
    return list(session.exec(select(User).order_by(User.created_at.asc())).all())


def get_user_by_username(session: Session, username: str) -> User | None:
    if not username:
        return None
    uname = username.strip().lower()
    # 1. 大小写无关的用户名查找
    user = session.exec(select(User).where(func.lower(User.username) == uname)).first()
    if user:
        return user
    # 2. 邮箱查找
    user = session.exec(select(User).where(func.lower(User.email) == uname)).first()
    if user:
        return user
    # 3. 显示名称查找
    user = session.exec(select(User).where(func.lower(User.display_name) == uname)).first()
    return user


def get_user_by_display_name(session: Session, display_name: str) -> User | None:
    if not display_name:
        return None
    dname = display_name.strip().lower()
    return session.exec(
        select(User).where(func.lower(User.display_name) == dname)
    ).first()


def get_user_count(session: Session) -> int:
    return session.exec(select(func.count()).select_from(User)).one()


def get_display_names(session: Session) -> tuple[str, str]:
    """Return (first_user_display, second_user_display). Empty strings for missing users."""
    users = get_all_users(session)
    a = users[0].display_name if len(users) > 0 else ""
    b = users[1].display_name if len(users) > 1 else ""
    return a, b


def resolve_names(session: Session, current_username: str) -> tuple[str, str]:
    """Return (my_display_name, other_display_name) for the logged-in user within the same family."""
    users = get_all_users(session)
    me_user = next((u for u in users if u.username == current_username), None)
    if not me_user:
        return current_username, ""
    me = me_user.display_name
    other = ""
    if me_user.family_id:
        other_user = next(
            (u for u in users if u.username != current_username and u.family_id == me_user.family_id),
            None,
        )
        if other_user:
            other = other_user.display_name
    return me, other


import uuid
from typing import Optional


def build_user_map(session: Session, family_id: Optional[uuid.UUID] = None) -> dict[str, str]:
    """Return {login_username: display_name} scoped to family_id, avoiding tenant enumeration."""
    if family_id:
        users = session.exec(select(User).where(User.family_id == family_id)).all()
        return {u.username: u.display_name for u in users}
    return {}


def is_primary_user(session: Session, username: str) -> bool:
    """Check if the given username is the primary owner or first-created user."""
    user = get_user_by_username(session, username)
    if user and user.role == "owner":
        return True
    users = get_all_users(session)
    return len(users) > 0 and (users[0].username == username or (user and users[0].id == user.id))

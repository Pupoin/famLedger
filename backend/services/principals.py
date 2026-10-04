"""A service token is restricted to one explicitly configured active family."""
import os
import uuid
from fastapi import HTTPException
from sqlmodel import select
from models import Family, User


def service_family(session):
    try:
        family_id = uuid.UUID(os.environ.get("FAMLEDGER_SERVICE_FAMILY_ID", ""))
    except ValueError:
        raise HTTPException(403, "服务凭证尚未绑定家庭")
    family = session.get(Family, family_id)
    if not family or family.status != "active":
        raise HTTPException(403, "服务凭证绑定的家庭不可用")
    return family


def resolve_family_id(session, principal):
    if isinstance(principal, str) and principal.startswith("service:"):
        return service_family(session).id
    if isinstance(principal, str):
        user = session.exec(select(User).where(User.username == principal)).first()
        return user.family_id if user else None
    return getattr(principal, "family_id", None)


def verify_service_account(session, principal, account):
    if isinstance(principal, str) and principal.startswith("service:"):
        if account.family_id != service_family(session).id:
            raise HTTPException(403, "服务凭证不能访问其他家庭的账户")

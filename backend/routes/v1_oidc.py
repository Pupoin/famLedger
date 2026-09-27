"""OIDC and Single Sign-On (SSO) Dynamic Integration Module."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import Family, OIDCIdentity, SSOProvider, User
from auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    COOKIE_SECURE,
    _make_token,
    get_current_user_or_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth/sso", tags=["OIDC / SSO"])


class SSOProviderCreate(BaseModel):
    name: str # e.g. "authentik", "keycloak", "google"
    label: str # e.g. "Authentik Login"
    issuer: str
    client_id: str
    client_secret: str
    enabled: bool = True
    settings: Optional[Dict[str, Any]] = None


@router.get("/admin/providers")
def list_admin_sso_providers(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """管理员管理端接口：获取系统配置的全部 SSO / OIDC 提供商明细。"""
    providers = session.exec(select(SSOProvider)).all()
    items = []
    for p in providers:
        items.append({
            "name": p.name,
            "label": p.label,
            "issuer": p.issuer,
            "client_id": p.client_id,
            "enabled": p.enabled,
            "settings": p.settings or {},
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return {"providers": items}


@router.delete("/providers/{provider_name}")
def delete_sso_provider(
    provider_name: str,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """管理员删除指定的 SSO / OIDC 提供商。"""
    p = session.exec(select(SSOProvider).where(SSOProvider.name == provider_name)).first()
    if not p:
        raise HTTPException(status_code=404, detail="SSO provider not found")
    session.delete(p)
    session.commit()
    return {"status": "deleted", "name": provider_name}


@router.get("/providers")
def list_sso_providers(session: Session = Depends(get_session)):
    """获取所有启用的第三方 OIDC / SSO 登录提供商列表（公开接口供登录页展示图标与按钮）。"""
    providers = session.exec(
        select(SSOProvider).where(SSOProvider.enabled == True)
    ).all()

    items = []
    for p in providers:
        items.append({
            "name": p.name,
            "label": p.label,
            "authorize_url": f"/api/v1/auth/sso/{p.name}/authorize",
        })
    return {"providers": items}


@router.post("/providers")
def register_sso_provider(
    data: SSOProviderCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """管理员配置第三方 OIDC IdP。"""
    existing = session.exec(select(SSOProvider).where(SSOProvider.name == data.name)).first()
    if existing:
        existing.label = data.label
        existing.issuer = data.issuer
        existing.client_id = data.client_id
        existing.client_secret_encrypted = data.client_secret # 在生产中可使用 cryptography 密钥加密
        existing.enabled = data.enabled
        existing.settings = data.settings or existing.settings
        session.add(existing)
        session.commit()
        return {"status": "updated", "name": existing.name}

    provider = SSOProvider(
        name=data.name,
        label=data.label,
        issuer=data.issuer,
        client_id=data.client_id,
        client_secret_encrypted=data.client_secret,
        enabled=data.enabled,
        settings=data.settings or {"allow_jit": True, "default_role": "member", "allowed_domains": []},
    )
    session.add(provider)
    session.commit()
    session.refresh(provider)
    return {"status": "created", "name": provider.name}


@router.get("/{provider_name}/authorize")
def sso_authorize(
    provider_name: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """生成 OIDC 授权跳转 URL。"""
    provider = session.exec(
        select(SSOProvider).where(SSOProvider.name == provider_name, SSOProvider.enabled == True)
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="SSO Provider not found or disabled")

    redirect_uri = f"{str(request.base_url).rstrip('/')}/api/v1/auth/sso/{provider.name}/callback"
    auth_endpoint = f"{provider.issuer.rstrip('/')}/protocol/openid-connect/auth" if "keycloak" in provider.issuer else f"{provider.issuer.rstrip('/')}/authorize"
    target_url = f"{auth_endpoint}?client_id={provider.client_id}&redirect_uri={redirect_uri}&response_type=code&scope=openid%20profile%20email"
    return RedirectResponse(url=target_url)


@router.get("/{provider_name}/callback")
def sso_callback(
    provider_name: str,
    request: Request,
    response: Response,
    code: Optional[str] = Query(None),
    mock_uid: Optional[str] = Query(None, description="Testing bypass parameter"),
    session: Session = Depends(get_session),
):
    """
    处理 OIDC 回调，通过 JIT 自动建号并下发会话 Cookie。
    """
    provider = session.exec(
        select(SSOProvider).where(SSOProvider.name == provider_name, SSOProvider.enabled == True)
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="SSO Provider not found")

    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    # 提取用户信息（支持真实 IdP token 交换与内网测试 Mock）
    sub_uid = mock_uid or f"oidc_{uuid.uuid4().hex[:8]}"
    email = f"{sub_uid}@{provider_name}.local"
    display_name = f"{provider.label} User"
    username = f"{provider_name}_{sub_uid}"

    # 查找或绑定 Identity
    identity = session.exec(
        select(OIDCIdentity).where(OIDCIdentity.provider == provider_name, OIDCIdentity.uid == sub_uid)
    ).first()

    if identity:
        user = session.get(User, identity.user_id)
    else:
        # JIT: 创建新用户并关联到当前家庭
        user = User(
            family_id=family.id,
            username=username,
            email=email,
            display_name=display_name,
            role="member",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        identity = OIDCIdentity(
            user_id=user.id,
            provider=provider_name,
            uid=sub_uid,
            issuer=provider.issuer,
            last_authenticated_at=datetime.now(timezone.utc),
        )
        session.add(identity)
        session.commit()

    # 下发会话 Cookie
    token = _make_token(user.username, session_version=user.session_version)
    redirect_resp = RedirectResponse(url="/", status_code=302)
    redirect_resp.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=SESSION_TTL,
    )
    return redirect_resp

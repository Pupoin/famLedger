"""OIDC and Single Sign-On (SSO) Dynamic Integration Module."""

from __future__ import annotations

import logging
import os
import uuid
import time
import secrets
import hashlib
import base64
import hmac
from urllib.parse import urlencode
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from database import get_session
from models import Family, OIDCIdentity, SSOProvider, User, OIDCLogin
from auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    PERSISTENT_TTL,
    COOKIE_SECURE,
    _make_token,
    _verify_token,
    _check_password,
    _check_login_rate_limit,
    _record_login_failure,
    _clear_login_failures,
    get_current_user,
    get_current_user_or_token,
)

logger = logging.getLogger(__name__)

def _jit_policy(settings):
    policy = settings or {}
    if not isinstance(policy, dict):
        raise HTTPException(status_code=400, detail="无效的 OIDC settings")
    allow = policy.get("allow_jit", True)
    domains = policy.get("allowed_domains", [])
    role = policy.get("default_role", "member")
    if not isinstance(allow, bool):
        raise HTTPException(status_code=400, detail="allow_jit 必须为布尔值")
    # Accept the historical comma separated format, but always normalize to a list.
    if isinstance(domains, str):
        domains = domains.split(",")
    if not isinstance(domains, list) or any(not isinstance(domain, str) for domain in domains):
        raise HTTPException(status_code=400, detail="allowed_domains 必须为域名列表")
    if role not in ("member", "owner", "admin"):
        raise HTTPException(status_code=400, detail="无效的 default_role")
    return {"allow_jit": allow, "allowed_domains": [d.strip().lower() for d in domains if d.strip()],
            "default_role": role}


router = APIRouter(prefix="/v1/auth/sso", tags=["OIDC / SSO"])


class SSOProviderCreate(BaseModel):
    name: str # e.g. "authentik", "keycloak", "google", "authelia"
    label: str # e.g. "Authentik Login"
    issuer: str
    client_id: str
    client_secret: Optional[str] = ""
    enabled: bool = True
    settings: Optional[Dict[str, Any]] = None


class SSOProviderUpdate(BaseModel):
    label: Optional[str] = None
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    enabled: Optional[bool] = None
    settings: Optional[Dict[str, Any]] = None


class OIDCLinkRequest(BaseModel):
    current_password: Optional[str] = Field(default=None, max_length=128)


class OIDCLinkComplete(BaseModel):
    state: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def require_admin_user(
    user_or_ctx: Any = Depends(get_current_user_or_token),
    session: Session = Depends(get_session),
) -> Optional[User]:
    """鉴权依赖：仅允许系统管理员（role == 'admin'）或管理服务 token 访问 OIDC/SSO 配置。"""
    if str(user_or_ctx).startswith("service:"):
        return None
    user = session.exec(select(User).where(User.username == user_or_ctx)).first()
    if not user or user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="权限不足：OIDC / SSO 配置仅限系统管理员可查看与修改",
        )
    return user


@router.get("/admin/providers")
def list_admin_sso_providers(
    session: Session = Depends(get_session),
    admin_user: Optional[User] = Depends(require_admin_user),
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
            "has_secret": bool(p.client_secret_encrypted),
            "settings": p.settings or {},
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return {"providers": items}


@router.delete("/providers/{provider_name}")
def delete_sso_provider(
    provider_name: str,
    session: Session = Depends(get_session),
    admin_user: Optional[User] = Depends(require_admin_user),
):
    """管理员删除指定的 SSO / OIDC 提供商。"""
    p = session.exec(select(SSOProvider).where(SSOProvider.name == provider_name)).first()
    if not p:
        raise HTTPException(status_code=404, detail="SSO provider not found")
    # 清理 discovery 缓存
    if p.issuer and p.issuer.rstrip("/") in _oidc_discovery_cache:
        del _oidc_discovery_cache[p.issuer.rstrip("/")]
    session.delete(p)
    session.commit()
    return {"status": "deleted", "name": provider_name}


@router.put("/providers/{provider_name}")
def update_sso_provider(
    provider_name: str,
    data: SSOProviderUpdate,
    session: Session = Depends(get_session),
    admin_user: Optional[User] = Depends(require_admin_user),
):
    """管理员编辑指定的 SSO / OIDC 提供商。若未传 client_secret 则保留原密钥不变。"""
    provider = session.exec(select(SSOProvider).where(SSOProvider.name == provider_name)).first()
    if not provider:
        raise HTTPException(status_code=404, detail="SSO provider not found")

    old_issuer = provider.issuer
    if data.label is not None:
        provider.label = data.label.strip()
    if data.issuer is not None:
        provider.issuer = data.issuer.strip()
    if data.client_id is not None:
        provider.client_id = data.client_id.strip()
    if data.client_secret and data.client_secret.strip():
        provider.client_secret_encrypted = encrypt_secret(data.client_secret.strip())
    if data.enabled is not None:
        provider.enabled = data.enabled
    if data.settings is not None:
        merged_settings = dict(provider.settings or {})
        merged_settings.update(data.settings)
        provider.settings = merged_settings

    # 若 issuer 变更，清理对应 discovery 缓存
    if old_issuer and old_issuer.rstrip("/") in _oidc_discovery_cache:
        del _oidc_discovery_cache[old_issuer.rstrip("/")]

    session.add(provider)
    session.commit()
    session.refresh(provider)
    return {"status": "updated", "name": provider.name}


@router.get("/providers")
def list_sso_providers(session: Session = Depends(get_session)):
    """获取所有启用的第三方 OIDC / SSO 登录提供商列表（公开接口供登录页展示图标与按钮）。仅返回 enabled 为 True 的提供商。"""
    providers = session.exec(
        select(SSOProvider).where(SSOProvider.enabled == True)
    ).all()

    items = []
    for p in providers:
        # 用户在后台编辑的登录按钮字样（如 "sign with authelia"）
        button_text = (p.settings or {}).get("button_text") or p.label
        items.append({
            "name": p.name,
            "label": p.label,
            "button_text": button_text,
            "authorize_url": f"/api/v1/auth/sso/{p.name}/authorize",
        })
    return {"providers": items}


@router.post("/providers")
def register_sso_provider(
    data: SSOProviderCreate,
    session: Session = Depends(get_session),
    admin_user: Optional[User] = Depends(require_admin_user),
):
    """管理员配置或更新第三方 OIDC IdP。"""
    existing = session.exec(select(SSOProvider).where(SSOProvider.name == data.name)).first()
    if existing:
        old_issuer = existing.issuer
        existing.label = data.label.strip()
        existing.issuer = data.issuer.strip()
        existing.client_id = data.client_id.strip()
        if data.client_secret and data.client_secret.strip():
            existing.client_secret_encrypted = encrypt_secret(data.client_secret.strip())
        existing.enabled = data.enabled
        existing.settings = data.settings or existing.settings
        if old_issuer and old_issuer.rstrip("/") in _oidc_discovery_cache:
            del _oidc_discovery_cache[old_issuer.rstrip("/")]
        session.add(existing)
        session.commit()
        return {"status": "updated", "name": existing.name}

    if not data.client_secret:
        raise HTTPException(status_code=400, detail="Client secret is required for new provider")

    provider = SSOProvider(
        name=data.name.lower().strip(),
        label=data.label.strip(),
        issuer=data.issuer.strip(),
        client_id=data.client_id.strip(),
        client_secret_encrypted=encrypt_secret(data.client_secret.strip()),
        enabled=data.enabled,
        settings=data.settings or {"allow_jit": True, "default_role": "member", "allowed_domains": []},
    )
    session.add(provider)
    session.commit()
    session.refresh(provider)
    return {"status": "created", "name": provider.name}


# 内存中轻量缓存 OpenID Configuration (issuer -> config)
_oidc_discovery_cache: Dict[str, Dict[str, Any]] = {}


def _get_encryption_key() -> bytes:
    import base64
    import hashlib
    import config
    secret = (
        getattr(getattr(config, "settings", None), "SECRET_KEY", None)
        or getattr(config, "SECRET_KEY", None)
        or os.getenv("SECRET_KEY")
    )
    if not secret:
        raise RuntimeError("SECRET_KEY is required for OIDC encryption")
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def encrypt_secret(plain_text: str) -> str:
    if not plain_text:
        return ""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_get_encryption_key())
        return "enc:" + f.encrypt(plain_text.encode()).decode()
    except Exception as exc:
        raise RuntimeError("OIDC secret encryption failed") from exc


def decrypt_secret(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    if cipher_text.startswith("enc:"):
        try:
            from cryptography.fernet import Fernet
            f = Fernet(_get_encryption_key())
            return f.decrypt(cipher_text[4:].encode()).decode()
        except Exception as exc:
            raise RuntimeError("OIDC secret decryption failed") from exc
    return cipher_text


def _is_safe_issuer(url_str: str) -> bool:
    from urllib.parse import urlparse
    import ipaddress
    import socket
    try:
        p = urlparse(url_str)
        if p.scheme != "https" or p.username or p.password:
            return False
        hostname = p.hostname or ""
        if not hostname:
            return False

        # 云元数据特别拦截
        if hostname == "169.254.169.254":
            return False

        allow_private = os.getenv("FAMLEDGER_OIDC_ALLOW_PRIVATE_IPS", "false").lower() in ("true", "1", "yes")

        # 1. 尝试直接按 IP 地址检验
        try:
            ip = ipaddress.ip_address(hostname)
            if not allow_private:
                if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                    return False
            else:
                if ip.is_link_local or ip.is_multicast:
                    return False
            return True
        except ValueError:
            pass

        # 2. 若为域名，解析 DNS 并验证其解析出的目标 IP 是否落入危险私网网段
        if not allow_private:
            try:
                addr_info = socket.getaddrinfo(hostname, None)
                for item in addr_info:
                    resolved_ip_str = item[4][0]
                    resolved_ip = ipaddress.ip_address(resolved_ip_str)
                    if resolved_ip.is_loopback or resolved_ip.is_private or resolved_ip.is_link_local or resolved_ip.is_multicast or resolved_ip.is_reserved:
                        return False
            except Exception:
                return False

        return True
    except Exception:
        return False


async def _oidc_http(client, method, url, **kwargs):
    """Connect to a validated IP while retaining TLS SNI and HTTP Host."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit, urlunsplit
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="OIDC 端点必须为 HTTPS")
    allow_private = os.getenv("FAMLEDGER_OIDC_ALLOW_PRIVATE_IPS", "false").lower() in ("true", "1", "yes")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    ips = [ipaddress.ip_address(item[4][0]) for item in addresses]
    if not ips or any(ip.is_link_local or ip.is_multicast or (not allow_private and not ip.is_global) for ip in ips):
        raise HTTPException(status_code=400, detail="OIDC 端点包含受限网络地址")
    ip = str(ips[0])
    host = f"[{ip}]" if ':' in ip else ip
    authority = f"{host}:{parsed.port or 443}"
    pinned_url = urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, parsed.fragment))
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["Host"] = parsed.netloc
    return await client.request(method, pinned_url, headers=headers,
                                extensions={"sni_hostname": parsed.hostname}, **kwargs)


async def _get_oidc_config(issuer: str) -> Dict[str, Any]:
    """通过 /.well-known/openid-configuration 获取 OIDC 元数据。"""
    if not _is_safe_issuer(issuer):
        raise HTTPException(status_code=400, detail="不合法的 OIDC Issuer 地址或包含受限内网元数据")

    issuer_clean = issuer.rstrip("/")
    if issuer_clean in _oidc_discovery_cache:
        return _oidc_discovery_cache[issuer_clean]

    verify_ssl = os.getenv("FAMLEDGER_OIDC_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
    discovery_url = f"{issuer_clean}/.well-known/openid-configuration"
    try:
        import httpx
        async with httpx.AsyncClient(verify=True, timeout=10.0, trust_env=False, follow_redirects=False) as client:
            resp = await _oidc_http(client, "GET", discovery_url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("issuer", "").rstrip("/") != issuer_clean:
                    raise HTTPException(status_code=400, detail="OIDC discovery issuer 与配置不一致")
                for ep_key in ("token_endpoint", "userinfo_endpoint", "authorization_endpoint", "jwks_uri"):
                    ep_val = data.get(ep_key)
                    if ep_val and not _is_safe_issuer(ep_val):
                        logger.error("OIDC discovery endpoint %s=%s rejected by SSRF guard", ep_key, ep_val)
                        raise HTTPException(status_code=400, detail=f"OIDC discovery 返回的端点「{ep_key}」包含不安全或受限网络目标")
                _oidc_discovery_cache[issuer_clean] = data
                return data
            logger.warning("Failed to fetch OIDC discovery from %s: HTTP %s", discovery_url, resp.status_code)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Error fetching OIDC discovery from %s: %s", discovery_url, exc)

    raise HTTPException(status_code=502, detail="无法获取可信的 OIDC discovery 配置")


def _validate_id_token(token, jwks, provider, discovery, nonce, access_token):
    from authlib.jose import JsonWebToken
    allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
    algorithms = sorted(allowed.intersection(discovery.get("id_token_signing_alg_values_supported", ["RS256"])))
    if not algorithms or not isinstance(jwks, dict) or not jwks.get("keys"):
        raise HTTPException(401, "OIDC 签名算法或公钥无效")
    options = {"iss": {"essential": True, "value": discovery["issuer"]},
               "aud": {"essential": True, "value": provider.client_id},
               "sub": {"essential": True}, "iat": {"essential": True}, "exp": {"essential": True},
               "nonce": {"essential": True, "value": nonce}}
    claims = JsonWebToken(algorithms).decode(token, jwks, claims_options=options)
    claims.validate(leeway=30)
    if not isinstance(claims["sub"], str) or not claims["sub"] or len(claims["sub"]) > 255:
        raise HTTPException(401, "OIDC sub 无效")
    aud = claims["aud"]
    if ((isinstance(aud, list) and len(aud) > 1) or "azp" in claims) and claims.get("azp") != provider.client_id:
        raise HTTPException(401, "OIDC authorized party 不匹配")
    if "at_hash" in claims:
        algorithm = claims.header["alg"]
        bits = algorithm[-3:]
        digest = getattr(hashlib, "sha" + bits)(access_token.encode()).digest()
        expected = base64.urlsafe_b64encode(digest[:len(digest)//2]).rstrip(b"=").decode()
        if not hmac.compare_digest(expected, claims["at_hash"]):
            raise HTTPException(401, "OIDC access_token 不匹配")
    return claims


async def _begin_oidc(provider, request, session, link_user=None):
    oidc_cfg = await _get_oidc_config(provider.issuer)
    auth_endpoint = oidc_cfg.get("authorization_endpoint") or f"{provider.issuer.rstrip('/')}/api/oidc/authorization"

    redirect_uri = f"{str(request.base_url).rstrip('/')}/api/v1/auth/sso/{provider.name}/callback"
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    from sqlalchemy import delete
    session.exec(delete(OIDCLogin).where(OIDCLogin.expires_at < int(time.time())))
    login = OIDCLogin(id=state, provider_id=provider.id, issuer=provider.issuer,
                      client_id=provider.client_id, redirect_uri=redirect_uri,
                      nonce=nonce, code_verifier=verifier, expires_at=int(time.time()) + 300)
    if link_user is not None:
        token = _verify_token(request.cookies.get(SESSION_COOKIE, ""), session)
        if not token or token["uid"] != str(link_user.id):
            raise HTTPException(401, "Invalid session")
        login.link_user_id = link_user.id
        login.link_session_id = token["sid"]
        login.link_session_version = link_user.session_version
    session.add(login)
    session.commit()
    query = urlencode({"client_id": provider.client_id, "redirect_uri": redirect_uri,
                       "response_type": "code", "scope": "openid profile email", "state": state,
                       "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"})
    target_url = auth_endpoint + ("&" if "?" in auth_endpoint else "?") + query
    return target_url, state


def _set_oidc_state_cookie(response, state):
    response.set_cookie(
        key="famledger_oidc_state",
        value=state,
        max_age=300,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def _check_link_password(user, password, request):
    keys = (f"oidc-link:user:{user.id}", f"oidc-link:ip:{request.client.host if request.client else 'unknown'}")
    for key in keys:
        _check_login_rate_limit(key)
    if not user.password_hash or not password or not _check_password(password, user.password_hash):
        for key in keys:
            _record_login_failure(key)
        raise HTTPException(400, "本地账户密码不正确")
    for key in keys:
        _clear_login_failures(key)


def _link_session_user(login, request, session):
    provider = session.get(SSOProvider, login.provider_id)
    if (not provider or not provider.enabled or provider.issuer != login.issuer
            or provider.client_id != login.client_id):
        raise HTTPException(400, "OIDC 认证事务已失效或身份源不匹配")
    token = _verify_token(request.cookies.get(SESSION_COOKIE, ""), session)
    if (not token or token["uid"] != str(login.link_user_id)
            or token["sid"] != login.link_session_id or token["sv"] != login.link_session_version):
        raise HTTPException(401, "绑定会话已失效，请登录原账户后重试")
    return session.get(User, login.link_user_id)


def _check_email_domain(policy, email, userinfo, claims):
    if not policy["allowed_domains"]:
        return
    verified = (userinfo.get("email_verified") is True or
                (claims.get("email") == email and claims.get("email_verified") is True))
    if not verified:
        raise HTTPException(403, "域名准入要求身份源确认邮箱已验证")
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain not in policy["allowed_domains"]:
        raise HTTPException(403, f"您的邮箱域名 '@{domain}' 不在允许登录的域名白名单中")


def _save_identity_link(user, provider, uid, session):
    identity = session.exec(select(OIDCIdentity).where(
        OIDCIdentity.provider == provider.name, OIDCIdentity.uid == uid,
    )).first()
    if identity and identity.user_id != user.id:
        raise HTTPException(409, "该外部身份已关联其他账户，不能重复绑定")
    if identity is None:
        identity = OIDCIdentity(user_id=user.id, provider=provider.name, uid=uid)
    identity.issuer = provider.issuer
    identity.last_authenticated_at = datetime.now(timezone.utc)
    session.add(identity)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "该外部身份已关联其他账户，不能重复绑定") from None


def _pending_link(state, request, session):
    cookie_state = request.cookies.get("famledger_oidc_state")
    if not cookie_state or not hmac.compare_digest(cookie_state.encode(), state.encode()):
        raise HTTPException(400, "关联请求已失效，请重新使用 OIDC 登录")
    login = session.get(OIDCLogin, state)
    if (not login or not login.consumed or not login.link_uid or not login.link_user_id
            or login.link_session_id or login.expires_at < time.time()):
        raise HTTPException(400, "关联请求已失效，请重新使用 OIDC 登录")
    provider = session.get(SSOProvider, login.provider_id)
    user = session.get(User, login.link_user_id)
    if (not provider or not provider.enabled or provider.issuer != login.issuer
            or provider.client_id != login.client_id or not user or not user.is_active
            or user.session_version != login.link_session_version):
        raise HTTPException(400, "关联请求已失效，请重新使用 OIDC 登录")
    return login, provider, user


@router.get("/link-requests/{state}")
def get_link_request(state: str, request: Request, response: Response, session: Session = Depends(get_session)):
    _, provider, user = _pending_link(state, request, session)
    response.headers["Cache-Control"] = "no-store"
    return {"username": user.username, "provider_label": provider.label}


@router.post("/link-requests/complete")
def complete_link(data: OIDCLinkComplete, request: Request, response: Response,
                  session: Session = Depends(get_session)):
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    login, provider, user = _pending_link(data.state, request, session)
    _check_link_password(user, data.password, request)
    uid = login.link_uid
    claimed = session.exec(update(OIDCLogin).where(
        OIDCLogin.id == data.state, OIDCLogin.link_uid == uid,
        OIDCLogin.expires_at >= int(time.time()),
    ).values(link_uid=None, link_user_id=None, link_session_version=None)).rowcount
    if claimed != 1:
        raise HTTPException(400, "关联请求已失效，请重新使用 OIDC 登录")
    _save_identity_link(user, provider, uid, session)
    response.delete_cookie("famledger_oidc_state")
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(SESSION_COOKIE, _make_token(user.username, session_version=user.session_version, user_id=user.id),
                        httponly=True, samesite="lax", secure=COOKIE_SECURE, max_age=SESSION_TTL)
    return {"status": "linked", "username": user.username}


@router.get("/account-links")
def list_account_links(request: Request, response: Response, session: Session = Depends(get_session)):
    username = get_current_user(request, response, session)
    user = session.exec(select(User).where(User.username == username)).one()
    response.headers["Cache-Control"] = "no-store"
    return _account_link_options(user, session)


def _account_link_options(user, session):
    identities = session.exec(select(OIDCIdentity).where(OIDCIdentity.user_id == user.id)).all()
    linked = {(identity.provider, identity.issuer) for identity in identities}
    bound_names = {identity.provider for identity in identities}
    providers = session.exec(select(SSOProvider)).all()
    usable = {p.name for p in providers if p.enabled and (p.name, p.issuer) in linked}
    items = [{"name": p.name, "label": p.label, "enabled": p.enabled,
              "linked": p.name in usable, "has_binding": p.name in bound_names,
              "can_unlink": p.name in bound_names and (bool(user.password_hash) or bool(usable - {p.name}))}
             for p in providers if p.enabled or p.name in bound_names]
    # Keep stale bindings visible so users can remove a disabled or deleted IdP.
    for name in sorted(bound_names - {p.name for p in providers}):
        items.append({"name": name, "label": name, "enabled": False, "linked": False,
                      "has_binding": True, "can_unlink": bool(user.password_hash) or bool(usable)})
    return {"has_password": bool(user.password_hash), "providers": items}


@router.delete("/{provider_name}/link")
def unlink_account(provider_name: str, data: OIDCLinkRequest, request: Request, response: Response,
                   session: Session = Depends(get_session)):
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    session.expire_all()
    token = _verify_token(request.cookies.get(SESSION_COOKIE, ""), session)
    if not token:
        raise HTTPException(401, "Invalid session")
    user = session.get(User, uuid.UUID(token["uid"]))
    option = next((p for p in _account_link_options(user, session)["providers"]
                   if p["name"] == provider_name and p["has_binding"]), None)
    if option is None:
        raise HTTPException(404, "该单点登录服务尚未关联当前账户")
    if not option["can_unlink"]:
        raise HTTPException(409, "不能取消唯一可用的登录方式，请先设置本地密码或关联其他可用的登录服务")
    if user.password_hash:
        _check_link_password(user, data.current_password, request)
    identities = session.exec(select(OIDCIdentity).where(
        OIDCIdentity.user_id == user.id, OIDCIdentity.provider == provider_name,
    )).all()
    for identity in identities:
        session.delete(identity)
    # Revoke old sessions and pending links; keep this browser signed in.
    user.session_version += 1
    session.add(user)
    persist = token.get("persist") is True
    fresh_token = _make_token(user.username, persist=persist, session_version=user.session_version, user_id=user.id)
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(SESSION_COOKIE, fresh_token, httponly=True, samesite="lax", secure=COOKIE_SECURE,
                        max_age=PERSISTENT_TTL if persist else SESSION_TTL)
    return {"status": "unlinked"}


@router.post("/{provider_name}/link")
async def start_account_link(provider_name: str, data: OIDCLinkRequest, request: Request, response: Response,
                             session: Session = Depends(get_session)):
    username = get_current_user(request, response, session)
    user = session.exec(select(User).where(User.username == username)).one()
    if user.password_hash:
        _check_link_password(user, data.current_password, request)
    provider = session.exec(select(SSOProvider).where(
        SSOProvider.name == provider_name, SSOProvider.enabled == True,
    )).first()
    if not provider:
        raise HTTPException(404, "SSO Provider not found or disabled")
    target, state = await _begin_oidc(provider, request, session, link_user=user)
    _set_oidc_state_cookie(response, state)
    return {"authorize_url": target}


@router.get("/{provider_name}/authorize")
async def sso_authorize(provider_name: str, request: Request, session: Session = Depends(get_session)):
    """生成 OIDC 授权跳转 URL，动态通过 OIDC Discovery 发现端点。"""
    provider = session.exec(select(SSOProvider).where(
        SSOProvider.name == provider_name, SSOProvider.enabled == True,
    )).first()
    if not provider:
        raise HTTPException(404, "SSO Provider not found or disabled")
    target, state = await _begin_oidc(provider, request, session)
    response = RedirectResponse(target)
    _set_oidc_state_cookie(response, state)
    return response


@router.get("/{provider_name}/callback")
async def sso_callback(
    provider_name: str,
    request: Request,
    response: Response,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """
    处理 OIDC 回调，通过 Token 交换并获取 UserInfo，最后通过 JIT 自动建号并下发会话 Cookie。
    严格执行 state 参数校验，防御 CSRF 跨站请求伪造。
    """
    if not code:
        raise HTTPException(status_code=400, detail="缺少有效的 OIDC 授权码 (Authorization Code)")

    # 防御 CSRF：比对回调 state 与请求 Cookie
    cookie_state = request.cookies.get("famledger_oidc_state")
    if not state or not cookie_state or not hmac.compare_digest(state.encode(), cookie_state.encode()):
        raise HTTPException(status_code=400, detail="OIDC state 验证失败，可能存在跨站请求伪造 (CSRF) 攻击")

    response.delete_cookie(key="famledger_oidc_state")

    provider = session.exec(
        select(SSOProvider).where(SSOProvider.name == provider_name, SSOProvider.enabled == True)
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="SSO Provider not found")

    redirect_uri = f"{str(request.base_url).rstrip('/')}/api/v1/auth/sso/{provider.name}/callback"
    login = session.get(OIDCLogin, state)
    if (not login or login.consumed or login.expires_at < time.time()
            or login.provider_id != provider.id or login.issuer != provider.issuer
            or login.client_id != provider.client_id or login.redirect_uri != redirect_uri):
        raise HTTPException(400, "OIDC 认证事务已失效或身份源不匹配")
    if login.link_session_id:
        _link_session_user(login, request, session)
    nonce, verifier = login.nonce, login.code_verifier
    consumed = session.exec(update(OIDCLogin).where(
        OIDCLogin.id == state, OIDCLogin.consumed == False,
        OIDCLogin.expires_at >= int(time.time()),
    ).values(consumed=True)).rowcount
    session.commit()
    if consumed != 1:
        raise HTTPException(400, "OIDC 认证事务已经使用")

    import httpx
    oidc_cfg = await _get_oidc_config(provider.issuer)
    token_endpoint = oidc_cfg.get("token_endpoint")
    userinfo_endpoint = oidc_cfg.get("userinfo_endpoint")
    jwks_uri = oidc_cfg.get("jwks_uri")
    if not token_endpoint or not userinfo_endpoint or not jwks_uri:
        raise HTTPException(502, "OIDC discovery 缺少必要的端点")
    try:
        async with httpx.AsyncClient(verify=True, timeout=15.0, trust_env=False, follow_redirects=False) as client:
            plain_secret = decrypt_secret(provider.client_secret_encrypted)
            token_payload = {"grant_type": "authorization_code", "code": code,
                             "redirect_uri": redirect_uri, "code_verifier": verifier}
            token_resp = await _oidc_http(client, "POST", token_endpoint, data=token_payload,
                                         auth=(provider.client_id, plain_secret), headers={"Accept": "application/json"})
            if token_resp.status_code == 401 and "client_secret_post" in token_resp.text:
                token_resp = await _oidc_http(client, "POST", token_endpoint,
                    data={**token_payload, "client_id": provider.client_id, "client_secret": plain_secret},
                    headers={"Accept": "application/json"})
            if token_resp.status_code != 200:
                raise HTTPException(401, "OIDC 凭证交换失败")
            token_data = token_resp.json()
            if not token_data.get("id_token") or not token_data.get("access_token"):
                raise HTTPException(401, "OIDC 响应缺少身份凭证")
            keys_resp = await _oidc_http(client, "GET", jwks_uri)
            if keys_resp.status_code != 200:
                raise HTTPException(502, "无法获取 OIDC 验证公钥")
            claims = _validate_id_token(token_data["id_token"], keys_resp.json(), provider,
                                        oidc_cfg, nonce, token_data["access_token"])
            uinfo_resp = await _oidc_http(client, "GET", userinfo_endpoint,
                                         headers={"Authorization": f"Bearer {token_data['access_token']}"})
            if uinfo_resp.status_code != 200:
                raise HTTPException(401, "OIDC 用户信息获取失败")
            userinfo = uinfo_resp.json()
            if not isinstance(userinfo, dict) or userinfo.get("sub") != claims["sub"]:
                raise HTTPException(401, "OIDC UserInfo 与身份凭证不匹配")
    except HTTPException:
        raise
    except Exception:
        logger.warning("OIDC credential verification failed", exc_info=False)
        raise HTTPException(401, "OIDC 身份凭证验证失败")
    sub_uid = claims["sub"]
    email = userinfo.get("email") or f"{sub_uid}@{provider_name}.local"
    display_name = userinfo.get("name") or userinfo.get("preferred_username") or f"{provider.label} User"
    raw_username = userinfo.get("preferred_username") or f"{provider_name}_{sub_uid}"
    if not all(isinstance(value, str) for value in (email, display_name, raw_username)):
        raise HTTPException(400, "OIDC 用户字段必须为字符串")
    if len(email) > 255:
        raise HTTPException(400, "OIDC 邮箱长度超出限制")
    display_name = display_name[:100]
    username = "".join(c for c in raw_username if c.isalnum() or c in ("_", "-")).lower()
    identity_suffix = hashlib.sha256((provider.issuer + "\0" + sub_uid).encode()).hexdigest()[:16]
    if not username:
        username = "oidc_" + identity_suffix
    elif len(username) > 50:
        username = username[:33] + "_" + identity_suffix

    # Serialize identity changes with unlink, after the network calls. A callback
    # started before unlink must not revive a binding or issue a new valid session.
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    session.expire_all()
    login = session.get(OIDCLogin, state)
    provider = session.exec(select(SSOProvider).where(SSOProvider.name == provider_name)).first()
    if (not login or not provider or not provider.enabled
            or provider.id != login.provider_id or provider.issuer != login.issuer or provider.client_id != login.client_id
            or login.expires_at < time.time()):
        raise HTTPException(400, "OIDC 认证事务已失效或身份源不匹配")

    if login.link_session_id:
        # Re-read after the external HTTP calls: password changes, logout and
        # provider changes must invalidate an in-flight account link.
        user = _link_session_user(login, request, session)
        _check_email_domain(_jit_policy(provider.settings), email, userinfo, claims)
        _save_identity_link(user, provider, sub_uid, session)
        result = RedirectResponse("/settings?tab=profile&sso_link=success", status_code=302)
        result.delete_cookie("famledger_oidc_state")
        result.headers["Cache-Control"] = "no-store"
        return result

    # 查找或绑定 Identity
    identity = session.exec(
        select(OIDCIdentity).where(OIDCIdentity.provider == provider_name, OIDCIdentity.uid == sub_uid)
    ).first()

    if identity:
        if identity.issuer != provider.issuer:
            raise HTTPException(status_code=409, detail="身份源 issuer 已变更，请重新绑定身份")
        user = session.get(User, identity.user_id)
        if not user:
            raise HTTPException(status_code=401, detail="关联的用户账户已不存在，请重新认证")
        # 刷新认证时间
        identity.last_authenticated_at = datetime.now(timezone.utc)
        session.add(identity)
    else:
        # Provider policies are stored in the settings JSON, not model attributes.
        policy = _jit_policy(provider.settings)
        # Email selects the suggested local account; the local password is
        # still required. Never attach an identity using email or name alone.
        candidates = session.exec(select(User).where(func.lower(User.email) == email.lower())).all()
        if len(candidates) > 1:
            raise HTTPException(409, "邮箱对应多个本地账户，请先登录原账户后在个人设置中关联")
        candidate = candidates[0] if candidates else session.exec(
            select(User).where(func.lower(User.username) == username.lower())
        ).first()
        if candidate:
            _check_email_domain(policy, email, userinfo, claims)
            if not candidate.is_active:
                raise HTTPException(403, "关联账号已停用")
            if not candidate.password_hash:
                raise HTTPException(409, "该账户没有本地密码，请使用已有登录方式登录后在个人设置中关联")
            login.link_user_id = candidate.id
            login.link_uid = sub_uid
            login.link_session_version = candidate.session_version
            login.expires_at = int(time.time()) + 300
            session.add(login)
            session.commit()
            result = RedirectResponse(f"/oidc-link?state={state}", status_code=302)
            _set_oidc_state_cookie(result, state)
            return result
        if not policy["allow_jit"]:
            raise HTTPException(status_code=403, detail="该身份源已禁用新用户自动开户 (JIT)，请联系系统管理员")

        _check_email_domain(policy, email, userinfo, claims)

        # JIT: 创建独立新用户与 Identity（原子事务提交）
        user = User(
            family_id=None,
            username=username,
            email=email,
            display_name=display_name,
            role=policy["default_role"],
        )
        session.add(user)
        session.flush()

        from models import UserPreference
        pref = UserPreference(username=user.username, currency="CNY", has_chosen_currency=False, has_chosen_language=False)
        session.add(pref)

        identity = OIDCIdentity(
            user_id=user.id,
            provider=provider_name,
            uid=sub_uid,
            issuer=provider.issuer,
            last_authenticated_at=datetime.now(timezone.utc),
        )
        session.add(identity)

    # 下发会话 Cookie
    if not user.is_active:
        raise HTTPException(403, "关联账号已停用")
    token = _make_token(user.username, session_version=user.session_version, user_id=user.id)
    session.commit()
    redirect_resp = RedirectResponse(url="/", status_code=302)
    redirect_resp.delete_cookie(key="famledger_oidc_state")
    redirect_resp.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=SESSION_TTL,
    )
    return redirect_resp

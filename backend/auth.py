import base64
import collections
import hashlib
import hmac
import json
import os
import re
import tempfile
import threading
import time
import uuid
import secrets
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from config import SECRET_KEY
import database
from database import get_session
from models import User, ApiKey, RevokedSession
from users import get_user_by_username, get_user_count, build_user_map, is_primary_user
from services.audit import audit_logger

IS_DEV = os.getenv("ENV", "development") == "development"

# COOKIE_SECURE: override the automatic dev/prod detection when needed.
# Set COOKIE_SECURE=false explicitly for production HTTP (local network) deployments.
_cookie_secure_env = os.getenv("COOKIE_SECURE")
if _cookie_secure_env is not None:
    COOKIE_SECURE = _cookie_secure_env.lower() in ("true", "1", "yes")
else:
    COOKIE_SECURE = not IS_DEV

from database import DATA_DIR as _DATA_DIR
AVATARS_DIR = str(_DATA_DIR / "uploads" / "avatars")
os.makedirs(AVATARS_DIR, exist_ok=True)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

MAGIC_BYTES = {
    ".jpg":  [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png":  [b"\x89PNG"],
    ".gif":  [b"GIF87a", b"GIF89a"],
    ".webp": [b"RIFF"],
}

_SAFE_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_SAFE_DISPLAY_NAME_RE = re.compile(r"^[a-zA-Z0-9 '\-\.À-ÖØ-öø-ÿ\u4e00-\u9fa5]+$")

SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What city were you born in?",
    "What was your childhood nickname?",
    "What is the name of your favorite teacher?",
    "What was the make of your first car?",
]

logger = __import__('logging').getLogger(__name__)
router = APIRouter()


def hash_password(plain: str) -> str:
    """Generate a bcrypt hash for a plaintext password."""
    # Versioned prehash avoids bcrypt's silent 72-byte truncation.
    digest = base64.b64encode(hashlib.sha256(plain.encode("utf-8")).digest())
    return "bcrypt-sha256$" + bcrypt.hashpw(digest, bcrypt.gensalt()).decode()


def _check_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        if hashed.startswith("bcrypt-sha256$"):
            digest = base64.b64encode(hashlib.sha256(plain.encode("utf-8")).digest())
            return bcrypt.checkpw(digest, hashed[len("bcrypt-sha256$"):].encode())
        return False
    except (ValueError, TypeError):
        return False


def _hash_answer(answer: str) -> str:
    """Normalize and hash a security answer."""
    normalized = answer.strip().lower()
    return hash_password(normalized)


def _check_answer(answer: str, hashed: str) -> bool:
    """Verify a security answer against its hash."""
    normalized = answer.strip().lower()
    try:
        return _check_password(normalized, hashed)
    except (ValueError, TypeError):
        return False


def _validate_magic(data: bytes, ext: str) -> bool:
    """Verify file content magic bytes match the claimed extension."""
    signatures = MAGIC_BYTES.get(ext, [])
    for sig in signatures:
        if data[: len(sig)] == sig:
            if ext == ".webp":
                return len(data) >= 12 and data[8:12] == b"WEBP"
            return True
    return False


SESSION_COOKIE = "famledger_session"
SESSION_TTL = 60 * 60 * 8  # 8 hours
PERSISTENT_TTL = 60 * 60 * 24 * 365  # 1 year
# Non-persistent sessions slide forward on activity instead of hard-expiring
# 8 hours from login: once a cookie is older than this, get_current_user
# reissues it with a fresh timestamp. Not on every single request, so we
# don't churn an identical Set-Cookie header for no benefit.
SESSION_REFRESH_THRESHOLD = 60 * 30  # 30 minutes


def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _make_token(username: str, persist: bool = False, session_version: int = 0,
                user_id=None, session_id=None) -> str:
    if user_id is None:
        with Session(database.engine) as session:
            user = session.exec(select(User).where(User.username == username)).first()
            user_id = user.id if user else None
    raw_json = json.dumps({"user": username, "uid": str(user_id) if user_id else None,
                           "sid": session_id or secrets.token_hex(24), "ts": int(time.time()),
                           "persist": persist, "sv": session_version}, separators=(",", ":"))
    payload = base64.urlsafe_b64encode(raw_json.encode()).decode("ascii")
    return f"{payload}|{_sign(payload)}"


def _verify_token(token: str, session: Session | None = None) -> dict | None:
    if session is None:
        with Session(database.engine) as db_session:
            return _verify_token(token, db_session)
    try:
        payload, signature = token.strip('"').rsplit("|", 1)
        if not hmac.compare_digest(_sign(payload), signature):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        if not isinstance(data, dict) or not isinstance(data.get("sid"), str):
            return None
        uid = uuid.UUID(data["uid"])
        user = session.get(User, uid)
        if not user or not user.is_active or data.get("sv") != user.session_version:
            return None
        if session.get(RevokedSession, data["sid"]):
            return None
        ts = data["ts"]
        ttl = PERSISTENT_TTL if data.get("persist") is True else SESSION_TTL
        if not isinstance(ts, int) or ts > time.time() + 60 or time.time() - ts > ttl:
            return None
        # Resolve the current login name by immutable ID, never by aliases.
        data["user"] = user.username
        return data
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        return None


def get_current_user(request: Request, response: Response, session: Session = Depends(get_session)) -> str:
    """Returns the login username of the authenticated user.

    Non-persistent sessions ("stay signed in" off) slide forward on activity:
    once the cookie is older than SESSION_REFRESH_THRESHOLD, it's silently
    reissued with a fresh timestamp, so an active user isn't abruptly signed
    out mid-session just because SESSION_TTL elapsed since login. Persistent
    ("stay signed in") sessions already last a year and don't need this.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    data = _verify_token(token, session=session)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid session")
    username = data["user"]

    if not data.get("persist") and time.time() - data.get("ts", 0) > SESSION_REFRESH_THRESHOLD:
        fresh_token = _make_token(username, persist=False, session_version=data["sv"],
                                  user_id=data["uid"], session_id=data["sid"])
        response.set_cookie(
            key=SESSION_COOKIE,
            value=fresh_token,
            httponly=True,
            samesite="lax",
            secure=COOKIE_SECURE,
            max_age=SESSION_TTL,
        )

    return username


# ── Forgot-password rate limiter (CR-2) ──────────────────────────────

_reset_attempts: dict[str, list[float]] = collections.defaultdict(list)
_reset_lock = threading.Lock()
RESET_MAX_ATTEMPTS = 5
RESET_WINDOW_SECONDS = 300  # 5 minutes


def _check_reset_rate_limit(username: str, client_ip: Optional[str] = None) -> None:
    now = time.time()
    with _reset_lock:
        if client_ip:
            ip_attempts = [t for t in _reset_attempts[f"r_ip:{client_ip}"] if now - t < RESET_WINDOW_SECONDS]
            _reset_attempts[f"r_ip:{client_ip}"] = ip_attempts
            if len(ip_attempts) >= 15:
                raise HTTPException(status_code=429, detail="Too many attempts from this IP. Try again in 5 minutes.")

        key = f"user:{username}" if not client_ip else f"user:{client_ip}:{username}"
        attempts = [t for t in _reset_attempts[key] if now - t < RESET_WINDOW_SECONDS]
        _reset_attempts[key] = attempts
        if len(attempts) >= RESET_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again in 5 minutes.")


def _record_reset_failure(username: str, client_ip: Optional[str] = None) -> None:
    now = time.time()
    with _reset_lock:
        if client_ip:
            _reset_attempts[f"r_ip:{client_ip}"].append(now)
            _reset_attempts[f"user:{client_ip}:{username}"].append(now)
        else:
            _reset_attempts[f"user:{username}"].append(now)


def _clear_reset_attempts(username: str, client_ip: Optional[str] = None) -> None:
    with _reset_lock:
        if client_ip:
            _reset_attempts.pop(f"user:{client_ip}:{username}", None)
        else:
            _reset_attempts.pop(f"user:{username}", None)


def _check_question_rate_limit(client_ip: str) -> None:
    now = time.time()
    with _reset_lock:
        attempts = [t for t in _reset_attempts[f"q_ip:{client_ip}"] if now - t < RESET_WINDOW_SECONDS]
        _reset_attempts[f"q_ip:{client_ip}"] = attempts
        if len(attempts) >= 30:
            raise HTTPException(status_code=429, detail="Too many question lookup attempts. Try again in 5 minutes.")
        _reset_attempts[f"q_ip:{client_ip}"].append(now)


# ── Login rate limiter (防暴力破解) ────────────────────────────────────
_login_attempts: dict[str, list[float]] = collections.defaultdict(list)
_login_lock = threading.Lock()
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def _check_login_rate_limit(key: str) -> None:
    now = time.time()
    with _login_lock:
        attempts = [t for t in _login_attempts[key] if now - t < LOGIN_WINDOW_SECONDS]
        _login_attempts[key] = attempts
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="登录失败次数过多，请 5 分钟后再试")


def _record_login_failure(key: str) -> None:
    with _login_lock:
        _login_attempts[key].append(time.time())


def _clear_login_failures(key: str) -> None:
    with _login_lock:
        _login_attempts.pop(key, None)


# ── Registration ──────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    username: str
    display_name: str
    password: str
    security_question: str
    security_answer: str


@router.post("/auth/register", status_code=201)
def register(data: RegisterRequest, response: Response, session: Session = Depends(get_session)):
    # Validate username format
    if not _SAFE_USERNAME_RE.match(data.username):
        raise HTTPException(status_code=422, detail="Username must be alphanumeric (underscores and hyphens allowed)")
    if len(data.username) < 2 or len(data.username) > 50:
        raise HTTPException(status_code=422, detail="Username must be 2-50 characters")

    # Validate display name format
    if not _SAFE_DISPLAY_NAME_RE.match(data.display_name):
        raise HTTPException(status_code=422, detail="Display name may only contain letters, numbers, spaces, apostrophes, hyphens, and periods")
    if len(data.display_name) < 2 or len(data.display_name) > 100:
        raise HTTPException(status_code=422, detail="Display name must be 2-100 characters")

    # Validate password
    if len(data.password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")
    if len(data.password) > 128:
        raise HTTPException(status_code=422, detail="Password must be 128 characters or fewer")

    # Validate security question
    if not data.security_question or len(data.security_question) > 300:
        raise HTTPException(status_code=422, detail="Security question is required (max 300 characters)")

    # Validate security answer
    if not data.security_answer.strip():
        raise HTTPException(status_code=422, detail="Security answer is required")

    # Uncap user limit - FamLedger supports unlimited multi-user family members
    password_hash = hash_password(data.password)
    answer_hash = _hash_answer(data.security_answer)
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    count = get_user_count(session)

    # Check uniqueness
    if get_user_by_username(session, data.username):
        raise HTTPException(status_code=409, detail="Username already taken")
    from users import get_user_by_display_name
    if get_user_by_display_name(session, data.display_name):
        raise HTTPException(status_code=409, detail="Display name already taken")

    # 仅当系统完全没有用户时（创世用户），才自动创建并加入默认家庭组作为系统所有者
    user_family_id = None
    if count == 0:
        from models import Family
        default_family = session.exec(select(Family)).first() if "select" in globals() else None
        if not default_family:
            from sqlmodel import select as sm_select
            default_family = session.exec(sm_select(Family)).first()
        if not default_family:
            default_family = Family(name="我的家庭", currency="CNY")
            session.add(default_family)
            session.flush()
        user_family_id = default_family.id
        user_role = "admin"
    else:
        # 新注册普通用户属于独立账号，绝不默认加入任何现有家庭组
        user_family_id = None
        user_role = "member"

    user = User(
        family_id=user_family_id,
        username=data.username,
        display_name=data.display_name,
        role=user_role,
        password_hash=password_hash,
        security_question=data.security_question,
        security_answer_hash=answer_hash,
    )
    session.add(user)
    session.flush()

    # 新注册用户标记 has_chosen_currency=False，要求首次登录必须主动选择交易币种
    from models import UserPreference
    initial_pref = UserPreference(
        username=user.username,
        currency="CNY",
        has_chosen_currency=False,
        has_chosen_language=False,
    )
    session.add(initial_pref)

    session.commit()
    session.refresh(user)

    # Auto-login
    token = _make_token(user.username, session_version=user.session_version, user_id=user.id)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=SESSION_TTL,
    )
    return {
        "id": str(user.id),
        "family_id": str(user.family_id) if user.family_id else None,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "user_map": build_user_map(session, family_id=user.family_id),
    }


@router.get("/auth/account-status")
def account_status(session: Session = Depends(get_session)):
    """公开端点：系统是否存在账户、注册是否开放（不暴露全站精确用户数）。"""
    count = get_user_count(session)
    return {
        "has_users": count > 0,
        "is_first_user": count == 0,
        "registration_open": True,
    }



@router.get("/auth/security-questions")
def list_security_questions():
    """Return the preset security questions."""
    return {"questions": SECURITY_QUESTIONS}


# ── Login / Logout / Me ──────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(data: LoginRequest, request: Request, response: Response, session: Session = Depends(get_session)):
    import logging
    logger = logging.getLogger("auth.login")
    logger.info("Login attempt for username=%s", data.username)

    # 防暴力破解限流校验
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{data.username.strip().lower()}"
    _check_login_rate_limit(rate_key)

    user = get_user_by_username(session, data.username)

    # 严格单一密码校验：严格区分大小写，严格比对用户当前哈希，绝无旁路后门
    if not user or not user.password_hash or not _check_password(data.password, user.password_hash):
        logger.warning("Authentication failed for username=%s", data.username)
        _record_login_failure(rate_key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        logger.warning("Inactive user attempted login: username=%s", data.username)
        raise HTTPException(status_code=403, detail="该账号已被停用，无法登录")

    _clear_login_failures(rate_key)

    persist = user.stay_signed_in
    token = _make_token(user.username, persist=persist, session_version=user.session_version, user_id=user.id)
    ttl = PERSISTENT_TTL if persist else SESSION_TTL

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=ttl,
    )
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "user_map": build_user_map(session, family_id=user.family_id),
    }


@router.post("/auth/logout")
def logout(request: Request, response: Response, session: Session = Depends(get_session)):
    token = request.cookies.get(SESSION_COOKIE)
    data = _verify_token(token, session) if token else None
    if data:
        from sqlalchemy import delete
        now = int(time.time())
        session.exec(delete(RevokedSession).where(RevokedSession.expires_at < now))
        if session.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        session.execute(insert(RevokedSession).values(id=data["sid"], expires_at=now + PERSISTENT_TTL).on_conflict_do_nothing())
        session.commit()
    response.delete_cookie(key=SESSION_COOKIE)
    return {"ok": True}


@router.get("/auth/me")
def get_me(request: Request, response: Response, session: Session = Depends(get_session)):
    username = get_current_user(request, response, session)
    user = get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    has_avatar = _find_avatar(user.username) is not None
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "theme": user.theme,
        "locale": user.locale,
        "avatar_url": f"/api/auth/avatar/{user.username}" if has_avatar else None,
        "user_map": build_user_map(session, family_id=user.family_id),
        "stay_signed_in": user.stay_signed_in,
    }


class UpdateProfileRequest(BaseModel):
    username: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None


@router.put("/auth/profile")
def update_profile(
    data: UpdateProfileRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    current_uname = get_current_user(request, response, session)
    user = get_user_by_username(session, current_uname)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    old_uname = user.username
    need_reissue_token = False

    # 1. 修改用户名 / 名字
    if data.username and data.username.strip() and data.username.strip() != user.username:
        new_uname = data.username.strip()
        if not _SAFE_USERNAME_RE.match(new_uname):
            raise HTTPException(status_code=400, detail="用户名仅支持字母、数字、下划线及连字符")
        if len(new_uname) < 2 or len(new_uname) > 50:
            raise HTTPException(status_code=400, detail="用户名长度须在 2 到 50 个字符之间")

        existing = session.exec(select(User).where(func.lower(User.username) == new_uname.lower(), User.id != user.id)).first()
        if existing:
            raise HTTPException(status_code=409, detail="该用户名已被占用，请使用其他用户名")

        user.username = new_uname
        need_reissue_token = True

        # 迁移用户偏好配置 UserPreference
        from models import UserPreference
        pref = session.exec(select(UserPreference).where(UserPreference.username == old_uname)).first()
        if pref:
            pref.username = new_uname
            session.add(pref)

        # 迁移已有头像文件
        old_avatar = _find_avatar(old_uname)
        if old_avatar:
            ext = os.path.splitext(old_avatar)[1]
            new_avatar = os.path.join(AVATARS_DIR, f"{new_uname}{ext}")
            try:
                os.rename(old_avatar, new_avatar)
            except Exception:
                pass

    # 2. 修改昵称
    if data.display_name is not None and data.display_name.strip():
        new_dname = data.display_name.strip()
        if len(new_dname) > 100:
            raise HTTPException(status_code=400, detail="昵称长度不可超过 100 个字符")
        user.display_name = new_dname

    # 3. 修改邮箱
    if data.email is not None:
        clean_email = data.email.strip() if data.email.strip() else None
        if clean_email:
            if "@" not in clean_email or len(clean_email) > 255:
                raise HTTPException(status_code=400, detail="请输入有效的邮箱地址")
            existing_email = session.exec(select(User).where(func.lower(User.email) == clean_email.lower(), User.id != user.id)).first()
            if existing_email:
                raise HTTPException(status_code=409, detail="该邮箱已被其他账号绑定")
        user.email = clean_email

    # 4. 修改密码
    if data.new_password:
        if user.password_hash:
            if not data.current_password:
                raise HTTPException(status_code=400, detail="修改密码时必须输入当前原密码")
            if not _check_password(data.current_password, user.password_hash):
                raise HTTPException(status_code=400, detail="当前原密码输入错误")

        if len(data.new_password) < 6:
            raise HTTPException(status_code=422, detail="新密码长度不能少于 6 位")
        if len(data.new_password) > 128:
            raise HTTPException(status_code=422, detail="新密码长度不能超过 128 位")

        user.password_hash = hash_password(data.new_password)
        user.session_version = (user.session_version or 0) + 1
        need_reissue_token = True

        # 同步撤销当前用户的所有活跃 API Key
        api_keys = session.exec(select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.is_revoked == False)).all()
        for ak in api_keys:
            ak.is_revoked = True
            session.add(ak)

    session.add(user)
    session.commit()
    session.refresh(user)

    if need_reissue_token:
        persist = user.stay_signed_in
        token = _make_token(user.username, persist=persist, session_version=user.session_version, user_id=user.id)
        ttl = PERSISTENT_TTL if persist else SESSION_TTL
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            httponly=True,
            samesite="lax",
            secure=COOKIE_SECURE,
            max_age=ttl,
        )

    has_avatar = _find_avatar(user.username) is not None
    return {
        "ok": True,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "avatar_url": f"/api/auth/avatar/{user.username}" if has_avatar else None,
        "user_map": build_user_map(session, family_id=user.family_id),
    }


# ── Forgot Password ──────────────────────────────────────────────────


class ForgotPasswordQuestionRequest(BaseModel):
    username: str


@router.post("/auth/forgot-password/question")
def forgot_password_question(
    data: ForgotPasswordQuestionRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    client_ip = request.client.host if request.client else "unknown"
    _check_question_rate_limit(client_ip)

    user = get_user_by_username(session, data.username)
    if not user:
        # Deterministically map nonexistent usernames to one of the preset questions
        # so attackers can't detect nonexistent users through fixed defaults or nulls.
        idx = abs(hash(data.username)) % len(SECURITY_QUESTIONS)
        return {"security_question": SECURITY_QUESTIONS[idx]}
    return {"security_question": user.security_question}


class ForgotPasswordResetRequest(BaseModel):
    username: str
    security_answer: str
    new_password: str


@router.post("/auth/forgot-password/reset")
def forgot_password_reset(
    data: ForgotPasswordResetRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    client_ip = request.client.host if request.client else "unknown"
    _check_reset_rate_limit(data.username, client_ip=client_ip)

    user = get_user_by_username(session, data.username)
    if not user:
        # Record a failure and return 401 (same as wrong answer) so attackers
        # can't enumerate valid usernames via 404 vs 401 differences.
        _record_reset_failure(data.username, client_ip=client_ip)
        raise HTTPException(status_code=401, detail="Incorrect security answer")

    if not _check_answer(data.security_answer, user.security_answer_hash):
        _record_reset_failure(data.username, client_ip=client_ip)
        raise HTTPException(status_code=401, detail="Incorrect security answer")

    _clear_reset_attempts(data.username, client_ip=client_ip)

    if len(data.new_password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")
    if len(data.new_password) > 128:
        raise HTTPException(status_code=422, detail="Password must be 128 characters or fewer")

    user.password_hash = hash_password(data.new_password)
    user.session_version = (user.session_version or 0) + 1
    session.add(user)

    # 撤销所有活跃 API Key
    api_keys = session.exec(select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.is_revoked == False)).all()
    for ak in api_keys:
        ak.is_revoked = True
        session.add(ak)

    session.commit()
    return {"ok": True}


# ── Change Password ──────────────────────────────────────────────────


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.put("/auth/change-password")
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    username = get_current_user(request, response, session)
    user = get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not _check_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")
    if len(data.new_password) > 128:
        raise HTTPException(status_code=422, detail="Password must be 128 characters or fewer")

    user.password_hash = hash_password(data.new_password)
    user.session_version = (user.session_version or 0) + 1
    session.add(user)

    # 撤销所有活跃 API Key
    api_keys = session.exec(select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.is_revoked == False)).all()
    for ak in api_keys:
        ak.is_revoked = True
        session.add(ak)

    session.commit()

    # Reissue a fresh token so the current session survives the version bump
    token = _make_token(username, persist=user.stay_signed_in, session_version=user.session_version, user_id=user.id)
    ttl = PERSISTENT_TTL if user.stay_signed_in else SESSION_TTL
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=ttl,
    )
    return {"ok": True}


# ── Stay Signed In ───────────────────────────────────────────────────


class StaySignedInRequest(BaseModel):
    enabled: bool


@router.put("/auth/stay-signed-in")
def update_stay_signed_in(
    data: StaySignedInRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    username = get_current_user(request, response, session)
    user = get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user.stay_signed_in = data.enabled
    session.add(user)
    session.commit()

    # Reissue token with updated persistence
    token = _make_token(username, persist=data.enabled, session_version=user.session_version, user_id=user.id)
    ttl = PERSISTENT_TTL if data.enabled else SESSION_TTL
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=ttl,
    )
    return {"ok": True, "stay_signed_in": data.enabled}


# ── Account Deletion ─────────────────────────────────────────────────


class DeleteAccountRequest(BaseModel):
    password: str
    data_action: str  # "delete" or "anonymize"


@router.delete("/auth/account")
def delete_account(
    data: DeleteAccountRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    username = get_current_user(request, response, session)
    user = get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.password_hash:
        if not data.password or not _check_password(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect password")

    if data.data_action not in ("delete", "anonymize"):
        raise HTTPException(status_code=422, detail="data_action must be 'delete' or 'anonymize'")

    from services.membership import ensure_can_leave
    ensure_can_leave(session, user)

    from models import UserPreference, Settings, ApiKey, AccountShare, UserSession, OIDCIdentity, PersonalDebt, Account, Transaction
    from sqlmodel import select

    display_name = user.display_name

    expenses_deleted = 0
    expenses_anonymized = 0
    expenses_split_corrected = 0
    expenses_reassigned = 0
    income_affected = 0

    # 清理当前用户的 API Keys
    api_keys = session.exec(select(ApiKey).where(ApiKey.user_id == user.id)).all()
    for ak in api_keys:
        session.delete(ak)

    # 清理关联的 OIDCIdentity
    oidc_identities = session.exec(select(OIDCIdentity).where(OIDCIdentity.user_id == user.id)).all()
    for oi in oidc_identities:
        session.delete(oi)

    # 清理当前用户的账户共享关系
    shares = session.exec(select(AccountShare).where(AccountShare.user_id == user.id)).all()
    for s in shares:
        session.delete(s)

    # Anonymous data stays in its original family under an unloginable archive
    # identity. Never hand private records to an unrelated surviving user.
    debts = session.exec(select(PersonalDebt).where(PersonalDebt.owner_id == user.id)).all()
    user_accounts = session.exec(select(Account).where(Account.owner_id == user.id)).all()
    if data.data_action == "delete":
        from services.financial_deletion import delete_account_data
        transactions = delete_account_data(session, [account.id for account in user_accounts])
        expenses_deleted = sum(txn.transaction_type != "income" for txn in transactions)
        income_affected = sum(txn.transaction_type == "income" for txn in transactions)
        for debt in debts:
            session.delete(debt)
    else:
        import uuid
        archives = {}
        def archive_owner(family_id):
            if family_id not in archives:
                archived = User(username=f"archived_{uuid.uuid4().hex}", display_name="已注销用户",
                                family_id=family_id, role="archived", password_hash=None, is_active=False)
                session.add(archived)
                session.flush()
                archives[family_id] = archived
            return archives[family_id]
        for debt in debts:
            debt.owner_id = archive_owner(debt.family_id).id
            debt.counterparty = "已匿名化往来对象"
            debt.notes = None
            session.add(debt)
        for account in user_accounts:
            account.owner_id = archive_owner(account.family_id).id
            account.name = "已匿名化账户"
            account.institution_name = None
            account.external_identifier = None
            session.add(account)
            from models import Loan, TransactionSplit
            for loan in session.exec(select(Loan).where(Loan.account_id == account.id)).all():
                loan.lender_name = None
                session.add(loan)
            for txn in session.exec(select(Transaction).where(Transaction.account_id == account.id)).all():
                txn.narration = "已匿名化流水"
                txn.notes = None
                txn.tags = []
                for split in session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == txn.id)).all():
                    split.notes = None
                    session.add(split)
                txn.extra = {key: value for key, value in (txn.extra or {}).items()
                             if key in ("direction", "is_initial")}
                session.add(txn)
                expenses_anonymized += 1
            expenses_reassigned += 1

    # 清理当前用户的 API Key
    user_keys = session.exec(select(ApiKey).where(ApiKey.user_id == user.id)).all()
    for ak in user_keys:
        session.delete(ak)

    # 清理当前用户的账户共享记录
    from models import AccountShare
    user_shares = session.exec(select(AccountShare).where(AccountShare.user_id == user.id)).all()
    for ash in user_shares:
        session.delete(ash)

    # 清理当前用户的用户首选项
    prefs = session.exec(select(UserPreference).where(UserPreference.username == username)).all()
    for p in prefs:
        session.delete(p)

    # 清理当前用户的会话记录
    sessions = session.exec(select(UserSession).where(UserSession.user_id == user.id)).all()
    for s in sessions:
        session.delete(s)

    # 清理涉及当前用户的家庭组邀请记录 FamilyInvitation (发起、受邀或处理)
    from models import FamilyInvitation, Family
    invitations = session.exec(
        select(FamilyInvitation).where(
            (FamilyInvitation.invitee_user_id == user.id)
            | (FamilyInvitation.inviter_user_id == user.id)
            | (FamilyInvitation.processed_by_user_id == user.id)
        )
    ).all()
    for inv in invitations:
        session.delete(inv)

    # 解除家庭表中可能指向该用户的弱引用 (personal_owner_user_id / dissolved_by_user_id)
    fam_refs = session.exec(
        select(Family).where(
            (Family.personal_owner_user_id == user.id)
            | (Family.dissolved_by_user_id == user.id)
        )
    ).all()
    for fam in fam_refs:
        if fam.personal_owner_user_id == user.id:
            fam.personal_owner_user_id = None
        if fam.dissolved_by_user_id == user.id:
            fam.dissolved_by_user_id = None
        session.add(fam)

    # Find the avatar now, but don't remove the file until after the DB commit
    # below succeeds — deleting it first would leave the account intact but
    # the avatar file gone if the commit fails.
    existing_avatar = _find_avatar(username)

    # Sources from retained/shared accounts must no longer retry with a deleted actor.
    from models import PendingFxTransaction
    for pending in session.exec(select(PendingFxTransaction).where(PendingFxTransaction.requested_by_user_id == user.id)).all():
        pending.requested_by_user_id = None
        if pending.status == "pending_fx":
            pending.status = "canceled"
        pending.payload = {}
        pending.last_error = None
        session.add(pending)
    # Delete the user
    from services.schedules import delete_plans_for_owner
    delete_plans_for_owner(session, user.id)
    session.delete(user)

    # Count remaining users before the commit. The deleted user is still in the
    # DB at this point (session.delete queues the deletion; the row goes away on
    # commit), so we subtract 1 to get the post-commit count.
    session.flush()
    remaining = get_user_count(session)
    if remaining <= 1:
        settings = session.get(Settings, 1)
        if settings:
            settings.app_mode = "personal"
            session.add(settings)

    scope = {
        "data_action": data.data_action,
        "deleted_username": username,
        "deleted_display_name": display_name,
        "expenses_deleted": expenses_deleted,
        "expenses_anonymized": expenses_anonymized,
        "expenses_split_corrected": expenses_split_corrected,
        "expenses_reassigned": expenses_reassigned,
        "income_affected": income_affected,
    }
    # Account deletion is the single most destructive mutation in the app — it
    # must be audited like any other mutation, with the full scope of what it
    # touched so the survivor's balance/analytics can be reconciled after the fact.
    session.commit()
    audit_logger.log("ACCOUNT_DELETE", username, scope)

    # Only remove the avatar file now that the DB commit has actually
    # succeeded — a failed commit above would otherwise leave the account
    # intact but the avatar gone.
    if existing_avatar:
        os.remove(existing_avatar)

    response.delete_cookie(key=SESSION_COOKIE)
    return {"ok": True, **scope}


# ── Avatar ───────────────────────────────────────────────────────────


def _find_avatar(username: str) -> str | None:
    """Return the path to an existing avatar file for the given username, or None."""
    for ext in ALLOWED_EXTENSIONS:
        path = os.path.join(AVATARS_DIR, f"{username}{ext}")
        if os.path.isfile(path):
            return path
    return None


@router.post("/auth/avatar")
async def upload_avatar(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    username = get_current_user(request, response, session)

    # Authenticate and bound the entire body before any multipart parsing.
    body_limit = MAX_FILE_SIZE + 64 * 1024
    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) < 0 or int(declared_length) > body_limit:
                raise HTTPException(413, "Avatar request too large")
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > body_limit:
            raise HTTPException(413, "Avatar request too large")
        chunks.append(chunk)

    async def receive_body():
        return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

    bounded_request = Request(request.scope, receive_body)
    from starlette.datastructures import UploadFile as ParsedUploadFile
    async with bounded_request.form(max_files=1, max_fields=0, max_part_size=MAX_FILE_SIZE) as form:
        file = form.get("file")
        if not isinstance(file, ParsedUploadFile):
            raise HTTPException(422, "A single avatar file is required")
        filename = file.filename or ""
        contents = await file.read(MAX_FILE_SIZE + 1)

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed. Use: {', '.join(ALLOWED_EXTENSIONS)}")

    # Read one byte beyond the limit so we can distinguish "exactly at limit" from "over limit"
    # without loading an arbitrarily large file into memory first.
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 2 MB.")

    if not _validate_magic(contents, ext):
        raise HTTPException(
            status_code=400,
            detail="File content does not match the declared file type.",
        )

    if not _SAFE_USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    dest_path = Path(AVATARS_DIR).resolve() / f"{username}{ext}"
    if dest_path.parent != Path(AVATARS_DIR).resolve():
        raise HTTPException(status_code=400, detail="Invalid file path.")

    # Atomic write: write to a temp file then rename over the destination
    tmp_fd, tmp_path = tempfile.mkstemp(dir=AVATARS_DIR)
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(contents)
        os.replace(tmp_path, str(dest_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Clean up any stale avatar with a different extension
    for old_ext in ALLOWED_EXTENSIONS:
        old = os.path.join(AVATARS_DIR, f"{username}{old_ext}")
        if old != str(dest_path) and os.path.isfile(old):
            os.remove(old)

    return {"ok": True}


@router.get("/auth/avatar/{username}")
def get_avatar(username: str, session: Session = Depends(get_session)):
    path = _find_avatar(username)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(path)


# ── API Token & Service Authentication ──────────────────────────────

FAMLEDGER_API_TOKEN = os.getenv("FAMLEDGER_API_TOKEN", "")


def get_current_user_or_token(
    request: Request,
    response: Response = None,
    session: Session = Depends(get_session),
) -> str:
    """
    统一认证依赖：
    1. 优先校验 X-Api-Key 或 Authorization: Bearer 头（支持系统服务 Token 以及用户个人 API Key）。
    2. 若提供了 Key：
       a. 优先比对系统级 FAMLEDGER_API_TOKEN。
       b. 校验是否为合法的用户 API Key（SHA-256 哈希比对、有效性、有效期检测）。校验通过则以该用户身份放行，并刷新 last_used_at。
       c. 若 Key 无效或过期，直接抛出 401 拦截。
    3. 若未提供 Key，回退校验浏览器 Cookie 会话。
    4. 无任何有效凭证时，一律拒绝并返回 401 Unauthorized。
    """
    # 1. 检查 X-Api-Key 或 Bearer Token
    api_key = request.headers.get("X-Api-Key")
    if not api_key:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:].strip()

    if api_key:
        # a. 检查系统级服务 Token
        if FAMLEDGER_API_TOKEN and hmac.compare_digest(api_key, FAMLEDGER_API_TOKEN):
            from services.principals import service_family
            service_family(session)
            permitted = {("GET", "/api/v1/accounts"), ("GET", "/api/v1/transactions"),
                         ("POST", "/api/v1/transactions")}
            if (request.method, request.url.path.rstrip("/")) not in permitted:
                raise HTTPException(403, "账单服务凭证仅允许账户查询和流水导入/查询")
            return "service:bill"
        # 仅在本地开发与自动化测试环境下放行专用 dev-token，生产环境严格禁用
        is_dev = os.getenv("FAMLEDGER_ENV", "").lower() in ("dev", "development", "test") or os.getenv("PYTEST_CURRENT_TEST") is not None
        if is_dev and api_key == "dev-token":
            return "service:dev"

        # b. 检查用户个人专属 API Key (通过 SHA-256 哈希匹配)
        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        key_record = session.exec(
            select(ApiKey).where(
                ApiKey.hashed_key == key_hash,
                ApiKey.is_revoked == False,
            )
        ).first()

        if key_record:
            # 校验是否过期
            if key_record.expires_at:
                now_utc = datetime.now(timezone.utc)
                exp = key_record.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < now_utc:
                    raise HTTPException(status_code=401, detail="API Key 已过期")

            # 校验绑定的用户是否存在且处于激活状态
            user = session.get(User, key_record.user_id)
            if not user or not user.is_active:
                raise HTTPException(status_code=401, detail="API Key 归属用户不存在或已停用")

            # 记录最后使用时间
            try:
                key_record.last_used_at = datetime.now(timezone.utc)
                session.add(key_record)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.warning(f"更新 API Key last_used_at 失败: {e}")

            request.state.is_api_key = True
            return user.username

        # 提供了 api_key 但既不是系统 token 也不是合法用户 key
        raise HTTPException(status_code=401, detail="无效或已撤销的 API Key")

    # 2. 检查 Cookie 会话
    request.state.is_api_key = False
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        try:
            return get_current_user(request, response or Response(), session)
        except HTTPException as e:
            logger.warning(f"get_current_user failed: {e.detail}")
            raise e

    raise HTTPException(
        status_code=401,
        detail="未提供有效身份凭证：请通过 Authorization: Bearer <key>、X-Api-Key 头或登录 Cookie 访问",
    )

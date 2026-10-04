import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select, desc

from database import get_session
from models import ApiKey, User
from auth import get_current_user_or_token

router = APIRouter(prefix="/v1/api-keys", tags=["API Keys"])


# ── 请求与响应模型 ──────────────────────────────────────────

class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="密钥用途描述，如：iOS 快捷指令记账")
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650, description="有效天数，为空表示永久有效")


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: str
    is_revoked: bool
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    raw_key: str = Field(..., description="完整 API 密钥，仅在创建时返回一次，请务必妥善保存")


# ── 路由端点 ──────────────────────────────────────────────

@router.get("", response_model=List[ApiKeyResponse])
def list_api_keys(
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user_or_token),
):
    """获取当前登录用户创建的所有 API Key 列表（密钥内容脱敏掩码展示）。"""
    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="当前用户不存在")

    keys = session.exec(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(desc(ApiKey.created_at))
    ).all()
    return keys


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: ApiKeyCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user_or_token),
):
    """
    为当前用户创建新的 API 密钥。
    生成规范格式：flk_live_<32字符高熵随机字符串>
    注意：完整密钥仅在此接口响应中返回一次，后端仅存储不可逆的 SHA-256 哈希值。
    """
    # 安全屏障：禁止持有 API Key 的客户端再次派生新的 API Key（防密钥泄露后无限派生滥用）
    if getattr(request.state, "is_api_key", False):
        raise HTTPException(
            status_code=403,
            detail="安全限制：禁止使用 API Key 派生创建新的 API Key，请使用网页端交互式登录会话操作",
        )

    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="当前用户不存在")

    # 生成高熵随机 key
    token_entropy = secrets.token_hex(24)
    raw_key = f"flk_live_{token_entropy}"
    key_prefix = raw_key[:16]  # 形如 flk_live_a1b2c3d4
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    now_utc = datetime.now(timezone.utc)
    expires_at = None
    if payload.expires_in_days:
        expires_at = now_utc + timedelta(days=payload.expires_in_days)

    api_key_record = ApiKey(
        user_id=user.id,
        name=payload.name.strip(),
        key_prefix=key_prefix,
        hashed_key=key_hash,
        scopes="*",
        expires_at=expires_at,
        created_at=now_utc,
        updated_at=now_utc,
    )

    session.add(api_key_record)
    session.commit()
    session.refresh(api_key_record)

    return ApiKeyCreatedResponse(
        id=api_key_record.id,
        name=api_key_record.name,
        key_prefix=api_key_record.key_prefix,
        scopes=api_key_record.scopes,
        is_revoked=api_key_record.is_revoked,
        expires_at=api_key_record.expires_at,
        last_used_at=api_key_record.last_used_at,
        created_at=api_key_record.created_at,
        raw_key=raw_key,
    )


@router.post("/revoke-all")
def revoke_all_api_keys(
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user_or_token),
):
    """一键撤销/删除当前用户的所有 API 密钥（紧急终止全部外发访问凭证）。"""
    if getattr(request.state, "is_api_key", False):
        raise HTTPException(
            status_code=403,
            detail="安全限制：禁止使用 API Key 撤销或管理 API Key，请使用网页端交互式登录会话操作",
        )

    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="当前用户不存在")

    keys = session.exec(select(ApiKey).where(ApiKey.user_id == user.id)).all()
    count = len(keys)
    for k in keys:
        session.delete(k)
    session.commit()
    return {"ok": True, "revoked_count": count, "message": f"已成功撤销全部 {count} 个 API 密钥"}


@router.delete("/{key_id}")
def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user_or_token),
):
    """彻底撤销/删除指定的 API 密钥。删除后使用该密钥的调用将立即被 401 拦截。"""
    if getattr(request.state, "is_api_key", False):
        raise HTTPException(
            status_code=403,
            detail="安全限制：禁止使用 API Key 撤销或管理 API Key，请使用网页端交互式登录会话操作",
        )

    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="当前用户不存在")

    api_key_record = session.get(ApiKey, key_id)
    if not api_key_record or api_key_record.user_id != user.id:
        raise HTTPException(status_code=404, detail="API Key 不存在或无权操作")

    session.delete(api_key_record)
    session.commit()

    return {"ok": True, "message": "API Key 已成功撤销删除"}

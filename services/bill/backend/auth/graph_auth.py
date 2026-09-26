from __future__ import annotations

import logging
import platform
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from msal import PublicClientApplication, SerializableTokenCache

from backend.auth.state import set_auth_failed, set_auth_ok, set_auth_pending
from backend.notify import send_auth_notification

logger = logging.getLogger(__name__)

MSAL_NETWORK_STEP_TIMEOUT_SECONDS = 30


def _supports_signal_timeout() -> bool:
    return (
        platform.system().lower() != "windows"
        and threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
    )


@contextmanager
def _deadline_timeout(step_name: str, timeout_seconds: int):
    if timeout_seconds <= 0 or not _supports_signal_timeout():
        yield
        return

    def _raise_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"{step_name} 超时，超过 {timeout_seconds} 秒")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer != (0.0, 0.0):
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _run_auth_step(step_name: str, func: Any, *, timeout_seconds: int = MSAL_NETWORK_STEP_TIMEOUT_SECONDS) -> Any:
    start = time.monotonic()
    logger.info("Graph 认证步骤开始: %s", step_name)

    if timeout_seconds > 0 and not _supports_signal_timeout():
        logger.debug("当前运行环境不支持 signal 硬超时，步骤将按 MSAL 默认行为执行: %s", step_name)

    try:
        with _deadline_timeout(step_name, timeout_seconds):
            result = func()
    except TimeoutError:
        elapsed = time.monotonic() - start
        logger.error("Graph 认证步骤超时: %s, elapsed=%.2fs", step_name, elapsed)
        raise
    except Exception:
        elapsed = time.monotonic() - start
        logger.exception("Graph 认证步骤失败: %s, elapsed=%.2fs", step_name, elapsed)
        raise

    elapsed = time.monotonic() - start
    logger.info("Graph 认证步骤完成: %s, elapsed=%.2fs", step_name, elapsed)
    return result


def _build_public_client_app(
    tenant_id: str,
    client_id: str,
    token_cache_path: Path,
) -> tuple[PublicClientApplication, SerializableTokenCache, str]:
    tenant_candidate = _tenant_candidates(tenant_id)[0]
    authority = f"https://login.microsoftonline.com/{tenant_candidate}"
    token_cache = _load_token_cache(token_cache_path)
    app = PublicClientApplication(client_id=client_id, authority=authority, token_cache=token_cache)
    return app, token_cache, authority


def validate_cached_graph_auth(tenant_id: str, client_id: str, scopes: tuple[str, ...], token_cache_path: Path) -> bool:
    """静默校验缓存认证是否可用（不触发交互登录）。"""
    if not client_id:
        return False

    for tenant_candidate in _tenant_candidates(tenant_id):
        logger.info("开始校验缓存 Graph 认证: tenant=%s", tenant_candidate)
        authority = f"https://login.microsoftonline.com/{tenant_candidate}"
        token_cache = _load_token_cache(token_cache_path)
        app = PublicClientApplication(client_id=client_id, authority=authority, token_cache=token_cache)
        accounts = app.get_accounts()
        if not accounts:
            logger.info("缓存中未找到 Graph 账户: tenant=%s", tenant_candidate)
            continue

        result = _run_auth_step(
            f"静默校验缓存 token tenant={tenant_candidate}",
            lambda: app.acquire_token_silent(scopes=list(scopes), account=accounts[0], force_refresh=False),
        )
        _save_token_cache(token_cache, token_cache_path)
        if result and "access_token" in result:
            logger.info("缓存 Graph 认证有效: tenant=%s", tenant_candidate)
            return True
        logger.info("缓存 Graph 认证不可用: tenant=%s", tenant_candidate)
    return False


def initiate_device_code_login(
    tenant_id: str,
    client_id: str,
    scopes: tuple[str, ...],
    token_cache_path: Path,
) -> dict[str, Any]:
    """启动设备码登录流程，返回 flow 信息用于前端展示。"""
    if not client_id:
        raise ValueError("请先配置环境变量 GRAPH_CLIENT_ID。")

    app, token_cache, _ = _build_public_client_app(tenant_id, client_id, token_cache_path)
    flow = _run_auth_step(
        "初始化 Device Code Flow",
        lambda: app.initiate_device_flow(scopes=list(scopes)),
    )
    if "user_code" not in flow:
        set_auth_failed(
            f"Device Code Flow 启动失败: {flow}",
            verify_url="https://microsoft.com/devicelogin",
            client_id=client_id,
        )
        raise RuntimeError(f"Device Code Flow 启动失败: {flow}")

    verify_url = str(flow.get("verification_uri") or "https://microsoft.com/devicelogin")
    verify_url_complete = str(flow.get("verification_uri_complete") or "")
    set_auth_pending(
        str(flow.get("user_code", "")),
        verify_url,
        verify_url_complete=verify_url_complete,
        client_id=client_id,
    )
    _save_token_cache(token_cache, token_cache_path)
    return flow


def complete_device_code_login(
    tenant_id: str,
    client_id: str,
    scopes: tuple[str, ...],
    token_cache_path: Path,
    flow: dict[str, Any],
    timeout_seconds: int = 900,
) -> bool:
    """等待用户完成设备码登录并写入 token cache。"""
    if not client_id:
        return False

    app, token_cache, _ = _build_public_client_app(tenant_id, client_id, token_cache_path)
    result = _run_auth_step(
        "等待 Device Code Flow 完成",
        lambda: app.acquire_token_by_device_flow(flow, timeout=timeout_seconds),
        timeout_seconds=timeout_seconds + 5,
    )
    if result and "access_token" in result:
        _save_token_cache(token_cache, token_cache_path)
        set_auth_ok()
        return True

    error_text = str((result or {}).get("error_description") or (result or {}).get("error") or result)
    set_auth_failed(
        f"Graph 认证失败: {error_text}",
        verify_url=str(flow.get("verification_uri") or "https://microsoft.com/devicelogin"),
        client_id=client_id,
    )
    _save_token_cache(token_cache, token_cache_path)
    return False


def _tenant_candidates(tenant_id: str) -> list[str]:
    """根据配置的 tenant 生成可尝试的登录租户列表。"""
    value = (tenant_id or "").strip().lower()
    if not value:
        return ["common", "organizations", "consumers"]
    if value == "common":
        return ["common", "organizations", "consumers"]
    return [tenant_id]


def _load_token_cache(cache_path: Path) -> SerializableTokenCache:
    """加载 MSAL token cache（不存在则返回空缓存）。"""
    cache = SerializableTokenCache()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))
    return cache


def _save_token_cache(cache: SerializableTokenCache, cache_path: Path) -> None:
    """仅在缓存有变更时落盘。"""
    if cache.has_state_changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(cache.serialize(), encoding="utf-8")
        logger.debug("MSAL token cache 已更新保存: %s", cache_path)


def acquire_graph_token(tenant_id: str, client_id: str, scopes: tuple[str, ...], token_cache_path: Path) -> str:
    """获取 Graph Access Token。

    认证优先级：
    1) 强制刷新静默获取
    2) 普通静默获取
    3) Device Code 交互获取
    """
    if not client_id:
        raise ValueError("请先配置环境变量 GRAPH_CLIENT_ID。")
    logger.info("正在获取 Graph 访问令牌... tenant_id: %s, client_id: %s, scopes: %s", tenant_id, client_id, scopes)
    logger.debug("Token cache path: %s", token_cache_path)

    last_error: dict[str, Any] | None = None
    for tenant_candidate in _tenant_candidates(tenant_id):
        logger.info("开始尝试 Graph tenant: %s", tenant_candidate)
        token_cache = _load_token_cache(token_cache_path)
        authority = f"https://login.microsoftonline.com/{tenant_candidate}"
        app = PublicClientApplication(client_id=client_id, authority=authority, token_cache=token_cache)
        accounts = app.get_accounts()
        result: dict[str, Any] | None = None

        if accounts:
            logger.info("发现缓存账户，准备强制刷新 access token。tenant=%s, account_count=%s", tenant_candidate, len(accounts))
            result = _run_auth_step(
                f"强制刷新 access token tenant={tenant_candidate}",
                lambda: app.acquire_token_silent(scopes=list(scopes), account=accounts[0], force_refresh=True),
            )
        else:
            logger.info("未发现缓存账户，跳过静默刷新。tenant=%s", tenant_candidate)

        if not result and accounts:
            logger.info("强制刷新失败，回退到缓存静默获取。tenant=%s", tenant_candidate)
            result = _run_auth_step(
                f"缓存静默获取 access token tenant={tenant_candidate}",
                lambda: app.acquire_token_silent(scopes=list(scopes), account=accounts[0], force_refresh=False),
            )

        if not result:
            logger.info("准备进入 Device Code Flow。tenant=%s", tenant_candidate)
            flow = _run_auth_step(
                f"初始化 Device Code Flow tenant={tenant_candidate}",
                lambda: app.initiate_device_flow(scopes=list(scopes)),
            )
            if "user_code" not in flow:
                last_error = flow
                set_auth_failed(
                    f"Device Code Flow 启动失败: {flow}",
                    verify_url="https://microsoft.com/devicelogin",
                    client_id=client_id,
                )
                logger.warning("Device Code Flow 启动失败，tenant=%s，错误=%s", tenant_candidate, flow)
                continue
            verify_url = str(flow.get("verification_uri") or "https://microsoft.com/devicelogin")
            verify_url_complete = str(flow.get("verification_uri_complete") or "")
            set_auth_pending(
                str(flow.get("user_code", "")),
                verify_url,
                verify_url_complete=verify_url_complete,
                client_id=client_id,
            )
            send_auth_notification(
                str(flow.get("user_code", "")),
                verify_url,
                verify_url_complete=verify_url_complete,
                client_id=client_id,
            )
            print(flow["message"])
            logger.info("已展示 Device Code 登录提示，开始等待用户授权。tenant=%s", tenant_candidate)
            expires_in = int(flow.get("expires_in") or 900)
            result = _run_auth_step(
                f"等待 Device Code Flow 完成 tenant={tenant_candidate}",
                lambda: app.acquire_token_by_device_flow(flow, timeout=expires_in),
                timeout_seconds=expires_in + 5,
            )

        if "access_token" in result:
            _save_token_cache(token_cache, token_cache_path)
            set_auth_ok()
            logger.info("Graph token 获取成功，tenant=%s", tenant_candidate)
            return result["access_token"]

        last_error = result
        error_text = str((result or {}).get("error_description") or (result or {}).get("error") or result)
        set_auth_failed(
            f"Graph 认证失败: {error_text}",
            verify_url="https://microsoft.com/devicelogin",
            client_id=client_id,
        )
        _save_token_cache(token_cache, token_cache_path)
        logger.warning("Token 获取失败，tenant=%s，错误=%s", tenant_candidate, result)

    raise RuntimeError(
        "获取 Graph Token 失败。请检查："
        "1) `GRAPH_CLIENT_ID` 是否为你的 Azure 应用；"
        "2) 应用是否启用 Public client flows；"
        "3) `GRAPH_TENANT_ID` 是否填写为租户 ID/域名（例如 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` 或 `contoso.onmicrosoft.com`）。"
        f" 详细错误: {last_error}"
    )

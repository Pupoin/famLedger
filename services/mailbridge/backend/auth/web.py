"""A local Microsoft authorization page; no financial dashboard endpoints."""
from pathlib import Path
import logging
import threading
import time

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.auth.graph_auth import (MicrosoftAuthorizationRequired, acquire_graph_token,
                                     initiate_device_code_login, complete_device_code_login)
from backend.auth.state import load_auth_state, set_auth_failed, set_auth_ok
from backend.config import load_config

app = FastAPI(title="Mailbridge Microsoft authentication", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
login_lock = threading.Lock()
logger = logging.getLogger(__name__)
active_flow = None
checked_at = float("-inf")


class LoginRequest(BaseModel):
    force: StrictBool = False


def _pending(flow):
    return {"status": "pending", "required": True, "user_code": flow["user_code"],
            "verify_url": flow["verification_uri"], "expires_at": flow["expires_at"]}


def _check_cached_login(cfg):
    try:
        acquire_graph_token(cfg.tenant_id, cfg.client_id, cfg.graph_scopes, cfg.token_cache_path)
        set_auth_ok()
        return True
    except MicrosoftAuthorizationRequired:
        set_auth_failed("Microsoft 登录已失效，请重新认证")
        return False


@app.get("/")
def index():
    return FileResponse(Path(__file__).resolve().parents[2] / "front" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/status")
def auth_status():
    global checked_at
    flow = active_flow
    if flow and time.time() < flow["expires_at"]:
        return _pending(flow)
    state = load_auth_state()
    # A persisted pending code has no polling thread after a container restart.
    # Verify the actual MSAL cache instead of redisplaying that orphaned code.
    if state.get("status") == "pending" or time.monotonic() - checked_at >= 300:
        if not login_lock.acquire(blocking=False):
            return {"status": "checking", "required": False}
        try:
            _check_cached_login(load_config())
            checked_at = time.monotonic()
            state = load_auth_state()
        except Exception:
            logger.exception("Unable to check Microsoft authentication")
            raise HTTPException(503, "Unable to check Microsoft login; please retry")
        finally:
            login_lock.release()
    return {key: state[key] for key in ("status", "required", "message") if key in state}


def _complete(cfg, flow):
    global active_flow, checked_at
    try:
        complete_device_code_login(cfg.tenant_id, cfg.client_id, cfg.graph_scopes, cfg.token_cache_path, flow)
    except Exception:
        logger.exception("Microsoft authorization failed")
        set_auth_failed("Microsoft 登录失败，请重试")
    finally:
        active_flow = None
        checked_at = float("-inf")
        login_lock.release()


def _validate_login_request(request: Request):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Request origin rejected")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Use application/json")


@app.post("/api/auth/initiate", dependencies=[Depends(_validate_login_request)])
def initiate(background_tasks: BackgroundTasks, payload: LoginRequest):
    global active_flow, checked_at
    if not login_lock.acquire(blocking=False):
        raise HTTPException(409, "Microsoft login is already in progress")
    try:
        cfg = load_config()
        if not payload.force and _check_cached_login(cfg):
            checked_at = time.monotonic()
            login_lock.release()
            return {"status": "ok", "required": False}
        flow = initiate_device_code_login(cfg.tenant_id, cfg.client_id, cfg.graph_scopes, cfg.token_cache_path)
        flow.setdefault("expires_at", time.time() + int(flow.get("expires_in", 900)))
        active_flow = flow
        background_tasks.add_task(_complete, cfg, flow)
        # device_code and the eventual tokens remain server-side.
        return _pending(flow)
    except Exception:
        active_flow = None
        login_lock.release()
        logger.exception("Unable to start Microsoft authorization")
        raise HTTPException(503, "Unable to start Microsoft login; check GRAPH_CLIENT_ID")

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTH_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "auth_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_auth_state(payload: dict[str, Any]) -> None:
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_auth_state() -> dict[str, Any]:
    if not AUTH_STATE_PATH.exists():
        return {"required": False, "status": "ok", "updated_at": _now_iso()}
    try:
        return json.loads(AUTH_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"required": False, "status": "ok", "updated_at": _now_iso()}


def set_auth_ok() -> None:
    _write_auth_state(
        {
            "required": False,
            "status": "ok",
            "message": "",
            "user_code": "",
            "verify_url": "",
            "verify_url_complete": "",
            "client_id": "",
            "updated_at": _now_iso(),
        }
    )


def set_auth_pending(user_code: str, verify_url: str, *, verify_url_complete: str = "", client_id: str = "") -> None:
    _write_auth_state(
        {
            "required": True,
            "status": "pending",
            "message": "需要完成 Microsoft Graph 设备码认证。",
            "user_code": user_code,
            "verify_url": verify_url,
            "verify_url_complete": verify_url_complete,
            "client_id": client_id,
            "updated_at": _now_iso(),
        }
    )


def set_auth_failed(message: str, *, verify_url: str = "https://microsoft.com/devicelogin", client_id: str = "") -> None:
    _write_auth_state(
        {
            "required": True,
            "status": "failed",
            "message": message,
            "user_code": "",
            "verify_url": verify_url,
            "verify_url_complete": "",
            "client_id": client_id,
            "updated_at": _now_iso(),
        }
    )

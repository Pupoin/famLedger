import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone

AUTH_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "auth_state.json"


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def load_auth_state():
    try:
        return json.loads(AUTH_STATE_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {"required": True, "status": "unauthenticated", "message": "请登录 Microsoft"}


def _write(status, required, message="", **details):
    atomic_json(AUTH_STATE_PATH, {"required": required, "status": status, "message": message,
                                "updated_at": datetime.now(timezone.utc).isoformat(), **details})


def set_auth_ok():
    _write("ok", False)


def set_auth_pending(user_code, verify_url, expires_at):
    _write("pending", True, "请完成 Microsoft 设备码登录", user_code=user_code,
           verify_url=verify_url, expires_at=expires_at)


def set_auth_failed(message):
    _write("failed", True, message)

"""Microsoft delegated authentication shared by the UI and mail scheduler."""
from contextlib import contextmanager
import fcntl
import json
import time
from pathlib import Path

from msal import PublicClientApplication, SerializableTokenCache
from backend.auth.state import atomic_json, set_auth_failed, set_auth_ok, set_auth_pending


class MicrosoftAuthorizationRequired(RuntimeError):
    """The cache cannot provide a token without interactive authentication."""


@contextmanager
def _application(tenant, client_id, cache_path):
    if not client_id:
        raise ValueError("Configure GRAPH_CLIENT_ID")
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = SerializableTokenCache()
        if path.exists():
            cache.deserialize(path.read_text())
        app = PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant or 'common'}", token_cache=cache, timeout=20)
        try:
            yield app
        finally:
            if cache.has_state_changed:
                atomic_json(path, json.loads(cache.serialize()))
            fcntl.flock(lock, fcntl.LOCK_UN)


def acquire_graph_token(tenant_id, client_id, scopes, token_cache_path):
    with _application(tenant_id, client_id, token_cache_path) as app:
        accounts = app.get_accounts()
        result = app.acquire_token_silent(list(scopes), account=accounts[0]) if accounts else None
        if result and result.get("access_token"):
            set_auth_ok()
            return result["access_token"], accounts[0]["home_account_id"]
        set_auth_failed("Microsoft 登录已失效，请在认证页面重新登录")
        raise MicrosoftAuthorizationRequired("Microsoft authorization required")


def cached_account_id(token_cache_path):
    """Identify a single cached mailbox without contacting Microsoft."""
    path = Path(token_cache_path)
    if not path.exists():
        return None
    cache = SerializableTokenCache()
    cache.deserialize(path.read_text())
    accounts = cache.find(cache.CredentialType.ACCOUNT)
    return accounts[0]["home_account_id"] if len(accounts) == 1 else None


def initiate_device_code_login(tenant_id, client_id, scopes, token_cache_path):
    with _application(tenant_id, client_id, token_cache_path) as app:
        flow = app.initiate_device_flow(scopes=list(scopes))
        if "user_code" not in flow:
            raise RuntimeError("Unable to initiate Microsoft device-code login")
        flow.setdefault("expires_at", time.time() + int(flow.get("expires_in", 900)))
        set_auth_pending(flow["user_code"], flow["verification_uri"], flow["expires_at"])
        return flow


def complete_device_code_login(tenant_id, client_id, scopes, token_cache_path, flow):
    # Release the shared cache lock between polls so the worker can use its
    # existing token while an optional new login is waiting for the user.
    while time.time() < flow["expires_at"]:
        with _application(tenant_id, client_id, token_cache_path) as app:
            result = app.acquire_token_by_device_flow(flow, exit_condition=lambda _: True)
        if result and result.get("access_token"):
            set_auth_ok()
            return True
        if not result or result.get("error") not in ("authorization_pending", "slow_down"):
            break
        time.sleep(min(float(flow.get("interval", 5)), max(0, flow["expires_at"] - time.time())))
    set_auth_failed("Microsoft 登录未完成或已过期，请重新获取授权码")
    return False

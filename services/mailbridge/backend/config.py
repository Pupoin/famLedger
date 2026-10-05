from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import logging
import os
import re

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "testserver")


def load_allowed_hosts():
    """Load auth-page hosts separately from mail fetching and delivery settings."""
    load_dotenv(ROOT / ".env", override=False)
    hosts = [host.strip().lower() for host in os.getenv("MAILBRIDGE_ALLOWED_HOSTS", "").split(",")
             if host.strip()]
    if not hosts:
        hosts = list(DEFAULT_ALLOWED_HOSTS)
    for host in hosts:
        if (any(char.isspace() for char in host) or any(char in host for char in "/:@?#")
                or ("*" in host and host != "*" and not (host.startswith("*.") and "*" not in host[2:]))):
            raise ValueError("MAILBRIDGE_ALLOWED_HOSTS 请填写主机名或 IPv4 地址，用逗号分隔，不要包含协议、端口或路径")
    # Keep the local Docker health probe working even with only a public domain configured.
    return tuple(dict.fromkeys(("localhost", "127.0.0.1", *hosts)))


@dataclass(frozen=True)
class AppConfig:
    tenant_id: str
    client_id: str
    user_id: str
    graph_scopes: tuple[str, ...]
    lookback_days_credit: int
    lookback_days_debit: int
    credit_folder_name: str
    debit_folder_name: str
    token_cache_path: Path
    database_path: Path
    api_url: str
    api_token: str
    sync_interval: int
    task_timeout: int
    pull_enabled: bool
    post_enabled: bool
    replay_id: str
    replay_days: int


def parse_replay_setting(value):
    value = (value or "").strip()
    if not value:
        return "", 0
    match = re.fullmatch(r"(all|[1-9][0-9]*d)@([A-Za-z0-9][A-Za-z0-9._-]{0,63})", value, re.IGNORECASE | re.ASCII)
    if not match:
        raise ValueError("MAILBRIDGE_REPLAY 必须留空，或使用 all@标记、10d@标记 这样的格式")
    scope, marker = match.groups()
    scope = scope.lower()
    days = 0 if scope == "all" else int(scope[:-1])
    if days > 36500:
        raise ValueError("MAILBRIDGE_REPLAY 的天数不能超过 36500")
    return f"{scope}@{marker}", days


def _path(name, default):
    path = Path(os.getenv(name, default))
    return path if path.is_absolute() else ROOT / path


@lru_cache(maxsize=1)
def load_config():
    load_dotenv(ROOT / ".env", override=False)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler()])
    # Third-party DEBUG logs include mailbox IDs and opaque paging tokens.
    for library in ("msal", "urllib3", "httpx", "httpcore"):
        logging.getLogger(library).setLevel(logging.WARNING)
    interval = int(os.getenv("MAILBRIDGE_SYNC_INTERVAL_SECONDS", "600"))
    timeout = int(os.getenv("MAILBRIDGE_TASK_TIMEOUT_SECONDS", "1000"))
    if interval < 60 or timeout < 30:
        raise ValueError("Sync interval must be >=60 and task timeout >=30 seconds")
    replay_id, replay_days = parse_replay_setting(os.getenv("MAILBRIDGE_REPLAY", ""))
    return AppConfig(
        tenant_id=os.getenv("GRAPH_TENANT_ID", "common"),
        client_id=os.getenv("GRAPH_CLIENT_ID", ""), user_id=os.getenv("GRAPH_USER_ID", "me"),
        graph_scopes=("Mail.Read",),
        lookback_days_credit=int(os.getenv("LOOKBACK_DAYS_CREDIT", "30")),
        lookback_days_debit=int(os.getenv("LOOKBACK_DAYS_DEBIT", "15")),
        credit_folder_name=os.getenv("CREDIT_FOLDER", "credits"),
        debit_folder_name=os.getenv("DEBIT_FOLDER", "Debit_card"),
        token_cache_path=_path("GRAPH_TOKEN_CACHE_PATH", "data/msal_token_cache.json"),
        database_path=_path("MAILBRIDGE_DATABASE_PATH", "data/mailbridge.db"),
        api_url=os.getenv("FAMLEDGER_API_URL", "").strip().rstrip("/"),
        api_token=os.getenv("FAMLEDGER_API_TOKEN", "").strip(),
        sync_interval=interval, task_timeout=timeout,
        replay_id=replay_id, replay_days=replay_days,
        pull_enabled=os.getenv("MAILBRIDGE_PULL_ENABLED", "true").strip().lower() in ("true", "1", "yes"),
        post_enabled=os.getenv("MAILBRIDGE_POST_ENABLED", "false").strip().lower() in ("true", "1", "yes"),
    )

from __future__ import annotations

import os
import logging
import logging.config
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    tenant_id: str
    client_id: str
    user_id: str
    pg_dsn: str
    graph_scopes: tuple[str, ...]
    lookback_days_credit: int
    lookback_days_debit: int
    credit_folder_name: str
    debit_folder_name: str
    one_drive_icon: str
    log_file_path: Path
    log_level: str
    token_cache_path: Path


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    trimmed = value.strip()
    return trimmed if trimmed else default


def _env_int(name: str, default: int) -> int:
    value = _env_str(name, str(default))
    return int(value)


def _resolve_path(path_value: str, project_root: Path) -> Path:
    path_obj = Path(path_value)
    if path_obj.is_absolute():
        return path_obj
    return project_root / path_obj


def _setup_logging(log_file_path: Path, log_level: str):
    level = log_level.upper()
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": level,
                "formatter": "standard",
                "filename": str(log_file_path),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": level,
        },
    }
    logging.config.dictConfig(config)


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    load_dotenv(override=False)
    project_root = Path(__file__).resolve().parent.parent.parent
    log_default = str(project_root / "logs" / "backend.log")
    token_cache_default = str(project_root / "data" / "msal_token_cache.json")
    one_drive_root = _env_str("OneDrive", "")
    default_icon = str(Path(one_drive_root) / "media" / "!photo" / "Photo" / "Kamisato Ayaka base.png")
    log_file_path = _resolve_path(_env_str("LOG_FILE_PATH", log_default), project_root)
    token_cache_path = _resolve_path(_env_str("GRAPH_TOKEN_CACHE_PATH", token_cache_default), project_root)
    pg_password = _env_str("POSTGRES_PASSWORD", "postgres")
    pg_dsn_default = f"postgresql://postgres:replace-with-a-random-password@localhost:5432/personal_cost"
    pg_dsn_raw = _env_str("POSTGRES_DSN", pg_dsn_default)
    pg_dsn = pg_dsn_raw.replace("${POSTGRES_PASSWORD}", pg_password).replace("$POSTGRES_PASSWORD", pg_password)

    cfg = AppConfig(
        tenant_id=_env_str("GRAPH_TENANT_ID", "common"),
        client_id=_env_str("GRAPH_CLIENT_ID", ""),
        user_id=_env_str("GRAPH_USER_ID", "me"),
        pg_dsn=pg_dsn,
        graph_scopes=("Mail.Read",),
        lookback_days_credit=_env_int("LOOKBACK_DAYS_CREDIT", 30),
        lookback_days_debit=_env_int("LOOKBACK_DAYS_DEBIT", 15),
        credit_folder_name=_env_str("CREDIT_FOLDER", "credits"),
        debit_folder_name=_env_str("DEBIT_FOLDER", "Debit_card"),
        one_drive_icon=_env_str("NOTIFY_ICON_PATH", default_icon),
        log_file_path=log_file_path,
        log_level=_env_str("LOG_LEVEL", "INFO"),
        token_cache_path=token_cache_path,
    )

    _setup_logging(cfg.log_file_path, cfg.log_level)
    return cfg

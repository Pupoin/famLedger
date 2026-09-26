import logging
import os
from pathlib import Path

from sqlalchemy import event, text
from sqlmodel import create_engine, SQLModel, Session

logger = logging.getLogger("famledger")

# DATA_DIR: where backups, audit logs, and uploads are stored.
DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent)))
DB_PATH = DATA_DIR / "famledger.db"

# 优先读取 DATABASE_URL (默认采用 PostgreSQL 18)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

is_sqlite = DATABASE_URL.startswith("sqlite")

if is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
else:
    # PostgreSQL 18: 配置高性能连接池 (极低内存占用)
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


def create_db_and_tables():
    """初始化数据库表结构与必要的 PostgreSQL 扩展 (pgcrypto, pg_trgm)。"""
    if not is_sqlite:
        with engine.begin() as conn:
            try:
                conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto";'))
                conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm";'))
            except Exception as e:
                logger.warning(f"Could not enable PostgreSQL extensions (may require superuser): {e}")

    SQLModel.metadata.create_all(engine)
    logger.info("FamLedger database tables created/verified successfully.")


def check_db_integrity() -> bool:
    """运行数据库健康检查。"""
    try:
        with engine.connect() as conn:
            if is_sqlite:
                result = conn.execute(text("PRAGMA integrity_check")).scalar()
                return result == "ok"
            else:
                result = conn.execute(text("SELECT 1")).scalar()
                return result == 1
    except Exception:
        logger.exception("Database integrity check failed")
        return False


def ensure_user_preference_columns():
    if is_sqlite:
        from services.schema import sync_schema
        sync_schema(engine)


def get_session():
    """FastAPI 依赖项：获取数据库会话。"""
    with Session(engine) as session:
        yield session


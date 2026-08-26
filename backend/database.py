import logging
import os
from pathlib import Path

from sqlalchemy import event, text
from sqlmodel import create_engine, SQLModel, Session

logger = logging.getLogger("mosaic")

# DATA_DIR: where the database, backups, audit logs, and uploads are stored.
# Defaults to the backend/ directory (unchanged local behaviour).
# Set DATA_DIR=/app/data in Docker to persist everything in a mounted volume.
DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent)))
DB_PATH = DATA_DIR / "mosaic.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def check_db_integrity() -> bool:
    """Run PRAGMA integrity_check on the database. Returns True if healthy.

    A recognizable-but-corrupted SQLite file (bad page checksums, partial
    writes) returns a non-"ok" row from PRAGMA integrity_check. A file that
    isn't SQLite at all (or is corrupted badly enough to lose its header)
    makes sqlite3 raise instead of returning a row — both cases must be
    treated as a failed check, not let the caller crash outright.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA integrity_check")).scalar()
    except Exception:
        logger.exception("Database integrity check raised an error (unreadable/non-SQLite file)")
        return False
    ok = result == "ok"
    if ok:
        logger.info("Database integrity check passed")
    else:
        logger.error("Database integrity check FAILED: %s", result)
    return ok


def ensure_user_preference_columns():
    """Add columns introduced to `userpreference` after its first release.

    Superseded by services.schema.sync_schema(), which does the same diff-and-ALTER
    for *every* table rather than just this one — the hand-written version here
    had to be extended by hand each time a column was added, and every table it
    didn't cover reintroduced the original bug ("no such column" at runtime, on
    an app that started up perfectly).

    Kept as a delegating wrapper because it is part of the module's public
    surface and is directly covered by tests/test_preference_column_migration.py.
    Prefer calling sync_schema() in new code.
    """
    from services.schema import sync_schema
    sync_schema(engine)


def get_session():
    with Session(engine) as session:
        yield session

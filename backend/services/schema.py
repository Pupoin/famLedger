"""Additive schema migration for SQLite, plus a schema-version stamp.

Why this exists
---------------
``SQLModel.metadata.create_all()`` creates *missing tables* but never alters an
existing one. So any model field added to an already-deployed table is simply
absent from the real SQLite schema, and the failure surfaces at *runtime*
("no such column") on whichever endpoint touches it -- not at startup. That is
the worst possible shape for a data app: it boots clean, then one page 500s.

``database.ensure_user_preference_columns()`` was a hand-written patch for
exactly two columns on one table. This module generalises it: diff every model
table against the live schema and ADD whatever is missing, on every startup.

Deliberately **add-only**. It never drops, renames, or retypes a column --
those need a real migration (and a full table rebuild on SQLite). CLAUDE.md
already requires every new column to carry a default so old rows stay valid;
this module is what *enforces* that convention rather than trusting it.

What it refuses to do
---------------------
Two cases raise instead of guessing, because both would silently lose data:

* a missing NOT NULL column with no derivable default -- SQLite cannot add one
  to a table that already has rows;
* a missing UNIQUE column -- ``ALTER TABLE ADD COLUMN`` cannot express UNIQUE
  on SQLite at all.

A *declared type* difference only logs a warning. Comparing compiled type
strings is genuinely ambiguous (``VARCHAR``, ``VARCHAR(50)`` and ``TEXT`` all
describe the same SQLite affinity), so a false positive would take a healthy
app down. Refusing to boot is reserved for the two unambiguous cases above.
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text

logger = logging.getLogger("mosaic")

# Bumped only when the code requires a schema change this additive migrator
# cannot perform on its own. Stored via `PRAGMA user_version`, which costs no
# extra table and is therefore not itself a schema change.
#
# 1 -- first stamped version (Mosaic v2.1.0). Structurally identical to the
#      v2.0.0 schema: v2.1.0 introduces the stamp, not a schema change.
SCHEMA_VERSION = 4


def get_db_schema_version(engine) -> int:
    """Read the schema version stamped in the database.

    Returns 0 for a brand-new database *and* for any pre-v2.1.0 one, since
    neither was ever stamped. Callers must read 0 as "unknown, migrate it"
    rather than "empty".
    """
    if engine.dialect.name != "sqlite":
        from sqlalchemy import inspect
        if not inspect(engine).has_table("schema_version"):
            return 0
        with engine.connect() as conn:
            return int(conn.execute(text("SELECT version FROM schema_version WHERE id=1")).scalar() or 0)

    with engine.connect() as conn:
        return int(conn.execute(text("PRAGMA user_version")).scalar() or 0)


def set_db_schema_version(engine, version: int = SCHEMA_VERSION) -> None:
    """Stamp the database with a schema version.

    PRAGMA user_version takes no bound parameter, hence the f-string; the value
    is coerced to int first so this cannot become an injection point.
    """
    if engine.dialect.name != "sqlite":
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"))
            conn.execute(text("INSERT INTO schema_version(id,version) VALUES(1,:version) ON CONFLICT(id) DO UPDATE SET version=excluded.version"), {"version": int(version)})
        return

    version = int(version)
    with engine.connect() as conn:
        conn.execute(text(f"PRAGMA user_version = {version}"))
        conn.commit()


def assert_schema_not_newer(engine) -> int:
    """Refuse to run against a database written by a newer Mosaic.

    Downgrades are the one direction an add-only migrator can never handle: the
    newer version may have added columns or tables this code knows nothing
    about, and older code writing to it can violate constraints it cannot see.
    Failing loudly at startup beats corrupting data quietly.
    """
    db_version = get_db_schema_version(engine)
    if db_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {db_version} is newer than this build "
            f"supports (schema version {SCHEMA_VERSION}). This database was "
            f"written by a newer version of Mosaic. Refusing to start, because "
            f"running older code against a newer schema risks data loss. "
            f"Upgrade the Mosaic image, or restore a backup taken before the "
            f"upgrade."
        )
    return db_version


def _existing_columns(conn, table_name: str) -> dict:
    """Map column name -> declared type for a live table.

    An empty dict means the table does not exist yet, which is normal on a
    fresh database -- create_all() builds it with every column already present,
    so there is nothing for this module to do.
    """
    if conn.dialect.name == "sqlite":
        rows = conn.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
        return {row[1]: (row[2] or "") for row in rows}
    else:
        from sqlalchemy import inspect
        try:
            inspector = inspect(conn)
            cols = inspector.get_columns(table_name)
            return {col["name"]: str(col.get("type", "")) for col in cols}
        except Exception:
            return {}


def _sql_literal(value):
    """Render a Python default as a SQL literal for use in ADD COLUMN.

    Returns None when the value cannot be represented safely; the caller treats
    that as "no usable default" rather than inventing a substitute.
    """
    if value is None:
        return None
    # bool before int -- bool is an int subclass, and SQLite wants 0/1.
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return "'" + value.isoformat() + "'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def _default_literal(column):
    """Best-effort SQL literal for a column's default.

    Handles plain defaults (``Field(default="CAD")``) and factories
    (``Field(default_factory=...)``). SQLAlchemy wraps zero-argument callables
    so they accept a context argument, so a callable is tried both ways before
    giving up.
    """
    server_default = getattr(column, "server_default", None)
    if server_default is not None:
        arg = getattr(server_default, "arg", None)
        rendered = getattr(arg, "text", None) or (str(arg) if arg is not None else None)
        if rendered:
            return rendered

    default = getattr(column, "default", None)
    if default is None:
        return None

    arg = getattr(default, "arg", None)
    if callable(arg):
        for call in (lambda: arg(None), lambda: arg()):
            try:
                return _sql_literal(call())
            except TypeError:
                continue
            except Exception:
                logger.exception(
                    "Default factory for column %s raised; treating as no default",
                    column.name,
                )
                return None
        return None
    return _sql_literal(arg)


def sync_schema(engine=None, metadata=None) -> list:
    """Add every model column missing from the live SQLite schema.

    Returns the DDL statements actually executed -- empty when the schema is
    already current, which is the normal case on every restart after the first.
    Every statement is also logged at INFO, because silent schema mutation is
    exactly the thing you want a record of.

    ``metadata`` defaults to the app's real ``SQLModel.metadata``. It is a
    parameter so tests can pass an isolated ``MetaData`` and exercise the
    refusal paths on purpose-built tables -- declaring throwaway SQLModel models
    in a test would register them in the *global* metadata, where
    ``create_all()`` in another test's fixture would then start creating them.
    """
    # Imported here rather than at module scope: ``models`` must be imported for
    # SQLModel.metadata to be populated at all, and deferring keeps the import
    # graph acyclic with ``database``.
    import database
    if engine is None:
        engine = database.engine

    is_pg = engine.dialect.name == "postgresql"

    if metadata is None:
        import models  # noqa: F401  -- populates SQLModel.metadata
        from sqlmodel import SQLModel
        metadata = SQLModel.metadata

    executed = []

    for table in metadata.sorted_tables:
        with engine.connect() as conn:
            existing = _existing_columns(conn, table.name)
            if not existing:
                # Table absent -- create_all() will build it complete.
                continue

            for column in table.columns:
                if column.name in existing:
                    declared = existing[column.name].upper()
                    wanted = str(column.type.compile(dialect=engine.dialect)).upper()
                    # Advisory only -- see the module docstring on why a type
                    # difference must not block startup.
                    if declared and wanted and declared != wanted:
                        logger.warning(
                            "Column %s.%s is declared %s but the model expects %s. "
                            "Leaving it alone -- SQLite type affinity usually makes "
                            "this harmless, but a genuine type change needs a manual "
                            "migration.",
                            table.name, column.name, declared, wanted,
                        )
                    continue

                if column.unique:
                    raise RuntimeError(
                        f"Cannot add column {table.name}.{column.name}: SQLite's "
                        f"ALTER TABLE ADD COLUMN cannot create a UNIQUE column. "
                        f"This needs a manual table rebuild. Take a backup first "
                        f"(python -m cli export)."
                    )

                literal = _default_literal(column)
                if not column.nullable and literal is None:
                    raise RuntimeError(
                        f"Cannot add column {table.name}.{column.name}: it is NOT "
                        f"NULL with no usable default, and SQLite cannot add such a "
                        f"column to a table that already has rows. Give the model "
                        f"field a default (CLAUDE.md: every new column needs one so "
                        f"old rows stay valid)."
                    )

                if is_pg and str(column.type) == "BOOLEAN" and literal in {"0", "1"}:
                    literal = "FALSE" if literal == "0" else "TRUE"
                type_sql = column.type.compile(dialect=engine.dialect)
                if is_pg:
                    ddl = f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" {type_sql}'
                else:
                    ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {type_sql}'
                if not column.nullable:
                    ddl += " NOT NULL"
                if literal is not None:
                    ddl += f" DEFAULT {literal}"

                logger.info("Schema migration: %s", ddl)
                conn.execute(text(ddl))
                conn.commit()
                executed.append(ddl)
                existing[column.name] = str(type_sql)

            # A column in the database but not in the model is left strictly
            # alone. It may belong to a newer version someone rolled back from,
            # and dropping it would destroy data.
            for name in existing:
                if name not in table.columns:
                    logger.warning(
                        "Column %s.%s exists in the database but not in the model. "
                        "Leaving it untouched.",
                        table.name, name,
                    )

    _migrate_financial_indexes(engine, metadata)
    if executed:
        logger.info("Schema migration applied %d change(s)", len(executed))
    return executed


def _migrate_financial_indexes(engine, metadata):
    """Version 2 adds enforcement to deployed tables, not only new databases."""
    from sqlalchemy import inspect
    from sqlalchemy.exc import IntegrityError
    tables = set(inspect(engine).get_table_names()) & set(metadata.tables)
    with engine.begin() as conn:
        try:
            if "users" in tables:
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_ci ON users(lower(username))"))
            if "transfers" in tables:
                for field in ("outflow_transaction_id", "inflow_transaction_id"):
                    conn.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_transfers_{field} ON transfers({field})"))
            if "family_invitations" in tables:
                # Keep the newest pending request; explicitly cancel older duplicates.
                conn.execute(text("""UPDATE family_invitations SET status='canceled',
                    cancel_reason='升级时清理重复未决邀请' WHERE id IN (
                    SELECT id FROM (SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY family_id, invitee_user_id ORDER BY created_at DESC, id DESC) AS rn
                    FROM family_invitations WHERE status='pending') AS duplicates WHERE rn>1)"""))
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_family_invitation ON family_invitations(family_id,invitee_user_id) WHERE status='pending'"))
            if "series_alert_states" in tables:
                indexes = inspect(conn).get_indexes("series_alert_states")
                old = next((index for index in indexes if index['name'] == 'ix_series_alert_lookup'), None)
                if old and 'family_id' not in old.get('column_names', []):
                    conn.execute(text("DROP INDEX ix_series_alert_lookup"))
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_series_alert_lookup ON series_alert_states(series_key,alert_type,family_id)"))
        except IntegrityError as exc:
            raise RuntimeError("Existing data conflicts with required unique constraints; repair duplicates before upgrading") from exc

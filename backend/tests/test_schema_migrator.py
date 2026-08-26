"""Tests for services/schema.py — the additive schema migrator and version stamp.

These build isolated SQLAlchemy MetaData rather than declaring throwaway
SQLModel models: a SQLModel table declared in a test registers itself in the
*global* SQLModel.metadata, where conftest's `create_all()` would then start
creating it in every other test's database.

The last test covers the real models, so the generic machinery is also exercised
against the schema the app actually ships.
"""

import pytest
from sqlalchemy import Column, Integer, MetaData, Numeric, String, Table, text
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from services.schema import (
    SCHEMA_VERSION,
    assert_schema_not_newer,
    get_db_schema_version,
    set_db_schema_version,
    sync_schema,
)


def _engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_legacy(engine, ddl, rows=()):
    with engine.connect() as conn:
        conn.execute(text(ddl))
        for row in rows:
            conn.execute(text(row))
        conn.commit()


def _columns(engine, table):
    with engine.connect() as conn:
        return {
            r[1]: r for r in conn.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
        }


# ── adding columns ──────────────────────────────────────────────────

def test_adds_missing_nullable_column():
    engine = _engine()
    _create_legacy(
        engine,
        "CREATE TABLE thing (id INTEGER PRIMARY KEY, name VARCHAR(50))",
        ["INSERT INTO thing (name) VALUES ('existing')"],
    )

    md = MetaData()
    Table(
        "thing", md,
        Column("id", Integer, primary_key=True),
        Column("name", String(50)),
        Column("note", String(200), nullable=True),
    )

    executed = sync_schema(engine, metadata=md)

    assert len(executed) == 1
    assert "note" in _columns(engine, "thing")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, note FROM thing")).first()
    # The pre-existing row survives, with NULL in the new column.
    assert row.name == "existing"
    assert row.note is None


def test_adds_missing_not_null_column_with_default():
    engine = _engine()
    _create_legacy(
        engine,
        "CREATE TABLE thing (id INTEGER PRIMARY KEY)",
        ["INSERT INTO thing (id) VALUES (1)"],
    )

    md = MetaData()
    Table(
        "thing", md,
        Column("id", Integer, primary_key=True),
        Column("currency", String(10), nullable=False, default="CAD"),
    )

    sync_schema(engine, metadata=md)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT currency FROM thing")).scalar() == "CAD"


def test_adds_decimal_column_with_numeric_type():
    """Money columns must land as NUMERIC, not TEXT — the app reads them back
    as Decimal and a type change would break every amount."""
    engine = _engine()
    _create_legacy(engine, "CREATE TABLE thing (id INTEGER PRIMARY KEY)")

    md = MetaData()
    Table(
        "thing", md,
        Column("id", Integer, primary_key=True),
        Column("amount", Numeric(10, 2), nullable=True),
    )

    executed = sync_schema(engine, metadata=md)

    assert "NUMERIC" in executed[0].upper()
    assert "NUMERIC" in _columns(engine, "thing")["amount"][2].upper()


def test_is_idempotent():
    engine = _engine()
    _create_legacy(engine, "CREATE TABLE thing (id INTEGER PRIMARY KEY)")

    md = MetaData()
    Table(
        "thing", md,
        Column("id", Integer, primary_key=True),
        Column("note", String(50), nullable=True),
    )

    assert len(sync_schema(engine, metadata=md)) == 1
    # A second run (i.e. the next app restart) must be a silent no-op.
    assert sync_schema(engine, metadata=md) == []


def test_skips_table_that_does_not_exist_yet():
    """A brand-new database has no tables until create_all() runs; the migrator
    must not try to ALTER something that isn't there."""
    engine = _engine()

    md = MetaData()
    Table("thing", md, Column("id", Integer, primary_key=True))

    assert sync_schema(engine, metadata=md) == []


# ── the refusal paths ───────────────────────────────────────────────

def test_refuses_not_null_column_without_default():
    """SQLite genuinely cannot do this to a table with rows, so guessing a value
    would mean inventing data. Fail loudly instead."""
    engine = _engine()
    _create_legacy(
        engine,
        "CREATE TABLE thing (id INTEGER PRIMARY KEY)",
        ["INSERT INTO thing (id) VALUES (1)"],
    )

    md = MetaData()
    Table(
        "thing", md,
        Column("id", Integer, primary_key=True),
        Column("mandatory", String(50), nullable=False),
    )

    with pytest.raises(RuntimeError, match="NOT NULL with no usable default"):
        sync_schema(engine, metadata=md)


def test_refuses_unique_column():
    """ALTER TABLE ADD COLUMN cannot express UNIQUE on SQLite; adding the column
    without the constraint would silently produce a schema that permits
    duplicates the app believes are impossible."""
    engine = _engine()
    _create_legacy(engine, "CREATE TABLE thing (id INTEGER PRIMARY KEY)")

    md = MetaData()
    Table(
        "thing", md,
        Column("id", Integer, primary_key=True),
        Column("slug", String(50), unique=True, nullable=True),
    )

    with pytest.raises(RuntimeError, match="UNIQUE"):
        sync_schema(engine, metadata=md)


def test_never_drops_a_column_the_model_does_not_have():
    """A column present in the database but not in the model is left alone — it
    may belong to a newer version someone rolled back from, and dropping it
    would destroy data."""
    engine = _engine()
    _create_legacy(
        engine,
        "CREATE TABLE thing (id INTEGER PRIMARY KEY, from_the_future VARCHAR(20))",
        ["INSERT INTO thing (from_the_future) VALUES ('keep me')"],
    )

    md = MetaData()
    Table("thing", md, Column("id", Integer, primary_key=True))

    sync_schema(engine, metadata=md)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT from_the_future FROM thing")).scalar() == "keep me"


def test_type_mismatch_warns_but_does_not_raise(caplog):
    """A declared-type difference must not block startup: comparing compiled
    type strings is ambiguous (VARCHAR / VARCHAR(50) / TEXT all describe one
    SQLite affinity), so a false positive here would take a healthy app down."""
    engine = _engine()
    _create_legacy(engine, "CREATE TABLE thing (id INTEGER PRIMARY KEY, name TEXT)")

    md = MetaData()
    Table(
        "thing", md,
        Column("id", Integer, primary_key=True),
        Column("name", String(50)),
    )

    with caplog.at_level("WARNING"):
        assert sync_schema(engine, metadata=md) == []
    assert any("expects" in record.message for record in caplog.records)


# ── the version stamp ───────────────────────────────────────────────

def test_unstamped_database_reads_as_zero():
    """Both a fresh database and any pre-v2.1.0 one are unstamped, so 0 must
    mean "unknown, migrate it" rather than "empty"."""
    assert get_db_schema_version(_engine()) == 0


def test_stamp_round_trips():
    engine = _engine()
    set_db_schema_version(engine, SCHEMA_VERSION)
    assert get_db_schema_version(engine) == SCHEMA_VERSION


def test_accepts_equal_and_older_schema_versions():
    engine = _engine()
    set_db_schema_version(engine, SCHEMA_VERSION)
    assert assert_schema_not_newer(engine) == SCHEMA_VERSION

    engine2 = _engine()  # unstamped / legacy
    assert assert_schema_not_newer(engine2) == 0


def test_refuses_a_database_from_a_newer_version():
    """Downgrades are the one direction an add-only migrator can never handle."""
    engine = _engine()
    set_db_schema_version(engine, SCHEMA_VERSION + 1)

    with pytest.raises(RuntimeError, match="newer than this build"):
        assert_schema_not_newer(engine)


# ── against the real models ─────────────────────────────────────────

def test_upgrades_a_real_legacy_userpreference_table():
    """The case that motivated all of this: a userpreference table created
    before `currency` and `income_mode_enabled` existed. Uses the app's real
    metadata, so this covers the shipped schema and not just synthetic tables."""
    engine = _engine()
    _create_legacy(
        engine,
        "CREATE TABLE userpreference ("
        "id INTEGER PRIMARY KEY, "
        "username VARCHAR(100) UNIQUE NOT NULL, "
        "date_format VARCHAR(20) NOT NULL DEFAULT 'DD/MM/YYYY')",
        ["INSERT INTO userpreference (username, date_format) VALUES ('alice', 'MM/DD/YYYY')"],
    )

    sync_schema(engine)

    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT username, date_format, currency, income_mode_enabled "
            "FROM userpreference"
        )).first()
    assert row.username == "alice"
    assert row.date_format == "MM/DD/YYYY"  # existing data untouched
    assert row.currency == "CAD"            # documented default
    assert row.income_mode_enabled == 0

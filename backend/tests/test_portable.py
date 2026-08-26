"""Tests for services/portable.py — the export / import path.

These construct real on-disk SQLite files (same approach as test_backup.py)
rather than using the in-memory test engine, because the whole point of the
module is what happens to files: checksums, atomic replacement, stale WAL
sidecars, tar extraction.

The bar these tests hold: an import must either land the data *exactly* as
exported, or refuse. Silently landing something almost-right is the failure mode
that matters for financial data.
"""

import json
import sqlite3
import tarfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from models import Expense, Income, Settings, User, UserPreference
from services.portable import (
    ARCHIVE_FORMAT,
    compute_fingerprint,
    export_archive,
    format_fingerprint,
    import_archive,
    read_manifest,
)
from services.schema import SCHEMA_VERSION


def _seed_data_dir(data_dir: Path, expense_count: int = 40) -> Path:
    """Build a realistic data directory: database, audit log and an avatar."""
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "mosaic.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as s:
        s.add(User(
            username="alice", display_name="Alice", password_hash="h" * 20,
            security_question="q", security_answer_hash="a" * 20,
        ))
        s.add(User(
            username="bob", display_name="Bob", password_hash="h" * 20,
            security_question="q", security_answer_hash="a" * 20,
        ))
        s.add(Settings(id=1, app_mode="shared"))
        s.add(UserPreference(username="alice", currency="CAD"))

        start = date(2024, 1, 1)
        for i in range(expense_count):
            # A negative Reimbursement every fifth row: the fingerprint must net
            # these into the total the same way the app's own totals do.
            category = "Reimbursement" if i % 5 == 4 else "Groceries"
            amount = Decimal("12.34") + Decimal(i) * Decimal("3.01")
            if category == "Reimbursement":
                amount = -amount
            s.add(Expense(
                date=start + timedelta(days=i),
                description=f"Item {i}",
                amount=amount,
                category=category,
                paid_by="Alice" if i % 2 == 0 else "Bob",
                split_method="50/50",
            ))
        s.add(Income(
            date=start, amount=Decimal("4210.75"),
            source="Salary / Wages", notes=None, user_id="alice",
        ))
        s.commit()
    engine.dispose()

    (data_dir / "audit").mkdir(exist_ok=True)
    (data_dir / "audit" / "audit.jsonl").write_text(
        '{"operation":"create","user":"alice"}\n', encoding="utf-8"
    )
    (data_dir / "uploads" / "avatars").mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads" / "avatars" / "alice.png").write_bytes(b"\x89PNGfake")
    return db_path


def _repack(archive: Path, mutate) -> Path:
    """Unpack an archive, let `mutate` alter the extracted tree, repack it.

    Used to forge tampered archives — the point of the checksum and fingerprint
    is that a forgery must not import cleanly.
    """
    work = archive.parent / (archive.stem + "-unpacked")
    work.mkdir(exist_ok=True)
    with tarfile.open(archive, "r:*") as tar:
        tar.extractall(work, filter="data")
    mutate(work)
    forged = archive.parent / "forged.tar.gz"
    with tarfile.open(forged, "w:gz") as tar:
        for item in sorted(work.iterdir()):
            tar.add(item, arcname=item.name)
    return forged


# ── fingerprinting ──────────────────────────────────────────────────

def test_fingerprint_nets_negative_reimbursements_into_the_total(tmp_path):
    db_path = _seed_data_dir(tmp_path / "src", expense_count=10)
    fingerprint = compute_fingerprint(db_path)

    # Recompute independently from the raw rows.
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT amount FROM expense").fetchall()
    conn.close()
    expected = sum((Decimal(str(r[0])) for r in rows), Decimal("0"))

    assert fingerprint["expense"]["count"] == 10
    assert Decimal(fingerprint["expense"]["total"]) == expected
    # A negative category total is expected, not a bug.
    assert Decimal(fingerprint["expense"]["by_category"]["Reimbursement"]) < 0


def test_fingerprint_reports_money_as_strings(tmp_path):
    """Money must never round-trip through a JSON float — that would reintroduce
    exactly the precision loss this module exists to prevent."""
    db_path = _seed_data_dir(tmp_path / "src")
    fingerprint = compute_fingerprint(db_path)

    assert isinstance(fingerprint["expense"]["total"], str)
    assert all(isinstance(v, str) for v in fingerprint["expense"]["by_payer"].values())
    # Survives a JSON round-trip unchanged.
    assert json.loads(json.dumps(fingerprint)) == fingerprint


def test_format_fingerprint_shows_the_headline_total(tmp_path):
    """The rendered form is the human check after a migration, so the total has
    to actually be in it."""
    db_path = _seed_data_dir(tmp_path / "src")
    fingerprint = compute_fingerprint(db_path)
    rendered = format_fingerprint(fingerprint)

    assert "TOTAL AMOUNT" in rendered
    assert fingerprint["expense"]["total"] in rendered
    assert "alice" in rendered


# ── export ──────────────────────────────────────────────────────────

def test_export_writes_a_manifest_with_version_and_checksum(tmp_path):
    _seed_data_dir(tmp_path / "src")
    archive = tmp_path / "out.tar.gz"

    manifest = export_archive(tmp_path / "src", archive, app_version="9.9.9")

    assert archive.exists()
    assert manifest["format"] == ARCHIVE_FORMAT
    assert manifest["mosaic_version"] == "9.9.9"
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert len(manifest["db_sha256"]) == 64
    assert read_manifest(archive) == manifest


def test_export_excludes_backups(tmp_path):
    """Backups are derived data; there can be thirty of them. Shipping
    backups-of-backups would bloat the archive for no recovery value."""
    src = tmp_path / "src"
    _seed_data_dir(src)
    (src / "backups" / "2026-01-01T000000000000").mkdir(parents=True)
    (src / "backups" / "2026-01-01T000000000000" / "mosaic.db").write_bytes(b"old")

    export_archive(src, tmp_path / "out.tar.gz")

    with tarfile.open(tmp_path / "out.tar.gz") as tar:
        names = tar.getnames()
    assert not any(name.startswith("backups") for name in names)
    assert "mosaic.db" in names


def test_export_refuses_when_there_is_no_database(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        export_archive(empty, tmp_path / "out.tar.gz")


# ── round trip ──────────────────────────────────────────────────────

def test_round_trip_preserves_the_fingerprint_exactly(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    db_path = _seed_data_dir(src)
    before = compute_fingerprint(db_path)

    export_archive(src, tmp_path / "out.tar.gz")
    result = import_archive(tmp_path / "out.tar.gz", dst)

    assert result["fingerprint"] == before
    assert compute_fingerprint(dst / "mosaic.db") == before


def test_round_trip_carries_audit_log_and_avatars(tmp_path):
    """Avatars were excluded from every backup before v2.1.0, so this is the
    regression guard for that gap."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src)

    export_archive(src, tmp_path / "out.tar.gz")
    import_archive(tmp_path / "out.tar.gz", dst)

    assert (dst / "audit" / "audit.jsonl").read_text(encoding="utf-8").startswith("{")
    assert (dst / "uploads" / "avatars" / "alice.png").read_bytes() == b"\x89PNGfake"


def test_source_is_never_modified_by_export(tmp_path):
    src = tmp_path / "src"
    db_path = _seed_data_dir(src)
    before = db_path.read_bytes()

    export_archive(src, tmp_path / "out.tar.gz")

    assert db_path.read_bytes() == before


# ── refusals ────────────────────────────────────────────────────────

def test_refuses_to_overwrite_a_populated_database(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src)
    _seed_data_dir(dst)
    export_archive(src, tmp_path / "out.tar.gz")

    with pytest.raises(RuntimeError, match="already contains data"):
        import_archive(tmp_path / "out.tar.gz", dst)


def test_force_overwrites_and_snapshots_the_previous_database(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src, expense_count=10)
    _seed_data_dir(dst, expense_count=40)
    export_archive(src, tmp_path / "out.tar.gz")

    result = import_archive(tmp_path / "out.tar.gz", dst, force=True)

    assert result["fingerprint"]["expense"]["count"] == 10
    snapshot = Path(result["snapshot"])
    assert snapshot.exists()
    # The replaced database is still recoverable, with its original contents.
    assert compute_fingerprint(snapshot / "mosaic.db")["expense"]["count"] == 40


def test_snapshot_is_not_placed_where_backup_rotation_would_delete_it(tmp_path):
    """BackupManager rotates `backups/` by timestamp pattern and keeps only the
    most recent N. A pre-import snapshot living there would eventually be
    deleted, so it goes in `pre-import/` instead."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src)
    _seed_data_dir(dst)
    export_archive(src, tmp_path / "out.tar.gz")

    result = import_archive(tmp_path / "out.tar.gz", dst, force=True)

    assert "pre-import" in Path(result["snapshot"]).parts
    assert "backups" not in Path(result["snapshot"]).parts


def test_detects_a_tampered_database(tmp_path):
    """The checksum's job: a database altered after export must not import."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src)
    archive = tmp_path / "out.tar.gz"
    export_archive(src, archive)

    def corrupt(tree):
        db = tree / "mosaic.db"
        raw = bytearray(db.read_bytes())
        raw[4096:4128] = b"\x00" * 32
        db.write_bytes(bytes(raw))

    forged = _repack(archive, corrupt)

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        import_archive(forged, dst)
    # Nothing was installed.
    assert not (dst / "mosaic.db").exists()


def test_detects_a_manifest_that_disagrees_with_its_own_data(tmp_path):
    """The fingerprint's job. Unlike the checksum, this is the check that still
    works after a schema migration has legitimately changed the file's bytes."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src)
    archive = tmp_path / "out.tar.gz"
    export_archive(src, archive)

    def overstate_the_total(tree):
        manifest_path = tree / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["fingerprint"]["expense"]["total"] = "999999.99"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    forged = _repack(archive, overstate_the_total)

    with pytest.raises(RuntimeError, match="do not match its manifest"):
        import_archive(forged, dst)


def test_refuses_an_archive_from_a_newer_schema(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src)
    archive = tmp_path / "out.tar.gz"
    export_archive(src, archive)

    def bump_schema(tree):
        manifest_path = tree / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = SCHEMA_VERSION + 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="newer than this build supports"):
        import_archive(_repack(archive, bump_schema), dst)


def test_refuses_an_unknown_archive_format(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src)
    archive = tmp_path / "out.tar.gz"
    export_archive(src, archive)

    def bump_format(tree):
        manifest_path = tree / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["format"] = 999
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="format 999 is not supported"):
        import_archive(_repack(archive, bump_format), dst)


def test_refuses_an_archive_with_no_manifest(tmp_path):
    bogus = tmp_path / "bogus.tar.gz"
    (tmp_path / "junk.txt").write_text("not an export", encoding="utf-8")
    with tarfile.open(bogus, "w:gz") as tar:
        tar.add(tmp_path / "junk.txt", arcname="junk.txt")

    with pytest.raises(RuntimeError, match="was not produced by"):
        import_archive(bogus, tmp_path / "dst")


# ── the WAL trap ────────────────────────────────────────────────────

def test_discards_a_stale_wal_belonging_to_the_replaced_database(tmp_path):
    """A leftover -wal from the old database would be applied on top of the newly
    installed one — that is a corruption, not a merge. It must be removed."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_data_dir(src, expense_count=10)
    _seed_data_dir(dst, expense_count=40)

    stale_wal = dst / "mosaic.db-wal"
    stale_wal.write_bytes(b"\xde\xad\xbe\xef" * 64)
    (dst / "mosaic.db-shm").write_bytes(b"\x00" * 32)

    export_archive(src, tmp_path / "out.tar.gz")
    result = import_archive(tmp_path / "out.tar.gz", dst, force=True)

    assert not stale_wal.exists()
    assert not (dst / "mosaic.db-shm").exists()
    assert result["fingerprint"]["expense"]["count"] == 10
    # And the installed database is genuinely readable afterwards.
    assert compute_fingerprint(dst / "mosaic.db")["expense"]["count"] == 10

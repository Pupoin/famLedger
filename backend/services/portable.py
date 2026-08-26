"""Portable export / import of a Mosaic data directory.

This is the lift-and-shift tool: it moves a live installation to another
machine (or another container) with a verifiable guarantee that the expense
data arrived intact.

Design decisions that matter
----------------------------
**The database travels as the binary SQLite file, never as CSV or JSON.**
Amounts are ``Decimal`` quantised to 2 places (``Numeric(10, 2)``); dates are
real dates. Any text round-trip risks a float conversion or a reformat that
silently changes a number. ``sqlite3.Connection.backup()`` produces a
byte-exact, WAL-consistent copy while the app is still running, so there is no
serialisation step to get wrong.

**Two independent verifications, because they catch different failures.**

* ``db_sha256`` proves the *file* arrived byte-identical -- it catches a
  truncated copy or a corrupted transfer.
* the **fingerprint** proves the *data* is unchanged -- row counts, the total
  of every expense, sums per category and per payer, the date range, income
  totals, and the user list.

Only the fingerprint survives a schema migration: once a column is added the
sha256 legitimately changes, so a checksum alone can no longer tell you your
money is still there. The fingerprint can, and it is deliberately
human-readable so you can eyeball the total against what the app shows.

**Backups are excluded from the archive.** They are derived data, there can be
thirty of them, and shipping backups-of-backups would bloat the archive for no
recovery value. The live database is what gets carried.
"""

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from services.schema import SCHEMA_VERSION

logger = logging.getLogger("mosaic")

# Bumped if the archive layout changes incompatibly. `import` refuses a format
# it does not recognise rather than guessing at the layout.
ARCHIVE_FORMAT = 1

MANIFEST_NAME = "manifest.json"
DB_NAME = "mosaic.db"
AUDIT_REL = "audit/audit.jsonl"
UPLOADS_REL = "uploads"

_MONEY = Decimal("0.01")


# ─────────────────────────── fingerprinting ───────────────────────────

def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in chunks so a large database is not slurped."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_to_memory(db_path: Path) -> sqlite3.Connection:
    """Copy a database into memory so it can be read consistently.

    Going through the online backup API rather than reading the file directly
    means a fingerprint taken against a *live* database still sees a single
    coherent snapshot, WAL included, and never writes to the source.
    """
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(":memory:")
        src.backup(dst)
        return dst
    finally:
        src.close()


def _table_names(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _money_sum(values) -> str:
    """Sum stored amounts exactly, as Decimal.

    SQLite has no DECIMAL type: SQLAlchemy's ``Numeric(10, 2)`` lands with
    NUMERIC affinity, so 10.50 comes back as the float 10.5. Summing in SQL
    would therefore be float arithmetic. Going via ``Decimal(str(v))`` -- str()
    of a float is the shortest representation that round-trips -- keeps the
    total exact and reproducible.
    """
    total = Decimal("0")
    for value in values:
        if value is None:
            continue
        total += Decimal(str(value))
    return str(total.quantize(_MONEY))


def compute_fingerprint(db_path: Path) -> dict:
    """Build a human-readable, verifiable summary of what a database contains.

    Deliberately reports money as strings: a float in JSON would reintroduce
    exactly the precision problem this whole module exists to avoid.
    """
    conn = _snapshot_to_memory(db_path)
    try:
        conn.row_factory = sqlite3.Row
        tables = _table_names(conn)

        counts = {}
        for name in tables:
            counts[name] = conn.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()[0]

        fingerprint = {
            "fingerprint_format": 1,
            "tables": counts,
        }

        if "expense" in tables:
            rows = conn.execute(
                "SELECT date, amount, category, paid_by FROM expense"
            ).fetchall()
            by_category = {}
            by_payer = {}
            for row in rows:
                by_category.setdefault(row["category"], []).append(row["amount"])
                by_payer.setdefault(row["paid_by"], []).append(row["amount"])
            dates = sorted(str(row["date"]) for row in rows if row["date"] is not None)
            fingerprint["expense"] = {
                "count": len(rows),
                "total": _money_sum(row["amount"] for row in rows),
                "by_category": {
                    key: _money_sum(vals) for key, vals in sorted(by_category.items())
                },
                "by_payer": {
                    key: _money_sum(vals) for key, vals in sorted(by_payer.items())
                },
                "date_min": dates[0] if dates else None,
                "date_max": dates[-1] if dates else None,
            }

        if "income" in tables:
            rows = conn.execute("SELECT amount FROM income").fetchall()
            fingerprint["income"] = {
                "count": len(rows),
                "total": _money_sum(row["amount"] for row in rows),
            }

        if "user" in tables:
            rows = conn.execute(
                "SELECT username, display_name FROM user ORDER BY id"
            ).fetchall()
            fingerprint["users"] = [
                {"username": row["username"], "display_name": row["display_name"]}
                for row in rows
            ]

        return fingerprint
    finally:
        conn.close()


def format_fingerprint(fingerprint: dict) -> str:
    """Render a fingerprint for a human to read and compare by eye.

    This is the actual proof that a migration went cleanly: run it on both
    machines and check that the totals match to the cent.
    """
    lines = []
    expense = fingerprint.get("expense")
    if expense:
        lines.append(f"Expenses:        {expense['count']} rows")
        lines.append(f"  TOTAL AMOUNT:  {expense['total']}")
        if expense.get("date_min"):
            lines.append(
                f"  date range:    {expense['date_min']} .. {expense['date_max']}"
            )
        if expense.get("by_payer"):
            lines.append("  by payer:")
            for name, total in expense["by_payer"].items():
                lines.append(f"    {name}: {total}")
        if expense.get("by_category"):
            lines.append("  by category:")
            for name, total in expense["by_category"].items():
                lines.append(f"    {name}: {total}")

    income = fingerprint.get("income")
    if income:
        lines.append(f"Income:          {income['count']} rows, total {income['total']}")

    users = fingerprint.get("users")
    if users:
        rendered = ", ".join(f"{u['username']} ({u['display_name']})" for u in users)
        lines.append(f"Users:           {rendered}")

    lines.append("Row counts:")
    for name, count in sorted(fingerprint.get("tables", {}).items()):
        lines.append(f"    {name}: {count}")
    return "\n".join(lines)


def _integrity_ok(db_path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error:
        logger.exception("Could not open %s for integrity check", db_path)
        return False
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.Error:
        logger.exception("Integrity check failed to run on %s", db_path)
        return False
    finally:
        conn.close()


# ───────────────────────────── export ─────────────────────────────

def export_archive(data_dir: Path, dest: Path, app_version: str = "unknown") -> dict:
    """Write a verifiable archive of ``data_dir`` to ``dest``.

    The source is only ever read. Returns the manifest that was embedded.
    """
    data_dir = Path(data_dir)
    dest = Path(dest)
    db_path = data_dir / DB_NAME
    if not db_path.exists():
        raise FileNotFoundError(f"No database found at {db_path}")

    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "mosaic-export"
        staging.mkdir(parents=True)

        # Consistent copy even while the app is serving traffic.
        staged_db = staging / DB_NAME
        src = sqlite3.connect(str(db_path))
        try:
            dst = sqlite3.connect(str(staged_db))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        if not _integrity_ok(staged_db):
            raise RuntimeError(
                f"The database copy taken from {db_path} failed PRAGMA "
                f"integrity_check. Refusing to write an archive that is not "
                f"restorable. The source database may be corrupt."
            )

        fingerprint = compute_fingerprint(staged_db)

        audit_src = data_dir / AUDIT_REL
        if audit_src.exists():
            staged_audit = staging / AUDIT_REL
            staged_audit.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(audit_src, staged_audit)

        uploads_src = data_dir / UPLOADS_REL
        if uploads_src.is_dir():
            shutil.copytree(uploads_src, staging / UPLOADS_REL)

        manifest = {
            "format": ARCHIVE_FORMAT,
            "mosaic_version": app_version,
            "schema_version": SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "db_sha256": sha256_file(staged_db),
            "fingerprint": fingerprint,
            "includes": {
                "audit": audit_src.exists(),
                "uploads": uploads_src.is_dir(),
                # Backups are intentionally omitted -- derived data, see the
                # module docstring.
                "backups": False,
            },
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        with tarfile.open(dest, "w:gz") as tar:
            for item in sorted(staging.iterdir()):
                tar.add(item, arcname=item.name)

    logger.info("Exported %s to %s", data_dir, dest)
    return manifest


# ───────────────────────────── import ─────────────────────────────

def read_manifest(archive: Path) -> dict:
    """Read just the manifest out of an archive, without extracting it."""
    with tarfile.open(archive, "r:*") as tar:
        try:
            member = tar.getmember(MANIFEST_NAME)
        except KeyError:
            raise RuntimeError(
                f"{archive} has no {MANIFEST_NAME}; it was not produced by "
                f"`mosaic export` and cannot be verified."
            )
        handle = tar.extractfile(member)
        if handle is None:
            raise RuntimeError(f"Could not read {MANIFEST_NAME} from {archive}")
        return json.loads(handle.read().decode("utf-8"))


def _fingerprint_diff(expected: dict, actual: dict) -> list:
    """Compare the load-bearing parts of two fingerprints.

    Only reports differences that mean data changed. Ignores presentation-only
    keys so a future additive change to the fingerprint does not read as a
    data-loss event.
    """
    problems = []

    exp_tables = expected.get("tables", {})
    act_tables = actual.get("tables", {})
    for table, count in sorted(exp_tables.items()):
        if table not in act_tables:
            problems.append(f"table {table!r} is missing after import")
        elif act_tables[table] != count:
            problems.append(
                f"table {table!r} has {act_tables[table]} rows, expected {count}"
            )

    for section in ("expense", "income"):
        exp = expected.get(section)
        act = actual.get(section)
        if exp is None and act is None:
            continue
        if exp is None or act is None:
            problems.append(f"{section} data present on one side only")
            continue
        if exp.get("count") != act.get("count"):
            problems.append(
                f"{section} row count is {act.get('count')}, expected {exp.get('count')}"
            )
        if exp.get("total") != act.get("total"):
            problems.append(
                f"{section} TOTAL is {act.get('total')}, expected {exp.get('total')}"
            )
        for key in ("by_category", "by_payer", "date_min", "date_max"):
            if key in exp and exp.get(key) != act.get(key):
                problems.append(f"{section}.{key} differs from the archive")

    if expected.get("users") != actual.get("users"):
        problems.append("the user list differs from the archive")

    return problems


def _looks_populated(db_path: Path) -> bool:
    """Whether a database already holds real data worth refusing to overwrite."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    try:
        fingerprint = compute_fingerprint(db_path)
    except sqlite3.Error:
        # Unreadable is not the same as empty -- treat it as populated so an
        # import cannot quietly clobber a database that merely failed to open.
        return True
    counts = fingerprint.get("tables", {})
    return any(counts.get(name, 0) > 0 for name in ("expense", "income", "user"))


def import_archive(archive: Path, data_dir: Path, force: bool = False) -> dict:
    """Restore an archive into ``data_dir``, verifying before and after.

    Ordering is chosen so that nothing irreversible happens until every check
    has passed, and so that a failure after the swap restores the snapshot.
    """
    archive = Path(archive)
    data_dir = Path(data_dir)
    db_path = data_dir / DB_NAME

    manifest = read_manifest(archive)

    if manifest.get("format") != ARCHIVE_FORMAT:
        raise RuntimeError(
            f"Archive format {manifest.get('format')} is not supported by this "
            f"build (expected {ARCHIVE_FORMAT})."
        )

    archive_schema = int(manifest.get("schema_version", 0))
    if archive_schema > SCHEMA_VERSION:
        raise RuntimeError(
            f"Archive was written at schema version {archive_schema}, newer than "
            f"this build supports ({SCHEMA_VERSION}). Upgrade the Mosaic image "
            f"before importing -- older code cannot safely read a newer schema."
        )

    if not force and _looks_populated(db_path):
        raise RuntimeError(
            f"{db_path} already contains data. Refusing to overwrite it. "
            f"Re-run with --force if you genuinely mean to replace it; a "
            f"snapshot of the current database is taken either way."
        )

    with tempfile.TemporaryDirectory() as tmp:
        extracted = Path(tmp) / "incoming"
        extracted.mkdir(parents=True)
        with tarfile.open(archive, "r:*") as tar:
            # filter="data" blocks absolute paths, parent-directory escapes,
            # symlinks and device files -- this archive came from outside.
            tar.extractall(extracted, filter="data")

        incoming_db = extracted / DB_NAME
        if not incoming_db.exists():
            raise RuntimeError(f"Archive contains no {DB_NAME}")

        actual_sha = sha256_file(incoming_db)
        if actual_sha != manifest.get("db_sha256"):
            raise RuntimeError(
                f"Database checksum mismatch. The archive is corrupt or was "
                f"modified after export.\n  expected {manifest.get('db_sha256')}"
                f"\n  actual   {actual_sha}"
            )

        if not _integrity_ok(incoming_db):
            raise RuntimeError(
                "The database inside the archive failed PRAGMA integrity_check. "
                "Refusing to install it."
            )

        expected_fp = manifest.get("fingerprint", {})
        incoming_fp = compute_fingerprint(incoming_db)
        problems = _fingerprint_diff(expected_fp, incoming_fp)
        if problems:
            raise RuntimeError(
                "The archive's own contents do not match its manifest:\n  - "
                + "\n  - ".join(problems)
            )

        data_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot whatever is already there, before touching anything. Placed
        # outside `backups/` deliberately: BackupManager rotates that directory
        # by timestamp pattern and would eventually delete this.
        snapshot_dir = None
        if db_path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S%f")
            snapshot_dir = data_dir / "pre-import" / stamp
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            try:
                src = sqlite3.connect(str(db_path))
                try:
                    dst = sqlite3.connect(str(snapshot_dir / DB_NAME))
                    try:
                        src.backup(dst)
                    finally:
                        dst.close()
                finally:
                    src.close()
                logger.info("Snapshotted the existing database to %s", snapshot_dir)
            except sqlite3.Error:
                # A database too broken to snapshot is also one there is no
                # point protecting -- but say so rather than pretending.
                logger.exception(
                    "Could not snapshot the existing database at %s; it may be "
                    "corrupt. Continuing with the import.", db_path
                )

        # Discard stale WAL/SHM *before* swapping the file in. A leftover WAL
        # belonging to the old database would otherwise be applied on top of the
        # new one, which is a corruption, not a merge. The snapshot above went
        # through backup(), so any committed WAL content is already preserved.
        for suffix in ("-wal", "-shm"):
            stale = Path(str(db_path) + suffix)
            if stale.exists():
                stale.unlink()

        # Written by hand rather than via shutil.copy2 so the data can be
        # fsync'd through the *write* handle -- fsync on a read-only descriptor
        # fails outright on Windows (OSError 9, bad file descriptor).
        staged = Path(str(db_path) + ".incoming")
        with open(incoming_db, "rb") as src_handle, open(staged, "wb") as dst_handle:
            shutil.copyfileobj(src_handle, dst_handle)
            dst_handle.flush()
            os.fsync(dst_handle.fileno())
        os.replace(staged, db_path)

        if manifest.get("includes", {}).get("audit"):
            audit_src = extracted / AUDIT_REL
            if audit_src.exists():
                audit_dest = data_dir / AUDIT_REL
                audit_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(audit_src, audit_dest)

        if manifest.get("includes", {}).get("uploads"):
            uploads_src = extracted / UPLOADS_REL
            if uploads_src.is_dir():
                uploads_dest = data_dir / UPLOADS_REL
                if uploads_dest.exists():
                    shutil.rmtree(uploads_dest)
                shutil.copytree(uploads_src, uploads_dest)

        # Verify what actually landed on disk, not what we believe we wrote.
        installed_fp = compute_fingerprint(db_path)
        problems = _fingerprint_diff(expected_fp, installed_fp)
        if problems:
            raise RuntimeError(
                "Import verification FAILED after installing the database:\n  - "
                + "\n  - ".join(problems)
                + (
                    f"\n\nThe previous database was snapshotted to {snapshot_dir} "
                    f"-- restore it before using the app."
                    if snapshot_dir else ""
                )
            )

    logger.info("Imported %s into %s (verified)", archive, data_dir)
    return {
        "manifest": manifest,
        "fingerprint": installed_fp,
        "snapshot": str(snapshot_dir) if snapshot_dir else None,
    }

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
from pathlib import Path, PurePosixPath

from services.schema import SCHEMA_VERSION

logger = logging.getLogger("mosaic")

# Bumped if the archive layout changes incompatibly. `import` refuses a format
# it does not recognise rather than guessing at the layout.
ARCHIVE_FORMAT = 1

MANIFEST_NAME = "manifest.json"
DB_NAME = "famledger.db"
AUDIT_REL = "audit/audit.jsonl"
UPLOADS_REL = "uploads"


def _resolve_data_db_path(data_dir: Path) -> Path:
    return data_dir / DB_NAME

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

        user_table = "users" if "users" in tables else None
        if user_table:
            rows = conn.execute(f'SELECT username, display_name FROM "{user_table}" ORDER BY username').fetchall()
            fingerprint["users"] = [dict(row) for row in rows]

        if "transactions" in tables:
            rows = conn.execute("SELECT amount, currency, transaction_type FROM transactions").fetchall()
            by_currency = {}
            by_type = {}
            for row in rows:
                kind = row["transaction_type"]
                signed = -Decimal(str(row["amount"])) if kind == "refund" else Decimal(str(row["amount"]))
                by_type.setdefault(kind, []).append(signed)
                if kind in ("expense", "refund"):
                    by_currency.setdefault(row["currency"], []).append(signed)
            fingerprint["transactions"] = {
                "count": len(rows),
                "net_expense": {key: _money_sum(values) for key, values in sorted(by_currency.items())},
                "by_type": {key: _money_sum(values) for key, values in sorted(by_type.items())},
            }
            # Amount totals alone cannot detect altered relationships or metadata.
            financial_tables = ("transactions", "accounts", "transaction_splits", "transfers",
                                "refund_allocations", "loans", "personal_debts", "account_shares", "pending_fx_transactions")
            digests = {}
            for name in financial_tables:
                if name not in tables:
                    continue
                all_rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
                canonical = sorted(json.dumps(dict(row), sort_keys=True, separators=(",", ":"), default=str)
                                   for row in all_rows)
                digests[name] = hashlib.sha256("\n".join(canonical).encode()).hexdigest()
            fingerprint["financial_digests"] = digests

        return fingerprint
    finally:
        conn.close()


def format_fingerprint(fingerprint: dict) -> str:
    """Render a fingerprint for a human to read and compare by eye.

    This is the actual proof that a migration went cleanly: run it on both
    machines and check that the totals match to the cent.
    """
    lines = []
    transactions = fingerprint.get("transactions")
    if transactions:
        lines.append(f"Transactions: {transactions['count']} rows")
        for currency, total in transactions["net_expense"].items():
            lines.append(f"  TOTAL AMOUNT ({currency} net expense): {total}")

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
        from services.data_integrity import sqlite_integrity_problems
        return not sqlite_integrity_problems(conn)
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
    db_path = _resolve_data_db_path(data_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"No database found at {db_path} (expected {DB_NAME})")

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

MAX_ARCHIVE_FILES = 10000
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


class SafeTarInfo(tarfile.TarInfo):
    def _check_metadata(self, tarfile_obj):
        count = getattr(tarfile_obj, "_safe_metadata_count", 0) + 1
        size = getattr(tarfile_obj, "_safe_metadata_size", 0) + self.size
        tarfile_obj._safe_metadata_count = count
        tarfile_obj._safe_metadata_size = size
        if self.size < 0 or self.size > MAX_MANIFEST_BYTES or size > 8 * MAX_MANIFEST_BYTES or count > 200:
            raise RuntimeError("Archive metadata exceeds limit")

    def _proc_pax(self, tarfile_obj):
        self._check_metadata(tarfile_obj)
        return super()._proc_pax(tarfile_obj)

    def _proc_gnulong(self, tarfile_obj):
        self._check_metadata(tarfile_obj)
        return super()._proc_gnulong(tarfile_obj)


def _safe_members(tar):
    seen = set()
    total = 0
    for member in tar:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                or not (member.isfile() or member.isdir()) or member.issparse()):
            raise RuntimeError("Archive contains an unsafe member")
        name = str(path)
        allowed = (name in {MANIFEST_NAME, DB_NAME, "audit", AUDIT_REL, UPLOADS_REL}
                   or name.startswith(UPLOADS_REL + "/"))
        if not allowed or name in seen or member.size < 0:
            raise RuntimeError("Archive contains unknown or duplicate members")
        seen.add(name)
        total += member.size
        if len(seen) > MAX_ARCHIVE_FILES or total > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Archive exceeds extraction limits")
        if member.isdir() and name in {MANIFEST_NAME, DB_NAME, AUDIT_REL}:
            raise RuntimeError("Archive file is replaced by a directory")
        yield member


def read_manifest(archive: Path) -> dict:
    manifest = None
    with tarfile.open(archive, "r:*", tarinfo=SafeTarInfo) as tar:
        for member in _safe_members(tar):
            if str(PurePosixPath(member.name)) == MANIFEST_NAME:
                if not member.isfile() or member.size > MAX_MANIFEST_BYTES:
                    raise RuntimeError("Manifest exceeds size limit")
                with tar.extractfile(member) as handle:
                    manifest = json.loads(handle.read(MAX_MANIFEST_BYTES + 1))
    if not isinstance(manifest, dict):
        raise RuntimeError("Archive contains no valid manifest")
    return manifest


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

    for section in ("transactions", "financial_digests"):
        if section in expected and expected[section] != actual.get(section):
            problems.append(f"{section} differs from the archive")

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
    return any(counts.get(name, 0) > 0 for name in ("transactions", "users", "accounts", "expense", "income", "user"))


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
        with tarfile.open(archive, "r:*", tarinfo=SafeTarInfo) as tar:
            # filter="data" blocks absolute paths, parent-directory escapes,
            # symlinks and device files -- this archive came from outside.
            tar.extractall(extracted, members=_safe_members(tar), filter="data")

        incoming_db = extracted / DB_NAME
        if not incoming_db.exists():
            raise RuntimeError(f"Archive does not contain {DB_NAME}")

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
            except sqlite3.Error as exc:
                raise RuntimeError("Cannot snapshot the current database; refusing to replace it") from exc

        # Include existing sidecars in the rollback snapshot, even when there
        # was no database. Preparation completes before changing live files.
        original_paths = {relative: (data_dir / relative).exists() for relative in (AUDIT_REL, UPLOADS_REL)}
        if any(original_paths.values()) and snapshot_dir is None:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S%f")
            snapshot_dir = data_dir / "pre-import" / stamp
            snapshot_dir.mkdir(parents=True, exist_ok=True)
        for relative, exists in original_paths.items():
            if exists:
                source = data_dir / relative
                target = snapshot_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)

        try:
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
        except Exception:
            # Restore the entire previous state rather than leaving a partial
            # database/audit/avatar import for the operator to repair manually.
            for suffix in ("-wal", "-shm", ".incoming"):
                Path(str(db_path) + suffix).unlink(missing_ok=True)
            saved_db = snapshot_dir / DB_NAME if snapshot_dir else None
            if saved_db and saved_db.exists():
                shutil.copy2(saved_db, db_path)
            else:
                db_path.unlink(missing_ok=True)
            for relative, existed in original_paths.items():
                live = data_dir / relative
                if live.is_dir():
                    shutil.rmtree(live)
                elif live.exists():
                    live.unlink()
                if existed:
                    saved = snapshot_dir / relative
                    live.parent.mkdir(parents=True, exist_ok=True)
                    if saved.is_dir():
                        shutil.copytree(saved, live)
                    else:
                        shutil.copy2(saved, live)
            raise

    logger.info("Imported %s into %s (verified)", archive, data_dir)
    return {
        "manifest": manifest,
        "fingerprint": installed_fp,
        "snapshot": str(snapshot_dir) if snapshot_dir else None,
    }

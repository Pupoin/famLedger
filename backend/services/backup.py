import logging
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

# Microsecond precision avoids two backups within the same second colliding on
# the same destination folder now that backups can also fire mid-session
# (see notify_mutation), not just once at startup. The looser {6,} lower bound
# keeps recognizing older second-precision backup folders already on disk.
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{6,}$")

logger = logging.getLogger("mosaic")


class BackupManager:
    """Creates timestamped, verified backups of the database, audit log and uploads.

    `uploads_dir` closes a real gap: avatars live under DATA_DIR/uploads/avatars
    (see auth.AVATARS_DIR) and used to be omitted entirely, so "restore from
    backup" silently did not restore everything.

    `mirror_dir` is an *additional* destination, not a replacement. Setting the
    BACKUP_PATH env var used to *relocate* backups -- local copies stopped, and
    if the target was an unmounted path the backup silently landed on the
    container's own disk while still logging success. Backups now always land
    locally first and are copied outward afterwards, so a mirror failure can
    never cost you the local copy.
    """

    def __init__(
        self,
        db_path: Path,
        audit_log_path: Path,
        backup_dir: Path,
        max_backups: int = 10,
        backup_every_n_mutations: Optional[int] = None,
        uploads_dir: Optional[Path] = None,
        mirror_dir: Optional[Path] = None,
    ):
        self.db_path = db_path
        self.audit_log_path = audit_log_path
        self.backup_dir = backup_dir
        self.uploads_dir = uploads_dir
        self.mirror_dir = mirror_dir
        self.max_backups = max_backups
        # If set, notify_mutation() triggers a backup once this many mutations
        # have been observed since the last one — correlating backups with
        # actual data change instead of only firing once at process startup.
        self.backup_every_n_mutations = backup_every_n_mutations
        self._mutation_count = 0
        self._lock = threading.Lock()

    def create_backup(self) -> Path:
        """Create a consistent, timestamped backup of the DB and audit log.

        Uses the SQLite online backup API (sqlite3.Connection.backup) which
        produces a correct snapshot even while the app is running with WAL mode.
        """
        timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S%f")
        dest = self.backup_dir / timestamp
        dest.mkdir(parents=True, exist_ok=True)

        from database import is_sqlite, DATABASE_URL
        if not is_sqlite:
            pg_dump_path = shutil.which("pg_dump")
            if pg_dump_path:
                try:
                    import subprocess
                    from database import engine
                    from services.postgres_tools import check_pg_dump_version, pg_dump_connection
                    check_pg_dump_version(pg_dump_path, engine)
                    connection_url, environment = pg_dump_connection(DATABASE_URL)
                    sql_dest = dest / "famledger.sql"
                    result = subprocess.run(
                        [pg_dump_path, "--dbname", connection_url, "-f", str(sql_dest), "--no-owner", "--no-privileges"],
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if result.returncode == 0:
                        logger.info("PostgreSQL database backup created via pg_dump at %s", sql_dest)
                    else:
                        raise RuntimeError(f"pg_dump failed with exit code {result.returncode}")
                except Exception as e:
                    shutil.rmtree(dest, ignore_errors=True)
                    raise RuntimeError("PostgreSQL backup failed") from e
            else:
                shutil.rmtree(dest, ignore_errors=True)
                raise RuntimeError("pg_dump is required for PostgreSQL backups")
        else:
            # Backup database using the SQLite online backup API
            if not self.db_path.exists():
                logger.warning("SQLite database file not found at %s; skipping DB backup", self.db_path)
            else:
                src_conn = sqlite3.connect(str(self.db_path))
                dst_conn = sqlite3.connect(str(dest / "famledger.db"))
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
                    src_conn.close()

        # Copy audit log if it exists
        if self.audit_log_path.exists():
            shutil.copy2(self.audit_log_path, dest / "audit.jsonl")

        # Uploads (avatars). Small, but they are user data and were previously
        # left out of every backup.
        if self.uploads_dir and self.uploads_dir.is_dir():
            try:
                shutil.copytree(self.uploads_dir, dest / "uploads", dirs_exist_ok=True)
            except OSError:
                logger.exception(
                    "Could not copy uploads from %s into backup %s. The database "
                    "backup itself is unaffected.",
                    self.uploads_dir, dest,
                )

        verified = self.verify_backup(dest)
        if verified:
            logger.info("Backup created and verified at %s", dest)
        else:
            logger.warning(
                "Backup at %s could not be verified (or running in PostgreSQL mode without valid dump).",
                dest,
            )
            # 若转储失败且未生成有效备份文件，清理空目录防堆积
            if not is_sqlite:
                try:
                    shutil.rmtree(dest)
                except OSError:
                    pass
                raise RuntimeError("PostgreSQL backup verification failed")

        if not verified:
            raise RuntimeError("Backup verification failed")
        self._rotate_backups()

        # Only mirror a backup that actually verified — copying a known-bad
        # backup off-site just spreads the false confidence.
        if verified:
            self._mirror_backup(dest)
        return dest

    def _mirror_backup(self, dest: Path) -> None:
        """Copy a verified backup to the mirror destination, if one is configured.

        Never raises: an off-site copy is redundancy, so a failure here must not
        take down the app or discard the local backup that already succeeded. It
        is logged at ERROR because a mirror that has quietly stopped working is
        exactly the thing you want to find out about before you need it.
        """
        if not self.mirror_dir:
            return
        target = self.mirror_dir / dest.name
        try:
            shutil.copytree(dest, target, dirs_exist_ok=True)
            logger.info("Backup mirrored to %s", target)
            self._rotate_backups(self.mirror_dir)
        except OSError:
            logger.exception(
                "Failed to mirror backup to %s. The local backup at %s is intact. "
                "Check that the mirror path is still mounted and writable.",
                target, dest,
            )

    def verify_backup(self, dest: Path) -> bool:
        """Open the freshly-created backup copy and confirm it's actually restorable.

        A corrupt backup is worse than no backup at all, since it creates false
        confidence that data is safe. Checks PRAGMA integrity_check on the copy
        itself, plus a row-count sanity comparison against the live source.

        Note: the row-count comparison reads the *current* source after the
        backup already completed, so a mutation landing in that gap could cause
        a spurious mismatch on an otherwise-good backup. Given this app's single
        low-concurrency SQLite instance, that window is negligible — this is a
        best-effort sanity check, not a strict guarantee.
        """
        from database import is_sqlite
        if not is_sqlite:
            sql_file = dest / "famledger.sql"
            return bool(sql_file.exists() and sql_file.stat().st_size > 0)
        targets = []
        for name in ["famledger.db"]:
            p = dest / name
            if p.exists() and p not in targets:
                targets.append(p)
        if not targets:
            return False

        for db_copy in targets:
            try:
                conn = sqlite3.connect(str(db_copy))
            except sqlite3.Error:
                logger.exception("Could not open backup at %s (%s) for verification", dest, db_copy.name)
                return False
            try:
                # A file corrupted badly enough to lose its SQLite header makes
                # sqlite3 raise here instead of returning an error row — either
                # way, the backup isn't restorable.
                from services.data_integrity import sqlite_integrity_problems
                integrity = sqlite_integrity_problems(conn)
                if integrity:
                    logger.error("Backup at %s (%s) failed integrity_check: %s", dest, db_copy.name, integrity)
                    return False
                if not self._row_counts_match(conn):
                    return False
            except sqlite3.Error:
                logger.exception("Backup at %s (%s) could not be read for integrity check", dest, db_copy.name)
                return False
            finally:
                conn.close()
        return True

    def _row_counts_match(self, backup_conn: sqlite3.Connection) -> bool:
        src_conn = sqlite3.connect(str(self.db_path))
        try:
            tables = [
                row[0]
                for row in src_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for table in tables:
                src_count = src_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                dst_count = backup_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if src_count != dst_count:
                    logger.error(
                        "Backup row-count mismatch in table %s: source=%d backup=%d",
                        table, src_count, dst_count,
                    )
                    return False
            return True
        finally:
            src_conn.close()

    def notify_mutation(self) -> Optional[Path]:
        """Call after a committed mutation. Creates a backup every N calls.

        Thread-safe: FastAPI runs sync routes in a worker thread pool, so
        concurrent mutations are possible even for a 2-user app.
        """
        if not self.backup_every_n_mutations:
            return None
        with self._lock:
            self._mutation_count += 1
            if self._mutation_count < self.backup_every_n_mutations:
                return None
            self._mutation_count = 0
        return self.create_backup()

    def _rotate_backups(self, directory: Optional[Path] = None) -> None:
        """Keep only the most recent max_backups in `directory`, delete the rest.

        Takes a directory so the mirror destination is rotated on the same
        policy as the local one -- otherwise an off-site folder grows without
        bound. Only directories matching the timestamp pattern are considered,
        which is what keeps anything else living alongside them (notably the
        `pre-import/` snapshots written by services.portable) from being
        deleted by rotation.
        """
        directory = directory or self.backup_dir
        if not directory.exists():
            return
        backups = sorted(
            [d for d in directory.iterdir() if d.is_dir() and _TIMESTAMP_RE.match(d.name)],
            reverse=True,
        )
        for old in backups[self.max_backups :]:
            shutil.rmtree(old)
            logger.info("Rotated old backup: %s", old.name)

"""Tests for backup cadence, verification, and the startup integrity gate
(bucket 05, item 2).

These construct BackupManager directly against real on-disk SQLite files —
independent of the shared in-memory API test database — since backups are
fundamentally a filesystem/on-disk-SQLite concern.
"""

import asyncio
import sqlite3

import pytest
from sqlmodel import SQLModel, Session, create_engine

from services.backup import BackupManager


def _make_real_db(tmp_path, name="mosaic.db"):
    """Create a real on-disk SQLite DB with the app's schema and one row."""
    db_path = tmp_path / name
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    from models import User

    with Session(engine) as s:
        s.add(User(
            username="alice",
            display_name="Alice",
            password_hash="x",
            security_question="q",
            security_answer_hash="x",
        ))
        s.commit()
    engine.dispose()
    return db_path


# ── Verification ──────────────────────────────────────────────────────────────


def test_create_backup_produces_a_verifiable_copy(tmp_path):
    db_path = _make_real_db(tmp_path)
    backup_dir = tmp_path / "backups"
    mgr = BackupManager(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", backup_dir=backup_dir)

    dest = mgr.create_backup()

    assert (dest / "mosaic.db").exists()
    assert mgr.verify_backup(dest) is True

    conn = sqlite3.connect(str(dest / "mosaic.db"))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 1
    finally:
        conn.close()


def test_verify_backup_detects_row_count_mismatch(tmp_path):
    db_path = _make_real_db(tmp_path)
    backup_dir = tmp_path / "backups"
    mgr = BackupManager(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", backup_dir=backup_dir)

    dest = mgr.create_backup()
    assert mgr.verify_backup(dest) is True

    # Simulate drift: a row lands in the source after the backup completed.
    engine = create_engine(f"sqlite:///{db_path}")
    from models import User
    with Session(engine) as s:
        s.add(User(
            username="bob", display_name="Bob", password_hash="x",
            security_question="q", security_answer_hash="x",
        ))
        s.commit()
    engine.dispose()

    assert mgr.verify_backup(dest) is False


def test_verify_backup_detects_corruption(tmp_path):
    db_path = _make_real_db(tmp_path)
    backup_dir = tmp_path / "backups"
    mgr = BackupManager(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", backup_dir=backup_dir)

    dest = mgr.create_backup()
    # Corrupt the backup copy directly (not the source).
    with open(dest / "mosaic.db", "r+b") as f:
        f.seek(100)
        f.write(b"\xff" * 50)

    assert mgr.verify_backup(dest) is False


def test_verify_backup_missing_file_returns_false(tmp_path):
    db_path = _make_real_db(tmp_path)
    backup_dir = tmp_path / "backups"
    mgr = BackupManager(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", backup_dir=backup_dir)
    dest = backup_dir / "2026-01-01T000000"
    dest.mkdir(parents=True)
    assert mgr.verify_backup(dest) is False


# ── Rotation / retention ───────────────────────────────────────────────────────


def test_rotate_backups_respects_max_backups(tmp_path):
    db_path = _make_real_db(tmp_path)
    backup_dir = tmp_path / "backups"
    mgr = BackupManager(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", backup_dir=backup_dir, max_backups=3)

    for _ in range(5):
        mgr.create_backup()

    remaining = [d for d in backup_dir.iterdir() if d.is_dir()]
    assert len(remaining) == 3


def test_rotate_backups_never_touches_non_matching_entries(tmp_path):
    """_rotate_backups deletes directories via shutil.rmtree selected purely
    by regex-matching their name (bucket 08, item 8 — "the regex-driven
    shutil.rmtree where a bug deletes directories"). A directory or file
    that doesn't match the timestamp pattern must survive rotation even
    when it sits right next to backups that get pruned, and even when
    rotation has more than enough matching candidates to hit max_backups
    without ever needing to touch them."""
    db_path = _make_real_db(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # A stray non-backup directory and file that happen to live alongside
    # real backups — must never be considered rotation candidates.
    stray_dir = backup_dir / "user-uploads"
    stray_dir.mkdir()
    (stray_dir / "keepme.txt").write_text("not a backup")
    stray_file = backup_dir / "README.txt"
    stray_file.write_text("not a backup either")
    # A directory that's *almost* a timestamp but doesn't fully match the
    # anchored pattern (extra suffix) — must also survive.
    almost_match = backup_dir / "2026-01-01T010101-notes"
    almost_match.mkdir()

    mgr = BackupManager(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", backup_dir=backup_dir, max_backups=2)
    for _ in range(4):
        mgr.create_backup()

    assert stray_dir.is_dir()
    assert (stray_dir / "keepme.txt").exists()
    assert stray_file.exists()
    assert almost_match.is_dir()

    real_backups = [d for d in backup_dir.iterdir() if d.is_dir() and d not in (stray_dir, almost_match)]
    assert len(real_backups) == 2


def test_main_uses_a_single_deliberate_max_backups_default():
    """main.py previously hardcoded max_backups=1000 while BackupManager's own
    default was 10, and nothing enforced which was in effect. Pin the single
    deliberate value main.py now uses.
    """
    import main
    assert main.MAX_BACKUPS == 30
    assert main.MAX_BACKUPS != 1000


# ── Mutation-triggered backups ─────────────────────────────────────────────────


def test_notify_mutation_backs_up_every_n_calls(tmp_path):
    db_path = _make_real_db(tmp_path)
    backup_dir = tmp_path / "backups"
    mgr = BackupManager(
        db_path=db_path, audit_log_path=tmp_path / "audit.jsonl",
        backup_dir=backup_dir, backup_every_n_mutations=3,
    )

    assert mgr.notify_mutation() is None
    assert mgr.notify_mutation() is None
    result = mgr.notify_mutation()
    assert result is not None
    assert (result / "mosaic.db").exists()

    # Counter resets — doesn't fire again until 3 more mutations.
    assert mgr.notify_mutation() is None
    assert mgr.notify_mutation() is None
    assert mgr.notify_mutation() is not None


def test_notify_mutation_disabled_when_not_configured(tmp_path):
    db_path = _make_real_db(tmp_path)
    mgr = BackupManager(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", backup_dir=tmp_path / "backups")
    for _ in range(10):
        assert mgr.notify_mutation() is None


def test_audit_logger_on_mutation_hook_triggers_backup(tmp_path):
    """AuditLogger.log() calls the on_mutation callback after a successful write."""
    from services.audit import AuditLogger

    calls = []
    logger = AuditLogger(tmp_path / "audit")
    logger.on_mutation = lambda: calls.append(1)

    logger.log("CREATE", "alice", {"id": 1})
    assert calls == [1]


def test_audit_logger_on_mutation_failure_does_not_raise(tmp_path):
    from services.audit import AuditLogger

    def _boom():
        raise RuntimeError("backup failed")

    logger = AuditLogger(tmp_path / "audit")
    logger.on_mutation = _boom
    logger.log("CREATE", "alice", {"id": 1})  # must not raise


# ── Startup integrity gate ─────────────────────────────────────────────────────


def test_check_db_integrity_detects_corruption(tmp_path, monkeypatch):
    import database

    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a real sqlite file" + b"\x00" * 100)

    corrupt_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(database, "engine", corrupt_engine)

    assert database.check_db_integrity() is False
    corrupt_engine.dispose()


def test_lifespan_refuses_to_start_when_integrity_check_fails(monkeypatch):
    import main

    monkeypatch.setattr(main, "check_db_integrity", lambda: False)

    backup_calls = []
    monkeypatch.setattr(
        "services.backup.BackupManager.create_backup",
        lambda self: backup_calls.append(1),
    )

    async def _run():
        async with main.lifespan(main.app):
            pass

    with pytest.raises(RuntimeError, match="integrity check FAILED"):
        asyncio.run(_run())

    assert backup_calls == []  # must not attempt a backup of a DB that failed its check


def test_lifespan_checks_integrity_before_running_any_ddl(monkeypatch):
    """Ordering guarantee. The old lifespan ran create_all() and the column
    ALTERs *before* the integrity check — i.e. it wrote to a database it had not
    yet established was readable. A corrupt database must never be written to.
    """
    import main

    calls = []
    monkeypatch.setattr(main, "check_db_integrity", lambda: calls.append("integrity") or False)
    monkeypatch.setattr(main, "create_db_and_tables", lambda: calls.append("create_all"))
    monkeypatch.setattr(main, "sync_schema", lambda engine: calls.append("sync_schema"))
    monkeypatch.setattr(main, "set_db_schema_version", lambda engine: calls.append("stamp"))

    async def _run():
        async with main.lifespan(main.app):
            pass

    with pytest.raises(RuntimeError, match="integrity check FAILED"):
        asyncio.run(_run())

    assert calls == ["integrity"]


# ── Uploads are part of a backup ───────────────────────────────────────────────


def test_backup_includes_uploads(tmp_path):
    """Avatars live under DATA_DIR/uploads/avatars but were excluded from every
    backup before v2.1.0, so "restore from backup" silently didn't restore
    everything."""
    db_path = _make_real_db(tmp_path)
    uploads = tmp_path / "uploads" / "avatars"
    uploads.mkdir(parents=True)
    (uploads / "alice.png").write_bytes(b"\x89PNGfake")

    mgr = BackupManager(
        db_path=db_path, audit_log_path=tmp_path / "audit.jsonl",
        backup_dir=tmp_path / "backups", uploads_dir=tmp_path / "uploads",
    )
    dest = mgr.create_backup()

    assert (dest / "uploads" / "avatars" / "alice.png").read_bytes() == b"\x89PNGfake"


def test_backup_works_when_there_are_no_uploads_yet(tmp_path):
    db_path = _make_real_db(tmp_path)
    mgr = BackupManager(
        db_path=db_path, audit_log_path=tmp_path / "audit.jsonl",
        backup_dir=tmp_path / "backups", uploads_dir=tmp_path / "nonexistent",
    )
    dest = mgr.create_backup()
    assert (dest / "mosaic.db").exists()


# ── BACKUP_PATH mirrors, it no longer relocates ────────────────────────────────


def test_mirror_is_additional_not_a_replacement(tmp_path):
    """The v2.0.0 behaviour was the dangerous one: setting BACKUP_PATH *moved*
    backups, so configuring a cloud folder silently switched local backups off.
    """
    db_path = _make_real_db(tmp_path)
    local = tmp_path / "backups"
    mirror = tmp_path / "mirror"
    mirror.mkdir()

    mgr = BackupManager(
        db_path=db_path, audit_log_path=tmp_path / "audit.jsonl",
        backup_dir=local, mirror_dir=mirror,
    )
    dest = mgr.create_backup()

    assert (dest / "mosaic.db").exists()                     # local copy kept
    assert (mirror / dest.name / "mosaic.db").exists()       # and mirrored
    assert dest.parent == local


def test_mirror_is_rotated_on_the_same_policy(tmp_path):
    """An off-site folder that is never pruned grows without bound."""
    db_path = _make_real_db(tmp_path)
    mirror = tmp_path / "mirror"
    mirror.mkdir()

    mgr = BackupManager(
        db_path=db_path, audit_log_path=tmp_path / "audit.jsonl",
        backup_dir=tmp_path / "backups", mirror_dir=mirror, max_backups=2,
    )
    for _ in range(4):
        mgr.create_backup()

    assert len([d for d in mirror.iterdir() if d.is_dir()]) == 2


def test_mirror_failure_never_costs_the_local_backup(tmp_path):
    """Off-site copying is redundancy. A broken mount must not take down the app
    or discard the local backup that already succeeded."""
    db_path = _make_real_db(tmp_path)
    local = tmp_path / "backups"
    # A *file* where a directory is expected — copytree raises OSError.
    broken_mirror = tmp_path / "not-a-dir"
    broken_mirror.write_text("this is a file")

    mgr = BackupManager(
        db_path=db_path, audit_log_path=tmp_path / "audit.jsonl",
        backup_dir=local, mirror_dir=broken_mirror,
    )
    dest = mgr.create_backup()  # must not raise

    assert (dest / "mosaic.db").exists()
    assert mgr.verify_backup(dest) is True


def test_a_backup_that_failed_verification_is_not_mirrored(tmp_path, monkeypatch):
    """Copying a known-bad backup off-site just spreads false confidence."""
    db_path = _make_real_db(tmp_path)
    mirror = tmp_path / "mirror"
    mirror.mkdir()

    mgr = BackupManager(
        db_path=db_path, audit_log_path=tmp_path / "audit.jsonl",
        backup_dir=tmp_path / "backups", mirror_dir=mirror,
    )
    monkeypatch.setattr(BackupManager, "verify_backup", lambda self, dest: False)

    mgr.create_backup()

    assert list(mirror.iterdir()) == []


# ── The mirror-path startup guard ──────────────────────────────────────────────


def test_local_backup_dir_is_always_inside_the_data_dir():
    import main
    assert main.BACKUP_DIR == main.DATA_DIR / "backups"


def test_startup_refuses_when_the_mirror_path_is_missing(tmp_path, monkeypatch):
    """The old code called mkdir(parents=True) on this path, so an unmounted
    target became a plain directory holding backups that synced nowhere — while
    logging "Backup created and verified"."""
    import main

    missing = tmp_path / "not-mounted-yet"
    monkeypatch.setattr(main, "BACKUP_MIRROR_DIR", missing)

    with pytest.raises(RuntimeError, match="does not exist"):
        main._assert_backup_mirror_usable()

    # Critically: it must not have created it as a side effect.
    assert not missing.exists()


def test_startup_accepts_an_existing_writable_mirror_path(tmp_path, monkeypatch):
    import main

    mirror = tmp_path / "mounted"
    mirror.mkdir()
    monkeypatch.setattr(main, "BACKUP_MIRROR_DIR", mirror)
    monkeypatch.setattr(main, "BACKUP_REQUIRE_MOUNT", False)

    main._assert_backup_mirror_usable()  # must not raise


def test_startup_is_a_no_op_when_no_mirror_is_configured(monkeypatch):
    import main

    monkeypatch.setattr(main, "BACKUP_MIRROR_DIR", None)
    main._assert_backup_mirror_usable()  # must not raise


def test_require_mount_rejects_a_plain_directory(tmp_path, monkeypatch):
    """Opt-in strictness for a genuine network/FUSE mount: an unmounted target is
    a normal empty directory, which is indistinguishable from a correct setup
    without this check."""
    import main

    mirror = tmp_path / "mountpoint"
    mirror.mkdir()
    monkeypatch.setattr(main, "BACKUP_MIRROR_DIR", mirror)
    monkeypatch.setattr(main, "BACKUP_REQUIRE_MOUNT", True)

    with pytest.raises(RuntimeError, match="not a mountpoint"):
        main._assert_backup_mirror_usable()

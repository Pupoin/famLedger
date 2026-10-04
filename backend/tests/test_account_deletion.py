"""Tests for account-deletion mode handling and avatar cleanup ordering."""

import pytest
from sqlmodel import select

from conftest import USER_B_LOGIN, PASSWORD_B, set_mode
from config import get_app_mode
from models import User
from users import get_user_by_username


def _delete_account(client, password=PASSWORD_B, data_action="delete"):
    return client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": password, "data_action": data_action},
    )


# ── App mode still forced to personal afterward ──────────────────────────────


def test_deletion_forces_personal_mode_with_one_user_remaining(auth_client_b, db):
    # conftest already seeds a "shared" Settings row (mirroring real 2nd-user
    # registration) — set_mode() here just makes that starting point explicit
    # rather than relying on the fixture default. Reads the mode through
    # get_app_mode() (the same resolver every route uses) rather than a raw
    # db.get(Settings, 1), which is exactly what the no-row variant below
    # needs to hit `None` on and would prove nothing either way here.
    set_mode(db, "shared")

    _delete_account(auth_client_b, data_action="delete")
    assert get_app_mode(db) == "personal"
    assert db.exec(select(User)).all() != []  # Alice still exists


def test_deletion_forces_personal_mode_with_no_settings_row(auth_client_b, db):
    """Same regression, but for the common case where Settings has never
    been written at all (a fresh install that never explicitly switched
    modes) — deletion must not crash trying to update a nonexistent row."""
    from sqlalchemy import text
    db.execute(text("DELETE FROM settings"))
    db.commit()

    _delete_account(auth_client_b, data_action="delete")
    assert get_app_mode(db) == "personal"


# ── Avatar deletion ordering (bucket 06, item 4) ──────────────────────────────
# The avatar file must only be removed after the DB commit succeeds — otherwise
# a commit failure leaves the account intact but the avatar file gone.


def test_avatar_removed_after_successful_deletion(auth_client_b, db, monkeypatch, tmp_path):
    import auth as auth_mod

    avatar_path = tmp_path / "bob.png"
    avatar_path.write_bytes(b"\x89PNG fake avatar")
    monkeypatch.setattr(
        auth_mod, "_find_avatar",
        lambda username: str(avatar_path) if username == USER_B_LOGIN else None,
    )

    resp = _delete_account(auth_client_b, data_action="delete")
    assert resp.status_code == 200
    assert not avatar_path.exists()


def test_avatar_file_untouched_until_commit_succeeds(auth_client_b, db, monkeypatch, tmp_path):
    """Regression test for the delete-before-commit ordering bug: force the
    avatar removal itself to fail, and confirm the DB commit already went
    through beforehand (proving removal now happens strictly after commit,
    not before it)."""
    import auth as auth_mod

    avatar_path = tmp_path / "bob.png"
    avatar_path.write_bytes(b"\x89PNG fake avatar")
    monkeypatch.setattr(
        auth_mod, "_find_avatar",
        lambda username: str(avatar_path) if username == USER_B_LOGIN else None,
    )

    def _boom(path):
        raise OSError("simulated failure removing avatar file")

    monkeypatch.setattr(auth_mod.os, "remove", _boom)

    with pytest.raises(OSError):
        _delete_account(auth_client_b, data_action="delete")

    # The account row is already gone even though the (post-commit) avatar
    # removal blew up — proving the commit happened first.
    assert get_user_by_username(db, USER_B_LOGIN) is None
    # And the file itself was never actually deleted, since os.remove was
    # mocked to raise instead of delete.
    assert avatar_path.exists()

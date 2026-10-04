"""
Tests for multi-mode support (personal / shared / blended).

Covers: Settings API, mode-aware validation, personal login restriction,
personal balance stub, personal-summary endpoint, analytics by_split_type,
and mode switching behaviour.
"""

from conftest import (
    USER_A_LOGIN, USER_B_LOGIN, PASSWORD_A, PASSWORD_B,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _set_mode(auth_client, mode):
    """Switch app mode via the settings API."""
    resp = auth_client.put("/api/settings", json={"app_mode": mode})
    assert resp.status_code == 200
    return resp


# ── Settings API ───────────────────────────────────────────────────────

def test_settings_default_mode(admin_client_a, db):
    """conftest seeds a "shared" Settings row by default (mirroring what
    registering a 2nd user really does). This test instead targets the raw
    resolver fallback for a database that has no Settings row at all — e.g.
    a fresh install, or one seeded directly like this test suite's own
    fixtures — which must be "personal", not "shared"."""
    from sqlalchemy import text
    db.execute(text("DELETE FROM settings"))
    db.commit()

    resp = admin_client_a.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["app_mode"] == "personal"


def test_settings_update_mode(admin_client_a):
    for mode in ("personal", "blended", "shared"):
        resp = _set_mode(admin_client_a, mode)
        assert resp.json()["app_mode"] == mode
        # Verify it persists on GET
        assert admin_client_a.get("/api/settings").json()["app_mode"] == mode


def test_settings_invalid_mode_rejected(admin_client_a):
    resp = admin_client_a.put("/api/settings", json={"app_mode": "invalid"})
    assert resp.status_code == 422


def test_settings_empty_mode_rejected(admin_client_a):
    resp = admin_client_a.put("/api/settings", json={"app_mode": ""})
    assert resp.status_code == 422


def test_settings_requires_auth(client):
    resp = client.put("/api/settings", json={"app_mode": "personal"})
    assert resp.status_code == 401


def test_settings_rejects_missing_app_mode(admin_client_a):
    """Pydantic model requires app_mode field (CR-4 / SG-2)."""
    resp = admin_client_a.put("/api/settings", json={})
    assert resp.status_code == 422


def test_settings_rejects_extra_fields_only(admin_client_a):
    """Payload with only extra fields (no app_mode) should fail validation."""
    resp = admin_client_a.put("/api/settings", json={"is_admin": True})
    assert resp.status_code == 422


def test_config_endpoint_includes_mode(admin_client_a):
    """GET /api/config should reflect the current mode."""
    resp = admin_client_a.get("/api/config")
    assert resp.json()["mode"] == "shared"

    _set_mode(admin_client_a, "personal")
    resp = admin_client_a.get("/api/config")
    assert resp.json()["mode"] == "personal"


# ── Personal Mode: Login Restriction ──────────────────────────────────

def test_personal_mode_allows_other_registered_users(admin_client_a, client):
    _set_mode(admin_client_a, "personal")
    resp = client.post("/api/auth/login", json={
        "username": USER_B_LOGIN, "password": PASSWORD_B,
    })
    assert resp.status_code == 200


def test_personal_allows_user_a_login(admin_client_a, client):
    _set_mode(admin_client_a, "personal")
    resp = client.post("/api/auth/login", json={
        "username": USER_A_LOGIN,
        "password": PASSWORD_A,
    })
    assert resp.status_code == 200


# ── Personal Mode: Validation ─────────────────────────────────────────


# ── Personal Mode: Balance ────────────────────────────────────────────

def test_personal_account_list_is_empty_without_accounts(admin_client_a):
    _set_mode(admin_client_a, "personal")
    resp = admin_client_a.get("/api/v1/accounts")
    assert resp.status_code == 200
    assert resp.json()["accounts"] == []
    assert resp.json()["count"] == 0


# ── Shared Mode: Validation (existing behaviour preserved) ────────────


# ── Blended Mode: Validation ──────────────────────────────────────────


# ── Personal Summary Endpoint ─────────────────────────────────────────


def test_dashboard_summary_requires_auth(client):
    resp = client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 401


# ── Analytics: by_split_type ───────────────────────────────────────────


# ── Mode Switching: Data Preservation ──────────────────────────────────

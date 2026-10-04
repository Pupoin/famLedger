"""Tests for audit logging on mode-switch mutations."""

import json


def _read_entries(audit_log):
    """Read all JSONL entries from the test audit log."""
    if not audit_log.log_path.exists():
        return []
    lines = audit_log.log_path.read_text().strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


# ── Mode-switch audit logging (07 #2) ───────────────────────────────────


def test_mode_change_generates_audit_entry(admin_client_a, audit_log):
    admin_client_a.put("/api/settings", json={"app_mode": "personal"})
    entries = _read_entries(audit_log)
    assert len(entries) == 1
    assert entries[0]["operation"] == "MODE_CHANGE"
    assert entries[0]["user"] == "alice"
    assert entries[0]["data"] == {"old_mode": "shared", "new_mode": "personal"}


def test_mode_change_to_same_mode_generates_no_audit_entry(admin_client_a, audit_log):
    """Setting the mode to what it already is is a no-op, not a real switch."""
    admin_client_a.put("/api/settings", json={"app_mode": "shared"})
    assert _read_entries(audit_log) == []

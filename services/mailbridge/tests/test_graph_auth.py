from contextlib import contextmanager
from unittest.mock import Mock

from backend.auth import graph_auth, state


def test_device_code_polling_releases_cache_lock_between_attempts(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "AUTH_STATE_PATH", tmp_path / "state.json")
    app = Mock()
    app.acquire_token_by_device_flow.side_effect = [
        {"error": "authorization_pending"}, {"error": "slow_down"}, {"access_token": "private"},
    ]
    events = []

    @contextmanager
    def application(*args):
        events.append("lock")
        try:
            yield app
        finally:
            events.append("unlock")

    monkeypatch.setattr(graph_auth, "_application", application)
    monkeypatch.setattr(graph_auth.time, "time", lambda: 100)
    monkeypatch.setattr(graph_auth.time, "sleep", lambda _: events.append("sleep"))
    assert graph_auth.complete_device_code_login("common", "app", (), tmp_path / "cache", {"expires_at": 1000})
    assert events == ["lock", "unlock", "sleep", "lock", "unlock", "sleep", "lock", "unlock"]
    assert state.load_auth_state()["status"] == "ok"
    assert app.acquire_token_by_device_flow.call_args.kwargs["exit_condition"]({}) is True


def test_expired_device_flow_does_not_poll_or_leave_a_displayable_code(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "AUTH_STATE_PATH", tmp_path / "state.json")
    state.set_auth_pending("EXPIRED", "https://microsoft.com/devicelogin", 1)
    application = Mock()
    monkeypatch.setattr(graph_auth, "_application", application)
    assert not graph_auth.complete_device_code_login("common", "app", (), tmp_path / "cache", {"expires_at": 1})
    application.assert_not_called()
    assert state.load_auth_state()["status"] == "failed"
    assert "user_code" not in state.load_auth_state()

from types import SimpleNamespace
from unittest.mock import Mock
import time

import pytest
from fastapi.testclient import TestClient
from backend.auth import web as auth_app
from backend.auth import state


@pytest.fixture(autouse=True)
def isolate_authentication(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "AUTH_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(auth_app, "active_flow", None)
    monkeypatch.setattr(auth_app, "checked_at", float("-inf"))
    cfg = SimpleNamespace(tenant_id="common", client_id="client", graph_scopes=("Mail.Read",), token_cache_path=tmp_path / "cache")
    monkeypatch.setattr(auth_app, "load_config", lambda: cfg)
    monkeypatch.setattr(auth_app, "acquire_graph_token", Mock(side_effect=auth_app.MicrosoftAuthorizationRequired()))


def test_only_authentication_interface_and_no_old_dashboard():
    with TestClient(auth_app.app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Microsoft" in page.text
        assert "ECharts" not in page.text
        assert "sankey" not in page.text.lower()
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/dashboard").status_code == 404
        assert client.get("/api/records_list").status_code == 404


def test_auth_state_exposes_no_internal_credentials(monkeypatch):
    monkeypatch.setattr(auth_app, "load_auth_state", lambda: {"status": "ok", "access_token": "secret", "client_id": "private"})
    monkeypatch.setattr(auth_app, "checked_at", time.monotonic())
    assert TestClient(auth_app.app).get("/api/auth/status").json() == {"status": "ok"}


def test_cross_origin_login_is_rejected_before_calling_microsoft(monkeypatch):
    initiate = Mock()
    monkeypatch.setattr(auth_app, "initiate_device_code_login", initiate)
    response = TestClient(auth_app.app).post("/api/auth/initiate", json={}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    initiate.assert_not_called()


def test_device_code_is_never_returned_to_browser(monkeypatch):
    cfg = SimpleNamespace(tenant_id="common", client_id="client", graph_scopes=("Mail.Read",), token_cache_path="cache")
    monkeypatch.setattr(auth_app, "load_config", lambda: cfg)
    monkeypatch.setattr(auth_app, "initiate_device_code_login", lambda *args: {"user_code": "ABCD1234", "device_code": "private-device-token", "verification_uri": "https://microsoft.com/devicelogin"})
    monkeypatch.setattr(auth_app, "complete_device_code_login", Mock(return_value=True))
    response = TestClient(auth_app.app).post("/api/auth/initiate", json={})
    assert response.status_code == 200
    assert response.json()["user_code"] == "ABCD1234"
    assert "device_code" not in response.json()
    assert "private-device-token" not in response.text


def test_login_form_content_type_is_rejected():
    response = TestClient(auth_app.app).post("/api/auth/initiate", data={"action": "login"})
    assert response.status_code == 415


def test_cached_login_is_checked_and_no_new_code_is_created(monkeypatch):
    cached = Mock(return_value=("private-token", "mailbox"))
    initiate = Mock()
    monkeypatch.setattr(auth_app, "acquire_graph_token", cached)
    monkeypatch.setattr(auth_app, "initiate_device_code_login", initiate)
    client = TestClient(auth_app.app)
    assert client.get("/api/auth/status").json()["status"] == "ok"
    assert client.get("/api/auth/status").json()["status"] == "ok"
    assert cached.call_count == 1  # Polling the page does not refresh tokens every three seconds.
    assert client.post("/api/auth/initiate", json={}).json() == {"status": "ok", "required": False}
    initiate.assert_not_called()


def test_force_reauthentication_uses_a_new_flow_even_with_cached_login(monkeypatch):
    cached = Mock(return_value=("private-token", "mailbox"))
    initiate = Mock(return_value={"user_code": "NEW-CODE", "device_code": "secret-device-code",
                                 "verification_uri": "https://login.microsoftonline.com/device", "expires_in": 600})
    monkeypatch.setattr(auth_app, "acquire_graph_token", cached)
    monkeypatch.setattr(auth_app, "initiate_device_code_login", initiate)
    monkeypatch.setattr(auth_app, "complete_device_code_login", Mock(return_value=True))
    before = time.time()
    response = TestClient(auth_app.app).post("/api/auth/initiate", json={"force": True})
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["user_code"] == "NEW-CODE"
    assert response.json()["verify_url"] == "https://login.microsoftonline.com/device"
    assert before + 600 <= response.json()["expires_at"] <= time.time() + 600
    cached.assert_not_called()
    initiate.assert_called_once()
    assert "secret-device-code" not in response.text


@pytest.mark.parametrize("authenticated", [True, False])
def test_stale_pending_code_after_restart_is_never_redisplayed(monkeypatch, authenticated):
    state.set_auth_pending("OLD-CODE", "https://microsoft.com/devicelogin", time.time() + 900)
    if authenticated:
        monkeypatch.setattr(auth_app, "acquire_graph_token", Mock(return_value=("token", "mailbox")))
    response = TestClient(auth_app.app).get("/api/auth/status")
    assert response.json()["status"] == ("ok" if authenticated else "failed")
    assert "user_code" not in response.json()
    assert "OLD-CODE" not in response.text


def test_active_flow_is_displayed_even_if_worker_updates_shared_status(monkeypatch):
    state.set_auth_ok()
    flow = {"user_code": "CURRENT", "verification_uri": "https://microsoft.com/devicelogin",
            "expires_at": time.time() + 900, "device_code": "secret"}
    monkeypatch.setattr(auth_app, "active_flow", flow)
    cached = Mock()
    monkeypatch.setattr(auth_app, "acquire_graph_token", cached)
    response = TestClient(auth_app.app).get("/api/auth/status")
    assert response.json()["status"] == "pending"
    assert response.json()["user_code"] == "CURRENT"
    assert "secret" not in response.text
    cached.assert_not_called()


def test_expired_active_code_is_never_returned(monkeypatch):
    state.set_auth_ok()
    monkeypatch.setattr(auth_app, "active_flow", {"user_code": "EXPIRED", "expires_at": time.time() - 1})
    assert "EXPIRED" not in TestClient(auth_app.app).get("/api/auth/status").text


def test_failed_status_check_does_not_display_stale_code(monkeypatch):
    state.set_auth_pending("OLD-CODE", "https://microsoft.com/devicelogin", time.time() + 900)
    monkeypatch.setattr(auth_app, "acquire_graph_token", Mock(side_effect=TimeoutError()))
    response = TestClient(auth_app.app).get("/api/auth/status")
    assert response.status_code == 503
    assert "OLD-CODE" not in response.text

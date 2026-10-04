"""Browser-facing origins reaching the API through a development proxy."""
import pytest
from fastapi.testclient import TestClient

import auth
from main import app


@pytest.mark.parametrize("origin", ["http://localhost:8888", "http://127.0.0.1:8888", "http://192.168.5.11:8888"])
def test_login_and_logout_with_stale_cookie_and_same_origin(origin):
    with TestClient(app, base_url=origin) as client:
        client.cookies.set(auth.SESSION_COOKIE, "stale-cookie-from-previous-server")
        response = client.post("/api/auth/login", headers={"Origin": origin, "X-FamLedger-CSRF": "1"},
                               json={"username": "alice", "password": "testpass_a"})
        assert response.status_code == 200, response.text
        assert client.get("/api/auth/me").status_code == 200
        response = client.post("/api/auth/logout", headers={"Origin": origin, "X-FamLedger-CSRF": "1"})
        assert response.status_code == 200, response.text
        assert client.get("/api/auth/me").status_code == 401


def test_login_with_cookie_rejects_host_rewritten_by_proxy(client):
    client.cookies.set(auth.SESSION_COOKIE, "stale-browser-cookie")
    response = client.post("/api/auth/login", headers={"Origin": "http://localhost:8888"},
                           json={"username": "alice", "password": "testpass_a"})
    assert response.status_code == 403
    assert response.json()["detail"] == "请求来源校验失败"


def test_login_with_cookie_still_rejects_untrusted_origin(client):
    client.cookies.set(auth.SESSION_COOKIE, "stale-browser-cookie")
    response = client.post("/api/auth/login", headers={"Origin": "https://evil.example", "X-FamLedger-CSRF": "1"},
                           json={"username": "alice", "password": "testpass_a"})
    assert response.status_code == 403


def test_explicit_cors_login_with_cookie_requires_csrf_header(client, monkeypatch):
    import main
    origin = "http://localhost:5173"
    monkeypatch.setattr(main, "CORS_ORIGINS", [origin])
    client.cookies.set(auth.SESSION_COOKIE, "stale-browser-cookie")
    response = client.post("/api/auth/login", headers={"Origin": origin},
                           json={"username": "alice", "password": "testpass_a"})
    assert response.status_code == 200, response.text
    del client.headers["X-FamLedger-CSRF"]
    response = client.post("/api/auth/login", headers={"Origin": origin},
                           json={"username": "alice", "password": "testpass_a"})
    assert response.status_code == 403

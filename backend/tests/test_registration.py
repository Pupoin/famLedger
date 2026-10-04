"""Registration roles, tenant isolation and immediate session tests."""
from sqlalchemy import text
from sqlmodel import select
from models import User
from conftest import set_mode

def _clear_users(db):
    db.execute(text("DELETE FROM users"))
    db.execute(text("DELETE FROM families"))
    db.execute(text("DELETE FROM settings"))
    db.commit()

def _register_payload(username, display_name, password="testpass123"):
    return dict(username=username, display_name=display_name, password=password,
                security_question="Favorite color?", security_answer="blue")

def test_first_registration_creates_admin_and_family(client, db):
    _clear_users(db)
    set_mode(db, "shared")
    resp = client.post("/api/auth/register", json=_register_payload("alice2", "Alice Two"))
    assert resp.status_code == 201
    user = db.exec(select(User).where(User.username == "alice2")).one()
    assert user.role == "admin" and user.family_id is not None
    assert client.get("/api/settings").json()["app_mode"] == "shared"

def test_second_registration_does_not_join_first_family(client, db):
    _clear_users(db)
    assert client.post("/api/auth/register", json=_register_payload("alice2", "Alice Two")).status_code == 201
    assert client.post("/api/auth/register", json=_register_payload("bob2", "Bob Two")).status_code == 201
    user = db.exec(select(User).where(User.username == "bob2")).one()
    assert user.role == "member" and user.family_id is None
    assert client.get("/api/auth/me").json()["user_map"] == {}

def test_registration_supports_more_than_two_users(client, db):
    _clear_users(db)
    for username in ("alice2", "bob2", "carol"):
        assert client.post("/api/auth/register", json=_register_payload(username, username)).status_code == 201
    assert len(db.exec(select(User)).all()) == 3
    assert client.get("/api/settings").json()["app_mode"] == "personal"

def test_registered_user_can_log_in_immediately(client, db):
    _clear_users(db)
    assert client.post("/api/auth/register", json=_register_payload("alice2", "Alice Two")).status_code == 201
    assert client.get("/api/auth/me").json()["username"] == "alice2"
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login", json={"username": "alice2", "password": "testpass123"})
    assert resp.status_code == 200 and resp.json()["username"] == "alice2"

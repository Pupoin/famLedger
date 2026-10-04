"""
Mosaic backend test configuration.

Bootstraps a mock config module and in-memory SQLite database
so tests run without .env files. Users are seeded in the DB.

Additional test dependencies (beyond requirements.txt):
    pip install pytest httpx
"""

import os
import sys
import types
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

import bcrypt
import pytest

# ── 1. Bootstrap mock config BEFORE any app imports ─────────────────
_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))

# Test user credentials (will be seeded into User table)
USER_A = "Alice"
USER_B = "Bob"
USER_A_LOGIN = "alice"
USER_B_LOGIN = "bob"
PASSWORD_A = "testpass_a"
PASSWORD_B = "testpass_b"
SECRET_KEY = "test-secret-key-for-unit-tests-only"
SECURITY_QUESTION = "What is your favorite color?"
SECURITY_ANSWER = "blue"

_config = types.ModuleType("config")
_config.SECRET_KEY = SECRET_KEY
_config.BACKUP_PATH = ""
_config.VALID_MODES = {"personal", "shared", "blended"}
_config.settings = _config

def _get_app_mode(session) -> str:
    """Delegate to the real get_app_mode (config.example.py) rather than
    reimplementing it — a hand-rolled copy here previously defaulted to
    "shared" with no Settings row, while the shipped default is "personal";
    dozens of tests ran under a mode-resolver that wasn't the real one."""
    from models import Settings
    row = session.get(Settings, 1)
    if row and row.app_mode in _config.VALID_MODES:
        return row.app_mode
    return "personal"

_config.get_app_mode = _get_app_mode
sys.modules["config"] = _config

os.environ["SECRET_KEY"] = SECRET_KEY

# ── 2. Now safe to import app modules ───────────────────────────────
from sqlalchemy import text, event
from sqlalchemy.engine import Engine
import sqlite3

@event.listens_for(Engine, "connect")
def _enable_test_foreign_keys(connection, record):
    if isinstance(connection, sqlite3.Connection):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine
from fastapi.testclient import TestClient

import database
from main import app
from models import User
from auth import hash_password, _hash_answer
_hash_a = hash_password(PASSWORD_A)
_hash_b = hash_password(PASSWORD_B)
_answer_hash = _hash_answer(SECURITY_ANSWER)
from services.audit import AuditLogger

# ── 3. In-memory test database (shared via StaticPool) ──────────────
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

database.engine = _test_engine


def _get_test_session():
    with Session(_test_engine) as session:
        yield session


app.dependency_overrides[database.get_session] = _get_test_session


# ── 4. Replace lifespan (skip backups & integrity checks) ───────────
@asynccontextmanager
async def _test_lifespan(app):
    SQLModel.metadata.create_all(_test_engine)
    yield


app.router.lifespan_context = _test_lifespan


# ── 5. Fixtures ─────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_db():
    """Ensure tables exist before each test, seed users, clear data after."""
    app.dependency_overrides[database.get_session] = _get_test_session
    SQLModel.metadata.create_all(_test_engine)

    # Seed test users into the User table
    with Session(_test_engine) as s:
        # Clear existing users and settings first
        s.execute(text("PRAGMA defer_foreign_keys=ON"))
        for table in reversed(SQLModel.metadata.sorted_tables):
            s.execute(table.delete())
        s.add(User(
            username=USER_A_LOGIN,
            display_name=USER_A,
            password_hash=_hash_a,
            security_question=SECURITY_QUESTION,
            security_answer_hash=_answer_hash,
        ))
        s.add(User(
            username=USER_B_LOGIN,
            display_name=USER_B,
            password_hash=_hash_b,
            security_question=SECURITY_QUESTION,
            security_answer_hash=_answer_hash,
        ))
        # Start mode tests from an explicit shared setting; registration does not change it.
        from models import Settings
        s.add(Settings(id=1, app_mode="shared"))
        s.commit()

    yield

    with Session(_test_engine) as s:
        s.execute(text("PRAGMA defer_foreign_keys=ON"))
        for table in reversed(SQLModel.metadata.sorted_tables):
            s.execute(table.delete())
        s.commit()


@pytest.fixture(autouse=True)
def _reset_password_reset_rate_limiter():
    """auth._reset_attempts is a module-level dict keyed by username and
    real wall-clock time, entirely independent of the DB — _clean_db never
    touches it. Left alone, a test that trips the forgot-password rate
    limiter would leak failed-attempt counts into any later test in the
    same run that happens to touch the same username within the 5-minute
    window, which easily includes an entire fast test session."""
    import auth as auth_mod
    auth_mod._reset_attempts.clear()
    yield
    auth_mod._reset_attempts.clear()


@pytest.fixture(autouse=True)
def _clear_embedding_cache():
    """services/clustering.py caches description -> embedding globally
    (process-wide, keyed only by description text) so it never re-embeds an
    immutable string twice. That's safe across real requests, but
    test_clustering.py swaps in a fake model with hand-built vectors for
    specific description strings (e.g. "Netflix") -- if a real-model
    embedding for that same string is already cached from another test
    (test_insights.py legitimately uses "Netflix" too), the fake model
    would never even be called."""
    import services.clustering as clustering_mod
    clustering_mod._embedding_cache.clear()
    yield
    clustering_mod._embedding_cache.clear()


@pytest.fixture(autouse=True)
def _clear_insights_cache():
    """services/insights_cache.py is a process-wide dict keyed by
    (user, mode, day), entirely independent of the DB -- _clean_db wiping
    the tables doesn't clear it. Left alone, a cached /insights payload from
    one test would leak into the next test for the same user on the same
    day, e.g. test_mode_in_response's second `set_mode` call bypasses the
    audited /api/settings endpoint (it writes the Settings row directly),
    so the mutation-triggered cache-clear hook never fires for it."""
    import services.insights_cache as cache_mod
    cache_mod.clear()
    yield
    cache_mod.clear()


@pytest.fixture(autouse=True)
def audit_log(tmp_path):
    """Redirect audit logging to a temp directory per test."""
    import services.audit as audit_mod
    import routes.insights as insights_mod
    import auth as auth_mod
    import main as main_mod

    test_logger = AuditLogger(tmp_path / "audit")
    old_audit = audit_mod.audit_logger
    old_insights = getattr(insights_mod, "audit_logger", None)
    old_auth = auth_mod.audit_logger
    old_main = main_mod.audit_logger

    audit_mod.audit_logger = test_logger
    if old_insights:
        insights_mod.audit_logger = test_logger
    auth_mod.audit_logger = test_logger
    main_mod.audit_logger = test_logger

    yield test_logger

    audit_mod.audit_logger = old_audit
    if old_insights:
        insights_mod.audit_logger = old_insights
    auth_mod.audit_logger = old_auth
    main_mod.audit_logger = old_main


@pytest.fixture
def client():
    """Unauthenticated test client."""
    with TestClient(app, headers={"X-FamLedger-CSRF": "1"}) as c:
        yield c


@pytest.fixture
def auth_client_a():
    """Test client authenticated as User A (Alice)."""
    with TestClient(app, headers={"X-FamLedger-CSRF": "1"}) as c:
        resp = c.post("/api/auth/login", json={
            "username": USER_A_LOGIN,
            "password": PASSWORD_A,
        })
        assert resp.status_code == 200
        yield c


@pytest.fixture
def auth_client_b():
    """Test client authenticated as User B (Bob)."""
    with TestClient(app, headers={"X-FamLedger-CSRF": "1"}) as c:
        resp = c.post("/api/auth/login", json={
            "username": USER_B_LOGIN,
            "password": PASSWORD_B,
        })
        assert resp.status_code == 200
        yield c


@pytest.fixture
def db():
    """Direct database session for seeding test data."""
    with Session(_test_engine) as s:
        yield s


def make_expense(**overrides) -> dict:
    """Build an expense JSON payload with sensible defaults."""
    data = {
        "date": str(date.today()),
        "description": "Test expense",
        "amount": 100.00,
        "category": "Groceries",
        "paid_by": USER_A,
        "split_method": "50/50",
    }
    data.update(overrides)
    return data


def make_income(**overrides) -> dict:
    """Build an income JSON payload with sensible defaults."""
    data = {
        "date": str(date.today()),
        "amount": 1000.00,
        "source": "Salary / Wages",
        "notes": None,
    }
    data.update(overrides)
    return data


def set_mode(db_session, mode: str) -> None:
    """Helper to set app mode in the test database."""
    from models import Settings
    row = db_session.get(Settings, 1)
    if row:
        row.app_mode = mode
    else:
        row = Settings(id=1, app_mode=mode)
    db_session.add(row)
    db_session.commit()


@pytest.fixture
def admin_client_a(auth_client_a, db):
    from sqlmodel import select
    user = db.exec(select(User).where(User.username == USER_A_LOGIN)).one()
    user.role = "admin"
    db.add(user)
    db.commit()
    return auth_client_a


@pytest.fixture
def service_family(db, monkeypatch):
    from models import Family
    family = Family(name='Explicit service test family')
    db.add(family)
    db.commit()
    monkeypatch.setenv('FAMLEDGER_SERVICE_FAMILY_ID', str(family.id))
    return family


@pytest.fixture(autouse=True)
def _bind_test_service_family(monkeypatch):
    from models import Family
    monkeypatch.delenv("FAMLEDGER_SERVICE_FAMILY_ID", raising=False)
    def bind(mapper, connection, family):
        if not os.getenv("FAMLEDGER_SERVICE_FAMILY_ID"):
            monkeypatch.setenv("FAMLEDGER_SERVICE_FAMILY_ID", str(family.id))
    event.listen(Family, "after_insert", bind)
    yield
    event.remove(Family, "after_insert", bind)

@pytest.fixture
def oidc_flow(client, db, monkeypatch):
    """A real signed ID token through authorize/callback, with HTTP transport mocked."""
    import uuid, time
    from types import SimpleNamespace
    from urllib.parse import urlsplit, parse_qs
    from authlib.jose import JsonWebKey, JsonWebToken
    from models import SSOProvider, OIDCLogin
    from routes import v1_oidc
    key = JsonWebKey.generate_key('RSA', 2048, is_private=True, options={'kid': 'test-key'})
    def prepare(policy=None, claims_update=None, userinfo_update=None, name=None):
        name = name or 'idp_' + uuid.uuid4().hex
        username = 'jit_' + uuid.uuid4().hex
        issuer = 'https://identity.example.com'
        provider = SSOProvider(name=name, label='Test', issuer=issuer, client_id='client',
                               client_secret_encrypted='secret', settings=policy or {})
        db.add(provider)
        db.commit()
        discovery = {'issuer': issuer, 'authorization_endpoint': issuer+'/authorize',
                     'token_endpoint': issuer+'/token', 'userinfo_endpoint': issuer+'/userinfo',
                     'jwks_uri': issuer+'/jwks', 'id_token_signing_alg_values_supported': ['RS256']}
        async def config(_issuer):
            return discovery
        monkeypatch.setattr(v1_oidc, '_get_oidc_config', config)
        monkeypatch.setattr(v1_oidc, 'decrypt_secret', lambda value: value)
        authorization = client.get(f'/api/v1/auth/sso/{name}/authorize', follow_redirects=False)
        assert authorization.status_code == 307
        query = parse_qs(urlsplit(authorization.headers['location']).query)
        state = query['state'][0]
        login = db.get(OIDCLogin, state)
        calls = []
        claims = {'iss': issuer, 'aud': 'client', 'sub': username, 'nonce': login.nonce,
                  'iat': int(time.time()), 'exp': int(time.time())+300}
        claims.update(claims_update or {})
        signed = JsonWebToken(['RS256']).encode({'alg': 'RS256', 'kid': 'test-key'}, claims, key).decode()
        info = {'sub': username, 'preferred_username': username, 'email': username+'@example.com',
                'email_verified': True}
        info.update(userinfo_update or {})
        async def transport(_client, method, url, **kwargs):
            calls.append((method, url, kwargs))
            if url.endswith('/token'):
                assert kwargs['data']['code_verifier'] == login.code_verifier
                data = {'access_token': 'access', 'id_token': signed}
            elif url.endswith('/jwks'):
                data = {'keys': [key.as_dict(is_private=False)]}
            elif url.endswith('/userinfo'):
                data = info
            else:
                raise AssertionError(url)
            return SimpleNamespace(status_code=200, json=lambda: data, text='')
        monkeypatch.setattr(v1_oidc, '_oidc_http', transport)
        return SimpleNamespace(provider=provider, username=username, state=state, query=query,
                               path=f'/api/v1/auth/sso/{name}/callback?code=code&state={state}', calls=calls)
    return prepare

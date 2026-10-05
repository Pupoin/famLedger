"""Linking proves control of both accounts and never trusts an email alone."""
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import Column, MetaData, Table, text
from sqlalchemy.dialects import postgresql
from sqlmodel import create_engine, select

import auth
from models import OIDCIdentity, OIDCLogin, User
from routes import v1_oidc
from services.schema import sync_schema


@pytest.fixture(autouse=True)
def clean_login_limits():
    auth._login_attempts.clear()
    yield
    auth._login_attempts.clear()


def local_user(db, name='alice'):
    return db.exec(select(User).where(User.username == name)).one()


def prepare_pending(client, db, oidc_flow, **overrides):
    user = local_user(db)
    user.email = 'alice@example.com'
    db.add(user)
    db.commit()
    info = {'email': 'alice@example.com'}
    info.update(overrides.pop('userinfo_update', {}))
    flow = oidc_flow(userinfo_update=info, **overrides)
    response = client.get(flow.path, follow_redirects=False)
    assert response.status_code == 302, response.text
    assert urlsplit(response.headers['location']).path == '/oidc-link'
    assert parse_qs(urlsplit(response.headers['location']).query)['state'] == [flow.state]
    db.expire_all()
    return flow, user


def complete(client, flow, password='testpass_a'):
    return client.post('/api/v1/auth/sso/link-requests/complete',
                       json={'state': flow.state, 'password': password})


def test_same_email_requires_password_once_and_then_uses_bound_subject(client, db, oidc_flow):
    flow, user = prepare_pending(client, db, oidc_flow)
    original = (user.id, user.username, user.email, user.password_hash, user.role, user.family_id)
    assert db.exec(select(OIDCIdentity)).all() == []
    assert len(db.exec(select(User)).all()) == 2
    assert client.get('/api/auth/me').status_code == 401
    preview = client.get(f'/api/v1/auth/sso/link-requests/{flow.state}')
    assert preview.json() == {'username': 'alice', 'provider_label': 'Test'}
    assert preview.headers['cache-control'] == 'no-store'
    assert complete(client, flow, 'wrong-password').status_code == 400
    assert db.exec(select(OIDCIdentity)).all() == []
    result = complete(client, flow)
    assert result.status_code == 200, result.text
    assert result.json()['username'] == 'alice'
    identity = db.exec(select(OIDCIdentity)).one()
    assert identity.user_id == user.id and identity.uid == flow.username
    db.refresh(user)
    assert (user.id, user.username, user.email, user.password_hash, user.role, user.family_id) == original
    assert client.get('/api/auth/me').json()['username'] == 'alice'
    assert complete(client, flow).status_code == 400

    # Email and username changes at the provider must not move the binding.
    followup = oidc_flow(provider=flow.provider, claims_update={'sub': flow.username},
                         userinfo_update={'sub': flow.username, 'preferred_username': 'bob',
                                          'email': 'changed@example.com'})
    response = client.get(followup.path, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'] == '/'
    assert client.get('/api/auth/me').json()['username'] == 'alice'
    assert len(db.exec(select(User)).all()) == 2
    assert len(db.exec(select(OIDCIdentity)).all()) == 1


def test_email_match_is_case_insensitive_and_precedes_username(client, db, oidc_flow):
    flow, user = prepare_pending(client, db, oidc_flow,
                                  userinfo_update={'email': 'ALICE@EXAMPLE.COM', 'preferred_username': 'bob'})
    assert db.get(OIDCLogin, flow.state).link_user_id == user.id
    assert complete(client, flow).status_code == 200
    assert db.exec(select(OIDCIdentity)).one().user_id == user.id


def test_same_name_suggests_confirmation_without_auto_takeover(client, db, oidc_flow):
    flow = oidc_flow(userinfo_update={'preferred_username': 'ALICE'})
    response = client.get(flow.path, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'].startswith('/oidc-link?')
    assert db.exec(select(OIDCIdentity)).all() == []
    assert client.get('/api/auth/me').status_code == 401
    assert complete(client, flow, 'testpass_b').status_code == 400
    assert complete(client, flow).status_code == 200


def test_existing_account_can_link_when_jit_is_disabled(client, db, oidc_flow):
    flow, user = prepare_pending(client, db, oidc_flow, policy={'allow_jit': False})
    assert complete(client, flow).status_code == 200
    assert db.exec(select(OIDCIdentity)).one().user_id == user.id


def test_email_is_only_a_suggestion_even_if_not_verified(client, db, oidc_flow):
    flow, _ = prepare_pending(client, db, oidc_flow, userinfo_update={'email_verified': False})
    assert db.exec(select(OIDCIdentity)).all() == []
    assert complete(client, flow, 'wrong-password').status_code == 400
    assert complete(client, flow).status_code == 200


@pytest.mark.parametrize('change', ['expired', 'password_changed', 'disabled_user', 'disabled_provider', 'issuer', 'client'])
def test_pending_request_invalidates_on_expiry_or_security_changes(client, db, oidc_flow, change):
    flow, user = prepare_pending(client, db, oidc_flow)
    login = db.get(OIDCLogin, flow.state)
    if change == 'expired':
        login.expires_at = int(time.time()) - 1
    elif change == 'password_changed':
        user.session_version += 1
    elif change == 'disabled_user':
        user.is_active = False
    elif change == 'disabled_provider':
        flow.provider.enabled = False
    elif change == 'issuer':
        flow.provider.issuer = 'https://replacement.example.com'
    else:
        flow.provider.client_id = 'replacement-client'
    db.add_all([login, user, flow.provider])
    db.commit()
    assert client.get(f'/api/v1/auth/sso/link-requests/{flow.state}').status_code == 400
    assert complete(client, flow).status_code == 400
    assert db.exec(select(OIDCIdentity)).all() == []


def test_pending_state_requires_matching_browser_cookie(client, auth_client_b, db, oidc_flow):
    flow, _ = prepare_pending(client, db, oidc_flow)
    assert auth_client_b.get(f'/api/v1/auth/sso/link-requests/{flow.state}').status_code == 400
    assert complete(auth_client_b, flow).status_code == 400
    assert db.exec(select(OIDCIdentity)).all() == []
    assert complete(client, flow).status_code == 200


def test_malformed_link_state_is_rejected_without_server_error(client):
    client.cookies.set('famledger_oidc_state', 'valid-state')
    assert client.get('/api/v1/auth/sso/link-requests/非正常请求').status_code == 400
    assert client.post('/api/v1/auth/sso/link-requests/complete',
                        json={'state': '非正常请求', 'password': 'testpass_a'}).status_code == 400


def test_pending_password_attempts_are_rate_limited(client, db, oidc_flow):
    flow, _ = prepare_pending(client, db, oidc_flow)
    for _ in range(5):
        assert complete(client, flow, 'wrong-password').status_code == 400
    assert complete(client, flow).status_code == 429
    assert db.exec(select(OIDCIdentity)).all() == []


def test_passwordless_collision_points_to_existing_sign_in_method(client, db, oidc_flow):
    user = local_user(db)
    user.password_hash = None
    db.add(user)
    db.commit()
    flow = oidc_flow(userinfo_update={'preferred_username': 'alice'})
    response = client.get(flow.path, follow_redirects=False)
    assert response.status_code == 409 and '没有本地密码' in response.json()['detail']
    assert db.exec(select(OIDCIdentity)).all() == []


def test_profile_link_keeps_current_account_despite_different_external_email(auth_client_a, auth_client_b, db, oidc_flow):
    cookie = auth_client_a.cookies.get(auth.SESSION_COOKIE)
    bob = local_user(db, 'bob')
    bob.email = 'bob@example.com'
    db.add(bob)
    db.commit()
    flow = oidc_flow(link_client=auth_client_a,
                     userinfo_update={'preferred_username': 'bob', 'email': 'bob@example.com'})
    response = auth_client_a.get(flow.path, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'] == '/settings?tab=profile&sso_link=success'
    assert auth_client_a.cookies.get(auth.SESSION_COOKIE) == cookie
    assert db.exec(select(OIDCIdentity)).one().user_id == local_user(db).id
    own = auth_client_a.get('/api/v1/auth/sso/account-links').json()
    other = auth_client_b.get('/api/v1/auth/sso/account-links').json()
    assert own['has_password'] is True and own['providers'][0]['linked'] is True
    assert other['providers'][0]['linked'] is False
    assert 'uid' not in own['providers'][0]
    assert len(db.exec(select(User)).all()) == 2


@pytest.mark.parametrize('change', ['logout', 'other_user', 'other_session', 'password_changed'])
def test_profile_link_is_bound_to_initiating_session(auth_client_a, db, oidc_flow, change):
    flow = oidc_flow(link_client=auth_client_a)
    user = local_user(db)
    if change == 'logout':
        assert auth_client_a.post('/api/auth/logout').status_code == 200
    elif change == 'password_changed':
        user.session_version += 1
        db.add(user)
        db.commit()
    else:
        if change == 'other_user':
            user = local_user(db, 'bob')
        auth_client_a.cookies.set(auth.SESSION_COOKIE, auth._make_token(user.username, user_id=user.id),
                                  domain='testserver.local', path='/')
    response = auth_client_a.get(flow.path, follow_redirects=False)
    assert response.status_code == 401, response.text
    assert flow.calls == []
    assert db.exec(select(OIDCIdentity)).all() == []


def test_profile_link_cannot_move_someone_elses_identity(auth_client_a, db, oidc_flow):
    flow = oidc_flow(link_client=auth_client_a)
    bob = local_user(db, 'bob')
    db.add(OIDCIdentity(user_id=bob.id, provider=flow.provider.name, uid=flow.username, issuer=flow.provider.issuer))
    db.commit()
    response = auth_client_a.get(flow.path, follow_redirects=False)
    assert response.status_code == 409
    assert db.exec(select(OIDCIdentity)).one().user_id == bob.id
    assert auth_client_a.get('/api/auth/me').json()['username'] == 'alice'


def test_identity_claimed_while_waiting_cannot_be_reassigned(client, db, oidc_flow):
    flow, _ = prepare_pending(client, db, oidc_flow)
    bob = local_user(db, 'bob')
    db.add(OIDCIdentity(user_id=bob.id, provider=flow.provider.name, uid=flow.username, issuer=flow.provider.issuer))
    db.commit()
    assert complete(client, flow).status_code == 409
    assert db.exec(select(OIDCIdentity)).one().user_id == bob.id
    assert client.get('/api/auth/me').status_code == 401


def test_profile_link_rechecks_password_version_after_external_requests(auth_client_a, db, oidc_flow, monkeypatch):
    flow = oidc_flow(link_client=auth_client_a)
    transport = v1_oidc._oidc_http
    async def change_during_http(http_client, method, url, **kwargs):
        result = await transport(http_client, method, url, **kwargs)
        if url.endswith('/userinfo'):
            user = local_user(db)
            user.session_version += 1
            db.add(user)
            db.commit()
        return result
    monkeypatch.setattr(v1_oidc, '_oidc_http', change_during_http)
    assert auth_client_a.get(flow.path, follow_redirects=False).status_code == 401
    assert db.exec(select(OIDCIdentity)).all() == []


def test_link_confirmation_respects_verified_email_domain_policy(client, db, oidc_flow):
    user = local_user(db)
    user.email = 'alice@example.com'
    db.add(user)
    db.commit()
    flow = oidc_flow(policy={'allowed_domains': ['example.com']},
                     userinfo_update={'email': 'alice@example.com', 'email_verified': False})
    assert client.get(flow.path, follow_redirects=False).status_code == 403
    assert db.exec(select(OIDCIdentity)).all() == []


def test_profile_link_requires_cookie_auth_password_and_csrf(client, auth_client_a, db, oidc_flow):
    flow = oidc_flow()
    path = f'/api/v1/auth/sso/{flow.provider.name}/link'
    assert client.get('/api/v1/auth/sso/account-links').status_code == 401
    assert client.post(path, json={'current_password': 'testpass_a'}).status_code == 401
    assert client.post(path, json={'current_password': 'testpass_a'}, headers={'X-API-Key': 'synthetic'}).status_code == 401
    assert auth_client_a.post(path, json={}).status_code == 400
    assert auth_client_a.post(path, json={'current_password': 'wrong'}).status_code == 400
    assert auth_client_a.post(path, json={'current_password': 'testpass_a'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert db.exec(select(OIDCIdentity)).all() == []


def test_existing_sso_session_can_link_without_local_password(auth_client_a, db, oidc_flow):
    user = local_user(db)
    user.password_hash = None
    db.add(user)
    db.commit()
    flow = oidc_flow(link_client=auth_client_a)
    response = auth_client_a.get(flow.path, follow_redirects=False)
    assert response.status_code == 302
    assert db.exec(select(OIDCIdentity)).one().user_id == user.id


def test_invalid_id_token_never_creates_link(auth_client_a, db, oidc_flow):
    flow = oidc_flow(link_client=auth_client_a, claims_update={'nonce': 'wrong'})
    assert auth_client_a.get(flow.path, follow_redirects=False).status_code == 401
    assert db.exec(select(OIDCIdentity)).all() == []


def test_link_columns_are_added_without_changing_old_flows():
    names = {'link_user_id', 'link_uid', 'link_session_id', 'link_session_version'}
    target_metadata = MetaData()
    target = OIDCLogin.__table__.to_metadata(target_metadata)
    old_metadata = MetaData()
    old = Table('oidc_logins', old_metadata, *[
        Column(col.name, col.type, primary_key=col.primary_key, nullable=col.nullable)
        for col in target.columns if col.name not in names
    ])
    engine = create_engine('sqlite:///:memory:')
    old_metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(old.insert().values(id='old-state', provider_id=uuid.uuid4(), issuer='https://idp.example.com',
            client_id='client', redirect_uri='https://app.example.com/callback', nonce='nonce', code_verifier='verifier',
            expires_at=123, consumed=False))
    statements = sync_schema(engine, metadata=target_metadata)
    assert len(statements) == 4
    with engine.connect() as connection:
        row = connection.execute(text('SELECT * FROM oidc_logins')).mappings().one()
        assert row['id'] == 'old-state'
        assert all(row[name] is None for name in names)
    assert sync_schema(engine, metadata=target_metadata) == []
    for name in names:
        assert target.c[name].nullable
        assert target.c[name].type.compile(dialect=postgresql.dialect())
    engine.dispose()

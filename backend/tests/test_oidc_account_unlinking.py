"""Unlink only the caller's identities without losing access or reviving sessions."""
import hashlib
import uuid

import pytest
from sqlmodel import select

import auth
from models import ApiKey, OIDCIdentity, SSOProvider, User
from routes import v1_oidc


@pytest.fixture(autouse=True)
def clean_login_limits():
    auth._login_attempts.clear()
    yield
    auth._login_attempts.clear()


def user_for(db, name='alice'):
    return db.exec(select(User).where(User.username == name)).one()


def bind(db, name='authelia', user=None, provider=None):
    user = user or user_for(db)
    provider = provider or SSOProvider(name=name, label=name.title(), issuer=f'https://{name}.example.com',
                                       client_id='client', client_secret_encrypted='secret')
    db.add(provider)
    identity = OIDCIdentity(user_id=user.id, provider=provider.name, issuer=provider.issuer, uid=uuid.uuid4().hex)
    db.add(identity)
    db.commit()
    return provider, identity


def unlink(client, name='authelia', password='testpass_a', **kwargs):
    return client.request('DELETE', f'/api/v1/auth/sso/{name}/link',
                          json={'current_password': password}, **kwargs)


def test_unlink_revokes_old_sessions_but_preserves_current_browser_and_other_users(auth_client_a, auth_client_b, db):
    user = user_for(db)
    bob = user_for(db, 'bob')
    original = (user.id, user.username, user.password_hash, user.family_id)
    provider, first = bind(db)
    _, second = bind(db, provider=provider)
    _, foreign = bind(db, user=bob, provider=provider)
    first_id, second_id, foreign_id = first.id, second.id, foreign.id
    other_browser = auth._make_token(user.username, user_id=user.id, session_version=user.session_version)
    current_cookie = auth_client_a.cookies.get(auth.SESSION_COOKIE)
    response = unlink(auth_client_a)
    assert response.status_code == 200 and response.json() == {'status': 'unlinked'}
    assert response.headers['cache-control'] == 'no-store'
    assert auth_client_a.cookies.get(auth.SESSION_COOKIE) != current_cookie
    assert auth._verify_token(current_cookie) is None
    assert auth._verify_token(other_browser) is None
    assert auth_client_a.get('/api/auth/me').json()['username'] == 'alice'
    assert auth_client_b.get('/api/auth/me').json()['username'] == 'bob'
    db.expire_all()
    assert db.get(OIDCIdentity, first_id) is None
    assert db.get(OIDCIdentity, second_id) is None
    assert db.get(OIDCIdentity, foreign_id).user_id == bob.id
    assert (user.id, user.username, user.password_hash, user.family_id) == original
    assert db.get(SSOProvider, provider.id) is not None
    assert auth_client_a.get('/api/v1/auth/sso/account-links').json()['providers'][0]['has_binding'] is False


@pytest.mark.parametrize('password', [None, '', 'wrong'])
def test_unlink_requires_correct_local_password(auth_client_a, db, password):
    _, identity = bind(db)
    assert unlink(auth_client_a, password=password).status_code == 400
    assert db.get(OIDCIdentity, identity.id) is not None
    assert auth_client_a.get('/api/auth/me').status_code == 200


def test_unlink_cannot_remove_another_users_identity(auth_client_b, db):
    _, identity = bind(db)
    assert unlink(auth_client_b, password='testpass_b').status_code == 404
    assert db.get(OIDCIdentity, identity.id) is not None


def test_unlink_rejects_api_key_auth_and_cross_site_requests(client, auth_client_a, db):
    _, identity = bind(db)
    raw_key = 'synthetic-api-key-for-unlink-test'
    key = ApiKey(user_id=user_for(db).id, name='Test key', key_prefix='synthetic',
                 hashed_key=hashlib.sha256(raw_key.encode()).hexdigest())
    db.add(key)
    db.commit()
    assert unlink(client, headers={'X-API-Key': raw_key}).status_code == 401
    assert unlink(auth_client_a, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert db.get(OIDCIdentity, identity.id) is not None
    assert db.get(ApiKey, key.id).is_revoked is False


def test_unlink_wrong_password_is_rate_limited(auth_client_a, db):
    _, identity = bind(db)
    for _ in range(5):
        assert unlink(auth_client_a, password='wrong').status_code == 400
    assert unlink(auth_client_a).status_code == 429
    assert db.get(OIDCIdentity, identity.id) is not None


def test_passwordless_user_cannot_remove_only_login(auth_client_a, db):
    user = user_for(db)
    user.password_hash = None
    db.add(user)
    _, identity = bind(db)
    options = auth_client_a.get('/api/v1/auth/sso/account-links').json()
    assert options['has_password'] is False
    assert options['providers'][0]['can_unlink'] is False
    response = unlink(auth_client_a, password=None)
    assert response.status_code == 409 and '唯一' in response.json()['detail']
    assert db.get(OIDCIdentity, identity.id) is not None


@pytest.mark.parametrize('unusable', ['disabled', 'issuer_changed', 'deleted', 'unlinked', 'belongs_to_other_user'])
def test_unavailable_or_foreign_login_does_not_allow_last_unlink(auth_client_a, db, unusable):
    user = user_for(db)
    user.password_hash = None
    db.add(user)
    _, identity = bind(db)
    other, other_identity = bind(db, name='second')
    if unusable == 'disabled':
        other.enabled = False
        db.add(other)
    elif unusable == 'issuer_changed':
        other.issuer = 'https://replacement.example.com'
        db.add(other)
    elif unusable == 'deleted':
        db.delete(other)
    elif unusable == 'unlinked':
        db.delete(other_identity)
    else:
        other_identity.user_id = user_for(db, 'bob').id
        db.add(other_identity)
    db.commit()
    assert unlink(auth_client_a, password=None).status_code == 409
    assert db.get(OIDCIdentity, identity.id) is not None


def test_passwordless_user_can_unlink_when_another_active_identity_remains(auth_client_a, db):
    user = user_for(db)
    user.password_hash = None
    db.add(user)
    _, identity = bind(db)
    _, remaining = bind(db, name='second')
    identity_id, remaining_id = identity.id, remaining.id
    assert unlink(auth_client_a, password=None).status_code == 200
    db.expire_all()
    assert db.get(OIDCIdentity, identity_id) is None
    assert db.get(OIDCIdentity, remaining_id) is not None
    assert auth_client_a.get('/api/auth/me').status_code == 200
    assert unlink(auth_client_a, name='second', password=None).status_code == 409


@pytest.mark.parametrize('unusable', ['disabled', 'issuer_changed', 'deleted'])
def test_users_can_see_and_remove_their_stale_bindings(auth_client_a, auth_client_b, db, unusable):
    provider, identity = bind(db)
    identity_id = identity.id
    if unusable == 'disabled':
        provider.enabled = False
        db.add(provider)
    elif unusable == 'issuer_changed':
        provider.issuer = 'https://replacement.example.com'
        db.add(provider)
    else:
        db.delete(provider)
    db.commit()
    own = auth_client_a.get('/api/v1/auth/sso/account-links').json()['providers']
    other = auth_client_b.get('/api/v1/auth/sso/account-links').json()['providers']
    assert own[0]['has_binding'] and not own[0]['linked'] and own[0]['can_unlink']
    assert 'uid' not in own[0] and 'issuer' not in own[0]
    if unusable != 'issuer_changed':
        assert other == []
    assert unlink(auth_client_a).status_code == 200
    db.expire_all()
    assert db.get(OIDCIdentity, identity_id) is None


def test_unlink_preserves_persistent_session_setting(auth_client_a, db):
    provider, _ = bind(db)
    user = user_for(db)
    auth_client_a.cookies.set(auth.SESSION_COOKIE, auth._make_token(user.username, persist=True, user_id=user.id),
                              domain='testserver.local', path='/')
    response = unlink(auth_client_a)
    assert response.status_code == 200
    token = auth._verify_token(auth_client_a.cookies.get(auth.SESSION_COOKIE))
    assert token['persist'] is True and token['sv'] == 1
    assert f'Max-Age={auth.PERSISTENT_TTL}' in response.headers['set-cookie']


def test_unlink_invalidates_pending_password_confirmation(client, auth_client_a, db, oidc_flow):
    provider, _ = bind(db)
    flow = oidc_flow(provider=provider, userinfo_update={'preferred_username': 'alice'})
    response = client.get(flow.path, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'].startswith('/oidc-link?')
    assert unlink(auth_client_a).status_code == 200
    response = client.post('/api/v1/auth/sso/link-requests/complete',
                           json={'state': flow.state, 'password': 'testpass_a'})
    assert response.status_code == 400
    assert db.exec(select(OIDCIdentity)).all() == []


def test_unlink_invalidates_profile_link_started_on_another_device(client, auth_client_a, db, oidc_flow):
    provider, _ = bind(db)
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'testpass_a'}).status_code == 200
    flow = oidc_flow(provider=provider, link_client=client)
    assert unlink(auth_client_a).status_code == 200
    assert client.get(flow.path, follow_redirects=False).status_code == 401
    assert flow.calls == []
    assert db.exec(select(OIDCIdentity)).all() == []


def test_login_callback_does_not_restore_identity_removed_during_token_exchange(client, auth_client_a, db, oidc_flow, monkeypatch):
    provider, identity = bind(db)
    flow = oidc_flow(provider=provider, claims_update={'sub': identity.uid},
                     userinfo_update={'sub': identity.uid, 'preferred_username': 'alice'})
    transport = v1_oidc._oidc_http
    async def unlink_during_http(http_client, method, url, **kwargs):
        result = await transport(http_client, method, url, **kwargs)
        if url.endswith('/userinfo'):
            assert unlink(auth_client_a).status_code == 200
        return result
    monkeypatch.setattr(v1_oidc, '_oidc_http', unlink_during_http)
    response = client.get(flow.path, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'].startswith('/oidc-link?')
    assert client.get('/api/auth/me').status_code == 401
    db.expire_all()
    assert db.exec(select(OIDCIdentity)).all() == []

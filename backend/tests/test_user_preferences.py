"""Tests for per-user preferences: date format, currency, income-mode toggle."""


def test_get_default_preferences(auth_client_a):
    """New users get the documented defaults for every preference."""
    resp = auth_client_a.get("/api/user-preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert body["date_format"] == "DD/MM/YYYY"
    assert body["currency"] == "CAD"
    assert body["income_mode_enabled"] is False
    assert body['language'] == 'en' and body['has_chosen_language'] is False


def test_update_date_format(auth_client_a):
    resp = auth_client_a.put("/api/user-preferences", json={
        "date_format": "MM/DD/YYYY",
    })
    assert resp.status_code == 200
    assert resp.json()["date_format"] == "MM/DD/YYYY"

    # Verify it persists
    resp = auth_client_a.get("/api/user-preferences")
    assert resp.json()["date_format"] == "MM/DD/YYYY"


def test_invalid_date_format_rejected(auth_client_a):
    resp = auth_client_a.put("/api/user-preferences", json={
        "date_format": "YYYY-MM-DD",
    })
    assert resp.status_code == 422


def test_update_currency(auth_client_a):
    resp = auth_client_a.put("/api/user-preferences", json={"currency": "USD"})
    assert resp.status_code == 200
    assert resp.json()["currency"] == "USD"

    resp = auth_client_a.get("/api/user-preferences")
    assert resp.json()["currency"] == "USD"


def test_invalid_currency_rejected(auth_client_a):
    resp = auth_client_a.put("/api/user-preferences", json={"currency": "XYZ"})
    assert resp.status_code == 422


def test_update_income_mode_enabled(auth_client_a):
    resp = auth_client_a.put("/api/user-preferences", json={"income_mode_enabled": True})
    assert resp.status_code == 200
    assert resp.json()["income_mode_enabled"] is True

    resp = auth_client_a.get("/api/user-preferences")
    assert resp.json()["income_mode_enabled"] is True


def test_partial_update_leaves_other_fields_untouched(auth_client_a):
    """PUT-ing one field must not reset the others to their defaults."""
    auth_client_a.put("/api/user-preferences", json={"date_format": "MM/DD/YYYY"})
    auth_client_a.put("/api/user-preferences", json={"currency": "USD"})
    auth_client_a.put("/api/user-preferences", json={"income_mode_enabled": True})

    body = auth_client_a.get("/api/user-preferences").json()
    assert body["date_format"] == "MM/DD/YYYY"
    assert body["currency"] == "USD"
    assert body["income_mode_enabled"] is True


def test_per_user_isolation(auth_client_a, auth_client_b):
    """Each user has independent preferences."""
    auth_client_a.put("/api/user-preferences", json={"date_format": "MM/DD/YYYY", "currency": "USD"})
    auth_client_b.put("/api/user-preferences", json={"date_format": "YYYY/MM/DD", "currency": "EUR"})

    a = auth_client_a.get("/api/user-preferences").json()
    b = auth_client_b.get("/api/user-preferences").json()
    assert a["date_format"] == "MM/DD/YYYY"
    assert a["currency"] == "USD"
    assert b["date_format"] == "YYYY/MM/DD"
    assert b["currency"] == "EUR"


def test_update_overwrites(auth_client_a):
    """Updating twice uses the latest value."""
    auth_client_a.put("/api/user-preferences", json={"date_format": "MM/DD/YYYY"})
    auth_client_a.put("/api/user-preferences", json={"date_format": "YYYY/DD/MM"})
    assert auth_client_a.get("/api/user-preferences").json()["date_format"] == "YYYY/DD/MM"


def test_unauthenticated_rejected(client):
    resp = client.get("/api/user-preferences")
    assert resp.status_code == 401


def test_new_user_registration_requires_currency_choice(client):
    """
    新注册用户首次登录，UserPreference 中标记 has_chosen_currency=False，
    在前端要求用户主动选择交易币种并保存后，状态持久化为 has_chosen_currency=True。
    """
    # 1. 注册新用户
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "username": "newbie_cur",
            "display_name": "币种新用户",
            "password": "password123",
            "security_question": "Your favorite food?",
            "security_answer": "pizza",
        },
    )
    assert reg_resp.status_code == 201

    # 2. 登录新用户获取会话
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "newbie_cur", "password": "password123"},
    )
    assert login_resp.status_code == 200

    # 3. 首次获取用户首选项，断言 has_chosen_currency 为 False
    pref_resp = client.get("/api/user-preferences")
    assert pref_resp.status_code == 200
    pref_data = pref_resp.json()
    assert pref_data["has_chosen_currency"] is False
    assert pref_data['language'] == 'en' and pref_data['has_chosen_language'] is False
    chosen = client.put('/api/user-preferences', json={'language':'en'})
    assert chosen.status_code == 200
    assert chosen.json()['has_chosen_language'] is True
    assert chosen.json()['has_chosen_currency'] is False

    # 4. 用户在首次弹窗中选定交易币种 (如 CAD 或 USD) 并提交
    put_resp = client.put(
        "/api/user-preferences",
        json={"currency": "CAD", "has_chosen_currency": True},
    )
    assert put_resp.status_code == 200
    put_data = put_resp.json()
    assert put_data["currency"] == "CAD"
    assert put_data["has_chosen_currency"] is True

    # 5. 后续再次查询，断言 has_chosen_currency 保持为 True，不再弹窗
    pref_resp2 = client.get("/api/user-preferences")
    assert pref_resp2.status_code == 200
    assert pref_resp2.json()["has_chosen_currency"] is True
    assert pref_resp2.json()["currency"] == "CAD"
    assert pref_resp2.json()['language'] == 'en' and pref_resp2.json()['has_chosen_language'] is True
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'username':'newbie_cur','password':'password123'}).status_code == 200
    assert client.get('/api/user-preferences').json()['has_chosen_language'] is True


def test_language_preference_is_per_user_and_invalid_choice_rejected(auth_client_a, auth_client_b):
    assert auth_client_a.put('/api/user-preferences', json={'language':'en'}).status_code == 200
    assert auth_client_b.put('/api/user-preferences', json={'language':'zh'}).status_code == 200
    assert auth_client_a.get('/api/user-preferences').json()['language'] == 'en'
    assert auth_client_b.get('/api/user-preferences').json()['language'] == 'zh'
    assert auth_client_b.put('/api/user-preferences', json={'language':'xx'}).status_code == 422
    assert auth_client_b.get('/api/user-preferences').json()['language'] == 'zh'


def test_other_preferences_do_not_dismiss_first_language_question(auth_client_a):
    assert auth_client_a.put('/api/user-preferences', json={'currency':'USD'}).status_code == 200
    assert auth_client_a.get('/api/user-preferences').json()['has_chosen_language'] is False

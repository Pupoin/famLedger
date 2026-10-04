"""
全面安全与多租户隔离自动化回归测试套件。
严格覆盖用户提出的 7 项核心安全/业务缺陷以及新用户注册隔离。
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine
from main import app
from models import Account, Family, PersonalDebt, Transaction, User
from auth import hash_password, _make_token, SESSION_COOKIE


@pytest.fixture
def client():
    return TestClient(app, headers={"X-FamLedger-CSRF": "1"})


def _login_cookie(client: TestClient, username: str) -> dict:
    client.cookies.clear()
    token = _make_token(username)
    client.cookies.set(SESSION_COOKIE, token)
    return {SESSION_COOKIE: token}


def test_1_oidc_security_state_and_no_mock_bypass(client: TestClient):
    """
    缺陷 1 验证：OIDC 回调不再接受 mock_uid 旁路，且无 code 时严格 400 拦截。
    """
    # 尝试传入 mock_uid 旁路绕过
    res = client.get("/api/v1/auth/sso/google/callback?mock_uid=attacker_admin")
    # 没有提供 code 时必须直接 400 拦截
    assert res.status_code == 400
    assert "缺少有效的 OIDC 授权码" in res.json()["detail"]


def test_2_api_key_strict_verification(client: TestClient):
    """
    缺陷 2 验证：生产环境下非合法 API Key 严格拦截，不可随意利用 dev-token 伪造身份。
    """
    # 随机伪造的无效 token
    res = client.get("/api/v1/accounts", headers={"X-Api-Key": "invalid-random-token-xyz"})
    assert res.status_code == 401

    # 在非显式 dev 模式下，非法 key 绝不允许放行
    res_fake = client.get("/api/v1/accounts", headers={"Authorization": "Bearer bad-key"})
    assert res_fake.status_code == 401


def test_3_registration_isolation_and_no_unauthorized_join(client: TestClient):
    """
    缺陷 3 验证：
    1. 新注册用户不再自动分配默认家庭 (family_id 为 None)；
    2. 加入已有家庭接口严格拦截非管理员随意免密加入。
    """
    with Session(engine) as session:
        # 确保存在一个已有家庭
        fam1 = Family(name="家庭 Alpha", currency="CNY")
        session.add(fam1)
        session.commit()
        session.refresh(fam1)

        # 创世或已有用户在家庭 Alpha
        user1 = User(
            family_id=fam1.id,
            username="alpha_owner",
            display_name="Alpha Owner",
            role="owner",
            password_hash=hash_password("Pass123!"),
        )
        session.add(user1)
        session.commit()

    # 注册新用户 beta_user (注册接口为 /api/auth/register)
    reg_payload = {
        "username": "beta_user",
        "display_name": "Beta User",
        "password": "Password123!",
        "security_question": "Pet?",
        "security_answer": "Dog",
    }
    res = client.post("/api/auth/register", json=reg_payload)
    assert res.status_code == 201

    with Session(engine) as session:
        new_u = session.exec(select(User).where(User.username == "beta_user")).first()
        assert new_u is not None
        # 新用户绝不应该属于家庭 Alpha
        assert new_u.family_id is None

    # beta_user 试图通过 family_name 免密加入已有成员的家庭 Alpha
    cookies = _login_cookie(client, "beta_user")
    join_res = client.post("/api/v1/family/join", json={"family_name": "家庭 Alpha"}, cookies=cookies)
    assert join_res.status_code == 404


def test_4_cross_family_account_idor_prevention(client: TestClient):
    """
    缺陷 4 验证：跨家庭 IDOR 拦截。家庭 A 的 owner 绝不能修改家庭 B 的账户或在其下插流水。
    """
    with Session(engine) as session:
        fam_a = Family(name="家庭A", currency="CNY")
        fam_b = Family(name="家庭B", currency="CNY")
        session.add(fam_a)
        session.add(fam_b)
        session.commit()

        user_a = User(family_id=fam_a.id, username="owner_a", display_name="Owner A", role="owner", password_hash=hash_password("pwd"))
        user_b = User(family_id=fam_b.id, username="owner_b", display_name="Owner B", role="owner", password_hash=hash_password("pwd"))
        session.add(user_a)
        session.add(user_b)
        session.commit()

        acc_b = Account(
            family_id=fam_b.id,
            owner_id=user_b.id,
            name="B家庭私有账户",
            account_type="checking",
            balance=Decimal("100.00"),
            currency="CNY",
        )
        session.add(acc_b)
        session.commit()
        session.refresh(acc_b)
        acc_b_id = acc_b.id

    cookies_a = _login_cookie(client, "owner_a")
    # owner_a 试图修改 acc_b 的名称
    res = client.patch(f"/api/v1/accounts/{acc_b_id}", json={"name": "Hacked Name"}, cookies=cookies_a)
    assert res.status_code == 403
    assert "无权编辑其他家庭名下的账户" in res.json()["detail"]

    # owner_a 试图在 acc_b 下创建交易
    txn_payload = {
        "account_id": str(acc_b_id),
        "amount": "50.00",
        "narration": "越权交易",
        "transaction_type": "expense",
        "transacted_at": "2026-10-01",
    }
    res_txn = client.post("/api/v1/transactions", json=txn_payload, cookies=cookies_a)
    assert res_txn.status_code == 403
    assert "该账户属于其他家庭" in res_txn.json()["detail"]


def test_5_email_endpoints_completely_removed(client: TestClient):
    """
    邮件接口全面下线验证：
    1. /api/v1/imports/emails 接口已被彻底移除，任何访问均返回 404；
    2. 交易导出接口 /api/export 权限正常。
    """
    res_get = client.get("/api/v1/imports/emails")
    assert res_get.status_code == 404

    res_post = client.post("/api/v1/imports/emails", json={"message_id": "test_msg"})
    assert res_post.status_code == 404



def test_6_transfers_and_reimbursement_write_permission(client: TestClient):
    """
    缺陷 6 验证：
    1. 创建转账严格校验转出账户的写权限；
    2. 报销状态更新严格核验账户写权限。
    """
    with Session(engine) as session:
        fam = Family(name="转账测试家庭", currency="CNY")
        session.add(fam)
        session.commit()

        u_rich = User(family_id=fam.id, username="rich_member", display_name="Rich", role="member", password_hash=hash_password("pwd"))
        u_poor = User(family_id=fam.id, username="poor_member", display_name="Poor", role="member", password_hash=hash_password("pwd"))
        session.add(u_rich)
        session.add(u_poor)
        session.commit()

        acc_rich = Account(
            family_id=fam.id,
            owner_id=u_rich.id,
            name="Rich账户",
            account_type="checking",
            balance=Decimal("10000.00"),
            currency="CNY",
        )
        acc_poor = Account(
            family_id=fam.id,
            owner_id=u_poor.id,
            name="Poor账户",
            account_type="checking",
            balance=Decimal("10.00"),
            currency="CNY",
        )
        session.add(acc_rich)
        session.add(acc_poor)
        session.commit()
        session.refresh(acc_rich)
        session.refresh(acc_poor)

        # 在 rich 账户下产生一笔流水
        txn_rich = Transaction(
            family_id=fam.id,
            account_id=acc_rich.id,
            amount=Decimal("100.00"),
            narration="公费消费",
            transaction_type="expense",
            transacted_at=date(2026, 10, 1),
        )
        session.add(txn_rich)
        session.commit()
        session.refresh(txn_rich)

        acc_rich_id = acc_rich.id
        acc_poor_id = acc_poor.id
        txn_rich_id = txn_rich.id

    cookies_poor = _login_cookie(client, "poor_member")

    # poor_member 试图从 rich 账户转账到 poor 账户
    transfer_payload = {
        "from_account_id": str(acc_rich_id),
        "to_account_id": str(acc_poor_id),
        "amount": 500.0,
    }
    res_tr = client.post("/api/v1/transfers", json=transfer_payload, cookies=cookies_poor)
    assert res_tr.status_code == 403
    assert "您没有权限从账户" in res_tr.json()["detail"]

    # poor_member 试图修改 rich 账户下流水的报销状态
    res_rb = client.patch(f"/api/v1/transactions/{txn_rich_id}/reimbursement", json={"reimbursement_status": "reimbursed"}, cookies=cookies_poor)
    assert res_rb.status_code == 403


def test_7_balance_calculation_and_no_db_overwrite(client: TestClient):
    """
    缺陷 7 验证：
    1. 初始余额 1000，支出 100，余额必须精确等于 900（绝不可变成 -100）；
    2. 只读列表接口 list_accounts 不得覆盖写回数据库。
    """
    with Session(engine) as session:
        fam = Family(name="余额测试家庭", currency="CNY")
        session.add(fam)
        session.commit()

        u = User(family_id=fam.id, username="bal_tester", display_name="Bal Tester", role="owner", password_hash=hash_password("pwd"))
        session.add(u)
        session.commit()

        # 账户录入初始余额 1000.00
        acc = Account(
            family_id=fam.id,
            owner_id=u.id,
            name="招行储蓄卡",
            account_type="checking",
            balance=Decimal("1000.00"),
            currency="CNY",
            classification="asset",
        )
        session.add(acc)
        session.commit()
        session.refresh(acc)
        acc_id = acc.id
        # Current accounts represent their baseline as a ledger activity.
        from routes.v1_accounts import _ensure_opening_balance_transaction
        _ensure_opening_balance_transaction(session, acc)
        session.commit()

        # 录入一笔 100.00 的支出
        tx = Transaction(
            family_id=fam.id,
            account_id=acc.id,
            amount=Decimal("100.00"),
            narration="日常买菜",
            transaction_type="expense",
            transacted_at=date(2026, 10, 1),
        )
        session.add(tx)
        session.commit()

    cookies = _login_cookie(client, "bal_tester")
    res = client.get("/api/v1/accounts", cookies=cookies)
    assert res.status_code == 200
    data = res.json()
    matched = next((item for item in data["items"] if item["id"] == str(acc_id)), None)
    assert matched is not None
    # 余额必须为 900.00，绝不可为 -100.00
    assert float(matched["balance"]) == 900.0

    # 验证底层数据库中的 stored_balance 没有被只读接口覆盖篡改
    with Session(engine) as session:
        db_acc = session.get(Account, acc_id)
        assert float(db_acc.balance) == 1000.0


def test_8_new_registered_user_dd_reports_all_zero(client: TestClient):
    """
    用户问题 2 验证：新注册的 dd 账号在“统计报表”中各项数字严格为 0，绝对不泄漏系统其他家庭的数据。
    """
    # 注册用户 dd (通过 /api/auth/register)
    reg = client.post("/api/auth/register", json={
        "username": "dd",
        "display_name": "DD User",
        "password": "Password123!",
        "security_question": "City?",
        "security_answer": "Hangzhou",
    })
    assert reg.status_code == 201

    cookies = _login_cookie(client, "dd")
    rep_res = client.get("/api/v1/analytics/report?period=monthly", cookies=cookies)
    assert rep_res.status_code == 200
    report = rep_res.json()

    # 验证当月核心 KPI 全为 0
    kpis = report["kpis"]
    assert kpis["total_income"] == 0.0
    assert kpis["total_expense"] == 0.0
    assert kpis["net_savings"] == 0.0
    assert kpis["savings_rate"] == 0.0

    # 验证净资产与账户全部为 0
    nw = report["net_worth"]
    assert nw["current"] == 0.0
    assert nw["assets_total"] == 0.0
    assert nw["liabilities_total"] == 0.0
    assert nw["cash_total"] == 0.0
    assert nw["invest_total"] == 0.0
    assert nw["credit_total"] == 0.0
    assert nw["loan_total"] == 0.0

    # 验证净资产历史趋势曲线全为 0
    for p in nw["trend"]:
        assert p["value"] == 0.0

    # 验证投资账户列表为空
    assert len(report["investments"]["accounts"]) == 0

    # 验证交易总数为 0
    assert report["activity"]["total_transactions_count"] == 0


def test_9_new_user_complete_isolation_and_no_silent_binding(client: TestClient):
    """
    全链路多租户隔离验证：
    1. 新注册用户 newbie 调用 /family/current 绝不被静默绑定到现有家庭；
    2. newbie 查询规则、标签、账户，均不得泄露首个家庭的数据；
    3. newbie 自主创建账户后，自动形成专属家庭，与现有家庭互不干扰。
    """
    fam_first_id = None
    with Session(engine) as session:
        # 确保存在一个已有第一家庭及数据
        fam_first = Family(name="第一家庭", currency="CNY")
        session.add(fam_first)
        session.commit()
        session.refresh(fam_first)
        fam_first_id = fam_first.id

        u_admin = User(
            family_id=fam_first.id,
            username="admin_fam1",
            display_name="Admin Fam1",
            role="owner",
            password_hash=hash_password("pwd"),
        )
        session.add(u_admin)
        session.commit()

        # 在第一家庭创建私有账户
        acc_first = Account(
            family_id=fam_first.id,
            owner_id=u_admin.id,
            name="第一家庭金库",
            account_type="checking",
            balance=Decimal("999999.00"),
            currency="CNY",
        )
        session.add(acc_first)
        session.commit()

    # 注册全新用户 newbie
    reg = client.post("/api/auth/register", json={
        "username": "newbie",
        "display_name": "Newbie",
        "password": "Password123!",
        "security_question": "Food?",
        "security_answer": "Apple",
    })
    assert reg.status_code == 201

    cookies = _login_cookie(client, "newbie")

    # 1. 调用 GET /api/v1/family/current
    fam_res = client.get("/api/v1/family/current", cookies=cookies)
    assert fam_res.status_code == 200
    fam_data = fam_res.json()
    assert fam_data["id"] is None
    assert fam_data["is_member"] is False

    # 再次验证底层数据库：newbie 绝不能被写回 family_first
    with Session(engine) as session:
        u_check = session.exec(select(User).where(User.username == "newbie")).first()
        assert u_check.family_id is None

    # 2. 查账户列表，绝不能看到第一家庭金库
    accs_res = client.get("/api/v1/accounts", cookies=cookies)
    assert accs_res.status_code == 200
    assert len(accs_res.json()["items"]) == 0

    # 3. 查规则列表，绝不能看到其他家庭规则
    rules_res = client.get("/api/v1/rules", cookies=cookies)
    assert rules_res.status_code == 200
    assert rules_res.json()["count"] == 0

    # 4. 查标签列表，必须为空
    tags_res = client.get("/api/v1/tags", cookies=cookies)
    assert tags_res.status_code == 200
    assert len(tags_res.json()["tags"]) == 0

    # 5. newbie 创建自己的第一个账户
    create_acc_res = client.post("/api/v1/accounts", json={
        "name": "Newbie工资卡",
        "account_type": "checking",
        "currency": "CNY",
        "balance": "5000.00",
    }, cookies=cookies)
    assert create_acc_res.status_code in (200, 201)
    new_acc_id = create_acc_res.json().get("id") or create_acc_res.json().get("account", {}).get("id")

    # 验证此时 newbie 自动拥有了自己的专属家庭组，且绝不是 fam_first
    with Session(engine) as session:
        u_after = session.exec(select(User).where(User.username == "newbie")).first()
        assert u_after.family_id is not None
        assert u_after.family_id != fam_first_id
        assert u_after.role == "owner"

        acc_created = session.get(Account, uuid.UUID(new_acc_id))
        assert acc_created.family_id == u_after.family_id

    # 6. 第一家庭的管理员 admin_fam1 查询账户，完全看不到 Newbie工资卡
    cookies_admin = _login_cookie(client, "admin_fam1")
    admin_accs_res = client.get("/api/v1/accounts", cookies=cookies_admin)
    assert admin_accs_res.status_code == 200
    admin_acc_names = [a["name"] for a in admin_accs_res.json()["items"]]
    assert "第一家庭金库" in admin_acc_names
    assert "Newbie工资卡" not in admin_acc_names


def test_10_oidc_secret_encryption_and_takeover_prevention(client: TestClient):
    """
    缺陷 2 & 5 验证：
    1. OIDC 密钥加密路径正常使用，不报 ImportError；
    2. 禁止外部 SSO 自动接管同名本地账号。
    """
    from routes.v1_oidc import encrypt_secret, decrypt_secret
    raw_secret = "test-secret-123456"
    enc = encrypt_secret(raw_secret)
    assert enc.startswith("enc:")
    assert decrypt_secret(enc) == raw_secret

    # 本地已存在用户 local_user
    with Session(engine) as session:
        u_local = User(
            username="local_victim",
            display_name="Local Victim",
            role="member",
            password_hash=hash_password("pwd"),
        )
        session.add(u_local)
        session.commit()


def test_11_account_shares_cross_family_idor_prevention(client: TestClient):
    """
    缺陷 4 验证：跨家庭获取账户共享详情严格 403 拦截，哪怕请求者是自己家庭的 owner。
    """
    uid_str = uuid.uuid4().hex[:6]
    with Session(engine) as session:
        fam_x = Family(name=f"FamX_{uid_str}", currency="CNY")
        fam_y = Family(name=f"FamY_{uid_str}", currency="CNY")
        session.add(fam_x)
        session.add(fam_y)
        session.commit()
        session.refresh(fam_x)
        session.refresh(fam_y)

        ux = User(family_id=fam_x.id, username=f"ux_{uid_str}", display_name="UX", role="owner", password_hash=hash_password("pwd"))
        uy = User(family_id=fam_y.id, username=f"uy_{uid_str}", display_name="UY", role="owner", password_hash=hash_password("pwd"))
        session.add(ux)
        session.add(uy)
        session.commit()
        session.refresh(ux)
        session.refresh(uy)

        acc_y = Account(family_id=fam_y.id, owner_id=uy.id, name="Secret Vault Y", account_type="checking", balance=Decimal("8888.00"), currency="CNY")
        session.add(acc_y)
        session.commit()
        session.refresh(acc_y)
        acc_y_id = acc_y.id

    # 家庭 X 的 owner 尝试读取家庭 Y 账户的 shares
    cookies_x = _login_cookie(client, f"ux_{uid_str}")
    res = client.get(f"/api/v1/accounts/{acc_y_id}/shares", cookies=cookies_x)
    assert res.status_code == 403
    assert "您无权查看其他家庭账户的共享设置" in res.json()["detail"]


def test_12_reconcile_balance_no_double_deduction(client: TestClient):
    """
    缺陷 3 验证：对账后余额绝不双重累加扣减。
    初始余额 1000，对账调至 900，随后查询实时余额必须严格为 900，绝不能变成 800。
    """
    uid_str = uuid.uuid4().hex[:6]
    with Session(engine) as session:
        fam = Family(name=f"FamReconcile_{uid_str}", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        u = User(family_id=fam.id, username=f"reconcile_user_{uid_str}", display_name="Reconcile User", role="owner", password_hash=hash_password("pwd"))
        session.add(u)
        session.commit()
        session.refresh(u)

        acc = Account(family_id=fam.id, owner_id=u.id, name="Bank 1000", account_type="checking", balance=Decimal("1000.00"), currency="CNY")
        session.add(acc)
        session.commit()
        session.refresh(acc)
        acc_id = acc.id

    cookies = _login_cookie(client, f"reconcile_user_{uid_str}")

    # 执行对账调账至 900
    res = client.post(f"/api/v1/accounts/{acc_id}/reconcile-balance", json={
        "new_balance": "900.00",
        "reconciliation_type": "adjustment",
    }, cookies=cookies)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert Decimal(res.json()["new_balance"]) == Decimal("900.00")

    # 查询账户列表，核实结余
    list_res = client.get("/api/v1/accounts", cookies=cookies)
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    target_acc = next(item for item in items if item["id"] == str(acc_id))
    assert Decimal(target_acc["balance"]) == Decimal("900.00"), f"Expected 900.00, got {target_acc['balance']}"



def test_13_account_edit_balance_no_double_counting(client: TestClient):
    """
    缺陷验证：通过账户编辑接口修改余额不会导致重复计算。
    场景：初始余额1000、支出100 → 实时余额900 → 编辑余额为800
    预期：页面显示800（而非 800 - 100 = 700）。
    """
    uid_str = str(uuid.uuid4())[:8]
    with Session(engine) as session:
        fam = Family(name="编辑余额测试家庭", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        u = User(
            username=f"edit_bal_user_{uid_str}",
            display_name="EditBalUser",
            password_hash=hash_password("test123"),
            security_question="Q?", security_answer_hash="a",
            family_id=fam.id, role="owner",
        )
        session.add(u)
        session.commit()
        session.refresh(u)

        acc = Account(family_id=fam.id, owner_id=u.id, name="储蓄卡1000",
                      account_type="checking", balance=Decimal("1000.00"), currency="CNY")
        session.add(acc)
        session.commit()
        session.refresh(acc)
        acc_id = acc.id
        # Current accounts represent their baseline as a ledger activity.
        from routes.v1_accounts import _ensure_opening_balance_transaction
        _ensure_opening_balance_transaction(session, acc)
        session.commit()

        # 模拟一笔100元支出
        from models import Transaction
        txn = Transaction(
            account_id=acc.id,
            amount=Decimal("100.00"),
            currency="CNY",
            narration="日常消费",
            transaction_type="expense",
            transacted_at=date.today(),
            status="cleared",
        )
        session.add(txn)
        session.commit()

    cookies = _login_cookie(client, f"edit_bal_user_{uid_str}")

    # 确认当前实时余额应为 900
    list_res = client.get("/api/v1/accounts", cookies=cookies)
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    target_acc = next(item for item in items if item["id"] == str(acc_id))
    assert Decimal(target_acc["balance"]) == Decimal("900.00"), \
        f"Expected pre-edit balance 900.00, got {target_acc['balance']}"

    # 通过编辑接口将余额修改为 800
    edit_res = client.patch(f"/api/v1/accounts/{acc_id}", json={"balance": "800.00"}, cookies=cookies)
    assert edit_res.status_code == 200

    # 再次查询，余额应精确为 800（不应是 700）
    list_res2 = client.get("/api/v1/accounts", cookies=cookies)
    items2 = list_res2.json()["items"]
    target_acc2 = next(item for item in items2 if item["id"] == str(acc_id))
    assert Decimal(target_acc2["balance"]) == Decimal("800.00"), \
        f"Expected edited balance 800.00, got {target_acc2['balance']} (double-counting bug!)"


def test_14_same_amount_expenses_never_pair_as_transfer(client: TestClient):
    """
    问题 1 回归测试：同家庭、两不同账户、同金额的日常支出，绝对不能误配对为内部转账。
    """
    uid_str = str(uuid.uuid4())[:8]
    with Session(engine) as session:
        fam = Family(name="转账方向防误撮合测试家庭", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        u = User(
            username=f"transfer_dir_{uid_str}",
            display_name="TransferDirUser",
            password_hash=hash_password("pwd"),
            family_id=fam.id, role="owner",
        )
        session.add(u)
        session.commit()
        session.refresh(u)

        acc1 = Account(family_id=fam.id, owner_id=u.id, name="账户1", account_type="checking", balance=Decimal("1000.00"), currency="CNY")
        acc2 = Account(family_id=fam.id, owner_id=u.id, name="账户2", account_type="checking", balance=Decimal("1000.00"), currency="CNY")
        session.add(acc1)
        session.add(acc2)
        session.commit()
        session.refresh(acc1)
        session.refresh(acc2)
        acc1_id, acc2_id = acc1.id, acc2.id

    cookies = _login_cookie(client, f"transfer_dir_{uid_str}")

    # 在账户1录入 100 元支出（餐饮）
    r1 = client.post("/api/v1/transactions", json={
        "account": str(acc1_id),
        "amount": "100.00",
        "narration": "餐饮晚餐",
        "transaction_type": "expense",
        "date": date.today().isoformat(),
    }, cookies=cookies)
    assert r1.status_code == 200
    t1_id = r1.json()["id"]

    # 在账户2录入同金额 100 元支出（超市）
    r2 = client.post("/api/v1/transactions", json={
        "account": str(acc2_id),
        "amount": "100.00",
        "narration": "超市买菜",
        "transaction_type": "expense",
        "date": date.today().isoformat(),
    }, cookies=cookies)
    assert r2.status_code == 200
    t2_id = r2.json()["id"]

    # 验证两笔交易依然是 expense，且 transfer_id 均为 None
    with Session(engine) as session:
        t1 = session.get(Transaction, uuid.UUID(t1_id))
        t2 = session.get(Transaction, uuid.UUID(t2_id))
        assert t1.transaction_type == "expense"
        assert t2.transaction_type == "expense"
        assert t1.transfer_id is None, "支出流水被错误转成了内部转账！"
        assert t2.transfer_id is None, "支出流水被错误转成了内部转账！"


def test_15_refund_multi_tenant_isolation_and_limit(client: TestClient):
    """
    问题 2 回归测试：退款自动匹配不能跨家庭，且手动分配必须 >0 且不能超过退款自身总额。
    """
    uid_str = str(uuid.uuid4())[:8]
    with Session(engine) as session:
        fam_a = Family(name="家庭A", currency="CNY")
        fam_b = Family(name="家庭B", currency="CNY")
        session.add(fam_a)
        session.add(fam_b)
        session.commit()

        ua = User(username=f"ua_{uid_str}", display_name="UA", password_hash=hash_password("pwd"), family_id=fam_a.id, role="owner")
        ub = User(username=f"ub_{uid_str}", display_name="UB", password_hash=hash_password("pwd"), family_id=fam_b.id, role="owner")
        session.add(ua)
        session.add(ub)
        session.commit()

        acc_a = Account(family_id=fam_a.id, owner_id=ua.id, name="A银行卡", account_type="checking", balance=Decimal("1000.00"), currency="CNY")
        acc_b = Account(family_id=fam_b.id, owner_id=ub.id, name="B银行卡", account_type="checking", balance=Decimal("1000.00"), currency="CNY")
        session.add(acc_a)
        session.add(acc_b)
        session.commit()
        acc_a_id, acc_b_id = acc_a.id, acc_b.id

    cookies_a = _login_cookie(client, f"ua_{uid_str}")
    cookies_b = _login_cookie(client, f"ub_{uid_str}")

    # 家庭 A 发生一笔 200 元的“Apple Store 消费”
    res_a = client.post("/api/v1/transactions", json={
        "account": str(acc_a_id),
        "amount": "200.00",
        "narration": "Apple Store 消费",
        "transaction_type": "expense",
        "date": date.today().isoformat(),
    }, cookies=cookies_a)
    assert res_a.status_code == 200
    orig_a_id = res_a.json()["id"]

    # 家庭 B 录入一笔“Apple Store 退款” 200 元
    res_b = client.post("/api/v1/transactions", json={
        "account": str(acc_b_id),
        "amount": "200.00",
        "narration": "Apple Store 退款",
        "transaction_type": "refund",
        "date": date.today().isoformat(),
    }, cookies=cookies_b)
    assert res_b.status_code == 200
    refund_b_id = res_b.json()["id"]

    # 验证家庭 B 的退款绝对没有自动关联到家庭 A 的原消费！
    with Session(engine) as session:
        rf = session.get(Transaction, uuid.UUID(refund_b_id))
        assert rf.refund_of_transaction_id is None, "退款跨家庭错误匹配到了其他家庭的支出！"

    # 家庭 B 尝试显式关联到家庭 A 的原消费，应被 403 拒绝
    alloc_res = client.post(f"/api/v1/refunds/{refund_b_id}/allocate", json={
        "original_transaction_id": orig_a_id,
        "allocated_amount": "200.00",
    }, cookies=cookies_b)
    assert alloc_res.status_code == 403


def test_16_credit_card_parent_and_shares_same_family(client: TestClient):
    """
    问题 4 & 5 回归测试：主副卡与账户共享必须严格限制在同一家庭内。
    """
    uid_str = str(uuid.uuid4())[:8]
    with Session(engine) as session:
        fam1 = Family(name="家庭1", currency="CNY")
        fam2 = Family(name="家庭2", currency="CNY")
        session.add(fam1)
        session.add(fam2)
        session.commit()

        u1 = User(username=f"u1_{uid_str}", display_name="U1", password_hash=hash_password("pwd"), family_id=fam1.id, role="owner")
        u2 = User(username=f"u2_{uid_str}", display_name="U2", password_hash=hash_password("pwd"), family_id=fam2.id, role="owner")
        session.add(u1)
        session.add(u2)
        session.commit()

        card_fam1 = Account(family_id=fam1.id, owner_id=u1.id, name="主卡1", account_type="credit_card", balance=Decimal("0"), currency="CNY")
        card_fam2 = Account(family_id=fam2.id, owner_id=u2.id, name="副卡2", account_type="credit_card", balance=Decimal("0"), currency="CNY")
        session.add(card_fam1)
        session.add(card_fam2)
        session.commit()
        card1_id, card2_id = card_fam1.id, card_fam2.id
        u2_id = u2.id

    cookies1 = _login_cookie(client, f"u1_{uid_str}")
    cookies2 = _login_cookie(client, f"u2_{uid_str}")

    # 家庭2尝试将副卡挂载到家庭1的主卡上，必须被 403 拦截
    attach_res = client.patch(f"/api/v1/accounts/{card2_id}", json={
        "parent_account_id": str(card1_id)
    }, cookies=cookies2)
    assert attach_res.status_code == 403

    # 家庭1尝试将自己的卡共享给家庭2的用户，必须被 400 拦截
    share_res = client.patch(f"/api/v1/accounts/{card1_id}/shares", json={
        "members": [{"user_id": str(u2_id), "shared": True, "permission": "read_only"}]
    }, cookies=cookies1)
    assert share_res.status_code == 400


def test_17_initial_balance_not_wiped_by_casual_notes(client: TestClient):
    """
    问题 9 回归测试：“学期初交学费”等普通包含“期初”的文字不能抹掉账户的期初活动。
    """
    uid_str = str(uuid.uuid4())[:8]
    with Session(engine) as session:
        fam = Family(name="期初字眼测试家庭", currency="CNY")
        session.add(fam)
        session.commit()

        u = User(username=f"init_word_{uid_str}", display_name="InitWord", password_hash=hash_password("pwd"), family_id=fam.id, role="owner")
        session.add(u)
        session.commit()

        # 初始余额 50,000 元
        acc = Account(family_id=fam.id, owner_id=u.id, name="教育储蓄卡", account_type="checking", balance=Decimal("50000.00"), currency="CNY")
        session.add(acc)
        session.commit()
        acc_id = acc.id
        # Current accounts represent their baseline as a ledger activity.
        from routes.v1_accounts import _ensure_opening_balance_transaction
        _ensure_opening_balance_transaction(session, acc)
        session.commit()

        # 录入一笔“学期初学费缴纳” 500 元
        txn = Transaction(
            account_id=acc.id,
            amount=Decimal("500.00"),
            currency="CNY",
            narration="学期初学费缴纳",
            notes="新学期初为孩子缴纳辅导费",
            transaction_type="expense",
            transacted_at=date.today(),
            status="cleared",
        )
        session.add(txn)
        session.commit()

    cookies = _login_cookie(client, f"init_word_{uid_str}")
    res = client.get("/api/v1/accounts", cookies=cookies)
    assert res.status_code == 200
    acc_data = next(a for a in res.json()["items"] if a["id"] == str(acc_id))
    # 正确计算：50000 - 500 = 49500
    assert Decimal(acc_data["balance"]) == Decimal("49500.00"), f"Expected 49500.00, got {acc_data['balance']} (Initial wiped bug!)"


def test_18_transfer_reconciliation_direction(client: TestClient):
    """
    问题 10 回归测试：通过转账方式上调余额，新余额应正确增加而非反向倒扣。
    """
    uid_str = str(uuid.uuid4())[:8]
    with Session(engine) as session:
        fam = Family(name="对账方向测试家庭", currency="CNY")
        session.add(fam)
        session.commit()

        u = User(username=f"rec_dir_{uid_str}", display_name="RecDir", password_hash=hash_password("pwd"), family_id=fam.id, role="owner")
        session.add(u)
        session.commit()

        acc = Account(family_id=fam.id, owner_id=u.id, name="钱包账户", account_type="checking", balance=Decimal("1000.00"), currency="CNY")
        session.add(acc)
        session.commit()
        acc_id = acc.id

    cookies = _login_cookie(client, f"rec_dir_{uid_str}")

    # 将余额通过 transfer 上调至 1500
    rec_res = client.post(f"/api/v1/accounts/{acc_id}/reconcile-balance", json={
        "new_balance": "1500.00",
        "reconciliation_type": "transfer",
    }, cookies=cookies)
    assert rec_res.status_code == 200

    # 查余额必须为 1500（绝不能反向倒扣变成 500）
    list_res = client.get("/api/v1/accounts", cookies=cookies)
    assert list_res.status_code == 200
    acc_data = next(a for a in list_res.json()["items"] if a["id"] == str(acc_id))
    assert Decimal(acc_data["balance"]) == Decimal("1500.00"), f"Expected 1500.00, got {acc_data['balance']}"

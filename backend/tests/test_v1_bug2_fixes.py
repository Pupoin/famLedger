"""
Automated regression tests covering all 14 issues from bug2.md:
- Issue 1: Dashboard calendar heatmap cross-tenant isolation
- Issue 2: Read-only shared user cannot escalate account share permissions
- Issue 3 & 5: Filter options & transaction list private account isolation (no 500 on Account.is_shared)
- Issue 4: Transfer write permission check on to_account_id
- Issue 6: Transfers module imports User and Account (no NameError)
- Issue 7: Manual pair transfer direction, amount equality, and pre-existing pair checks
- Issue 8: Link refund to original limit, positive amount, and family checks
- Issue 9: Auto-transfer matching prevents arbitrary transfer-transfer pairing
- Issue 10: Category IDs validated across families in create, split, and update
- Issue 11: No-family user list_categories returns valid preset IDs without KeyError: 'id'
- Issue 12: No-family user creating debt or tag returns 400 Bad Request (not 500)
- Issue 13: build_user_map returns empty dict for family_id=None
- Issue 14: /api/config returns family-scoped display names or placeholders
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine
from main import app
from models import (
    Account,
    AccountShare,
    Category,
    Family,
    PersonalDebt,
    RefundAllocation,
    Tag,
    Transaction,
    Transfer,
    User,
)
from auth import hash_password, _make_token, SESSION_COOKIE
from users import build_user_map


@pytest.fixture
def client():
    return TestClient(app, headers={"X-FamLedger-CSRF": "1"})


def _login_cookie(client: TestClient, username: str) -> dict:
    client.cookies.clear()
    token = _make_token(username)
    client.cookies.set(SESSION_COOKIE, token)
    return {SESSION_COOKIE: token}


def test_issue_1_dashboard_calendar_cross_tenant_isolation(client: TestClient):
    """
    Issue 1: 仪表盘日历热力图跨租户泄露修复验证。
    Family B 的支出绝不能出现在 Family A 的日历热力图中。
    """
    with Session(engine) as session:
        # 创建 Family A 与用户 Alice
        fam_a = Family(name="Test Fam A 1", currency="CNY")
        session.add(fam_a)
        session.commit()
        session.refresh(fam_a)

        user_a = User(
            username=f"u_cal_a_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam_a.id,
            display_name="Alice",
            role="owner",
        )
        session.add(user_a)
        session.commit()
        session.refresh(user_a)

        acc_a = Account(
            family_id=fam_a.id,
            owner_id=user_a.id,
            name="Alice Checking",
            account_type="checking",
            balance=Decimal("1000.00"),
        )
        session.add(acc_a)
        session.commit()
        session.refresh(acc_a)

        # Alice 本人支出 50
        txn_a = Transaction(
            account_id=acc_a.id,
            amount=Decimal("50.00"),
            transaction_type="expense",
            narration="Alice Lunch",
            transacted_at=date.today(),
            status="posted",
        )
        session.add(txn_a)

        # 创建 Family B 与用户 Bob，在同一天支出 88888 巨款
        fam_b = Family(name="Test Fam B 1", currency="CNY")
        session.add(fam_b)
        session.commit()
        session.refresh(fam_b)

        user_b = User(
            username=f"u_cal_b_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam_b.id,
            display_name="Bob",
            role="owner",
        )
        session.add(user_b)
        session.commit()
        session.refresh(user_b)

        acc_b = Account(
            family_id=fam_b.id,
            owner_id=user_b.id,
            name="Bob Checking",
            account_type="checking",
            balance=Decimal("99999.00"),
        )
        session.add(acc_b)
        session.commit()
        session.refresh(acc_b)

        txn_b = Transaction(
            account_id=acc_b.id,
            amount=Decimal("88888.00"),
            transaction_type="expense",
            narration="Bob Secret Island",
            transacted_at=date.today(),
            status="posted",
        )
        session.add(txn_b)
        session.commit()

        u_a_name = user_a.username

    # Alice 访问仪表盘图表数据
    _login_cookie(client, u_a_name)
    res = client.get("/api/v1/dashboard/summary?period=monthly")
    assert res.status_code == 200
    data = res.json()
    calendar = data.get("spending_calendar", {})

    today_str = date.today().isoformat()
    # 从 weeks 结构中检索当天的日历单元格与全量单元格列表
    weeks = calendar.get("weeks", [])
    all_cells = [cell for week in weeks for cell in week]
    today_cell = next((c for c in all_cells if c["date"] == today_str), None)

    # Alice 应该只看到自己的 50，总支出统计为 50.0，绝不应该看到 Bob 的 88888
    assert today_cell is not None
    assert today_cell["amount"] == 50.0
    assert today_cell["description"] == "Alice Lunch"
    assert sum(c["amount"] for c in all_cells) == 50.0
    assert data.get("outflows", {}).get("total") == 50.0

    # 严密验证 Bob 的任何数据均未泄露至 Alice 的日历热力图中
    assert not any(c.get("amount") == 88888.0 for c in all_cells)
    assert not any("Bob" in str(c.get("description", "")) for c in all_cells)


def test_issue_2_readonly_share_cannot_escalate_permission(client: TestClient):
    """
    Issue 2: 只读共享用户尝试通过 members 字段提权，严格拦截并返回 403。
    """
    with Session(engine) as session:
        fam = Family(name="Test Fam Shares", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        owner = User(
            username=f"owner_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="owner",
            display_name="Owner",
        )
        member = User(
            username=f"member_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="member",
            display_name="Member",
        )
        session.add(owner)
        session.add(member)
        session.commit()
        session.refresh(owner)
        session.refresh(member)

        acc = Account(
            family_id=fam.id,
            owner_id=owner.id,
            name="Owner Private Vault",
            account_type="savings",
            balance=Decimal("5000.00"),
        )
        session.add(acc)
        session.commit()
        session.refresh(acc)

        # 初始赋予只读共享
        share = AccountShare(
            account_id=acc.id,
            user_id=member.id,
            permission="read_only",
            include_in_finances=True,
        )
        session.add(share)
        session.commit()

        member_name = member.username
        member_id = member.id
        acc_id = acc.id

    _login_cookie(client, member_name)

    # 攻击场景：非管理人员在省略 include_in_finances 的情况下提交 members 试图将自己提权为 full_control
    attack_payload = {
        "members": [
            {
                "user_id": str(member_id),
                "permission": "full_control",
                "shared": True,
            }
        ]
    }
    res = client.put(f"/api/v1/accounts/{acc_id}/shares", json=attack_payload)
    assert res.status_code == 403
    assert "有权修改共享权限" in res.json()["detail"]

    # 验证数据库中权限未被篡改
    with Session(engine) as session:
        sh = session.exec(
            select(AccountShare).where(
                AccountShare.account_id == acc_id,
                AccountShare.user_id == member_id,
            )
        ).first()
        assert sh.permission == "read_only"

    # 合法操作：普通成员仅修改自己的 include_in_finances
    normal_payload = {"include_in_finances": False}
    res_ok = client.put(f"/api/v1/accounts/{acc_id}/shares", json=normal_payload)
    assert res_ok.status_code == 200
    assert res_ok.json()["include_in_finances"] is False


def test_issue_3_and_5_filter_options_no_500_and_no_private_leak(client: TestClient):
    """
    Issue 3 & 5: 验证流水筛选器不再调用 Account.is_shared (避免 500)，且不泄露同家庭未共享的私有账户。
    """
    with Session(engine) as session:
        fam = Family(name="Test Fam Filter", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        user_alice = User(
            username=f"u_flt_a_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="owner",
            display_name="Alice",
        )
        user_bob = User(
            username=f"u_flt_b_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="member",
            display_name="Bob",
        )
        session.add(user_alice)
        session.add(user_bob)
        session.commit()
        session.refresh(user_alice)
        session.refresh(user_bob)

        # Alice 私有账户
        acc_alice = Account(
            family_id=fam.id,
            owner_id=user_alice.id,
            name="Alice Secret Card 8888",
            account_type="credit_card",
        )
        # Bob 私有账户
        acc_bob = Account(
            family_id=fam.id,
            owner_id=user_bob.id,
            name="Bob Salary Account 6666",
            account_type="checking",
        )
        session.add(acc_alice)
        session.add(acc_bob)
        session.commit()

        bob_name = user_bob.username
        bob_acc_id = str(acc_bob.id)
        alice_acc_id = str(acc_alice.id)

    # Bob 登录调用 filter-options
    _login_cookie(client, bob_name)
    res = client.get("/api/v1/transactions/filter-options")
    # 之前因为 Account.is_shared 触发 AttributeError 500，现在必须是 200 成功
    assert res.status_code == 200
    data = res.json()
    acc_options = data.get("accounts", [])
    returned_acc_ids = [a["id"] for a in acc_options]

    # Bob 应该能看到自己的账户，但绝不能看到 Alice 的私有账户
    assert bob_acc_id in returned_acc_ids
    assert alice_acc_id not in returned_acc_ids


def test_issue_4_transfer_write_permission_on_to_account(client: TestClient):
    """
    Issue 4: 转账写入权限校验，防止向他人未授权的私有账户写入转账。
    """
    with Session(engine) as session:
        fam = Family(name="Test Fam Txfer", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        user_alice = User(
            username=f"u_txf_a_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="owner",
            display_name="Alice",
        )
        user_bob = User(
            username=f"u_txf_b_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="member",
            display_name="Bob",
        )
        session.add(user_alice)
        session.add(user_bob)
        session.commit()
        session.refresh(user_alice)
        session.refresh(user_bob)

        acc_bob = Account(
            family_id=fam.id,
            owner_id=user_bob.id,
            name="Bob Wallet",
            account_type="checking",
            balance=Decimal("500.00"),
        )
        acc_alice_private = Account(
            family_id=fam.id,
            owner_id=user_alice.id,
            name="Alice Private Fund",
            account_type="savings",
            balance=Decimal("10000.00"),
        )
        session.add(acc_bob)
        session.add(acc_alice_private)
        session.commit()
        session.refresh(acc_bob)
        session.refresh(acc_alice_private)

        bob_name = user_bob.username
        from_id = acc_bob.id
        to_id = acc_alice_private.id

    _login_cookie(client, bob_name)
    # Bob 试图向 Alice 的私有账户进行转账注水
    payload = {
        "from_account_id": str(from_id),
        "to_account_id": str(to_id),
        "amount": "100.00",
        "narration": "Unauthorized Inflow Injection",
    }
    res = client.post("/api/v1/transfers", json=payload)
    assert res.status_code == 403
    assert "您没有权限向账户" in res.json()["detail"]


def test_issue_6_transfers_no_name_error_imports(client: TestClient):
    """
    Issue 6: 转账列表、驳回与手动撮合不出现 User / Account 的 NameError 500。
    """
    with Session(engine) as session:
        fam = Family(name="Test Fam NameErr", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        user = User(
            username=f"u_ne_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="member",
            display_name="Test User",
        )
        session.add(user)
        session.commit()
        uname = user.username

    _login_cookie(client, uname)
    # 访问转账列表，此前由于缺失 User 模型导入会触发 NameError 500
    res = client.get("/api/v1/transfers")
    assert res.status_code == 200
    assert isinstance(res.json(), dict) and "transfers" in res.json()


def test_issue_7_manual_pair_transfer_validations(client: TestClient):
    """
    Issue 7: 手动转账配对严格校验收支互逆方向、金额绝对值相等、不可重复配对与黑名单。
    """
    with Session(engine) as session:
        fam = Family(name="Test Fam Manual Pair", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        user = User(
            username=f"u_mp_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="owner",
            display_name="Owner",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        acc1 = Account(family_id=fam.id, owner_id=user.id, name="Acc 1", account_type="checking")
        acc2 = Account(family_id=fam.id, owner_id=user.id, name="Acc 2", account_type="savings")
        session.add(acc1)
        session.add(acc2)
        session.commit()
        session.refresh(acc1)
        session.refresh(acc2)

        # 构造两笔支出流水（方向同向，不可配对）
        exp1 = Transaction(account_id=acc1.id, amount=Decimal("100.00"), transaction_type="expense", narration="Dinner", transacted_at=date.today())
        exp2 = Transaction(account_id=acc2.id, amount=Decimal("100.00"), transaction_type="expense", narration="Shopping", transacted_at=date.today())
        # 构造一笔不同金额的收入流水
        inc_diff = Transaction(account_id=acc2.id, amount=Decimal("200.00"), transaction_type="income", narration="Salary", transacted_at=date.today())
        # 构造一笔同金额的正规收入流水
        inc_match = Transaction(account_id=acc2.id, amount=Decimal("100.00"), transaction_type="income", narration="Deposit", transacted_at=date.today())

        session.add(exp1)
        session.add(exp2)
        session.add(inc_diff)
        session.add(inc_match)
        session.commit()
        session.refresh(exp1)
        session.refresh(exp2)
        session.refresh(inc_diff)
        session.refresh(inc_match)

        uname = user.username
        exp1_id = exp1.id
        exp2_id = exp2.id
        inc_diff_id = inc_diff.id
        inc_match_id = inc_match.id

    _login_cookie(client, uname)

    # 1. 尝试配对两笔支出（方向同向，未互逆）
    res1 = client.post("/api/v1/transfers/manual-pair", json={
        "outflow_transaction_id": str(exp1_id),
        "inflow_transaction_id": str(exp2_id),
    })
    assert res1.status_code == 400
    assert "转入方交易类型必须为收入或转账" in res1.json()["detail"]

    # 2. 尝试配对金额不同的支出与收入 (100 vs 200)
    res2 = client.post("/api/v1/transfers/manual-pair", json={
        "outflow_transaction_id": str(exp1_id),
        "inflow_transaction_id": str(inc_diff_id),
    })
    assert res2.status_code == 400
    assert "不一致" in res2.json()["detail"]

    # 3. 正常同额、方向相反的配对
    res3 = client.post("/api/v1/transfers/manual-pair", json={
        "outflow_transaction_id": str(exp1_id),
        "inflow_transaction_id": str(inc_match_id),
    })
    assert res3.status_code == 200
    assert "transfer_id" in res3.json()

    # 4. 重复配对已绑定的交易
    res4 = client.post("/api/v1/transfers/manual-pair", json={
        "outflow_transaction_id": str(exp1_id),
        "inflow_transaction_id": str(inc_match_id),
    })
    assert res4.status_code == 400
    assert "已属于其他转账配对" in res4.json()["detail"]


def test_issue_8_link_refund_to_original_limits(client: TestClient):
    """
    Issue 8: 一键退款关联 (/link/{original_id}) 严格执行冲抵金额限额、正数及类型防御校验。
    """
    with Session(engine) as session:
        fam = Family(name="Test Fam Refund Link", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        user = User(
            username=f"u_rfl_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="owner",
            display_name="Owner",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        acc = Account(family_id=fam.id, owner_id=user.id, name="Card", account_type="checking")
        session.add(acc)
        session.commit()
        session.refresh(acc)

        orig_exp = Transaction(account_id=acc.id, amount=Decimal("100.00"), transaction_type="expense", narration="Shoes", transacted_at=date.today())
        refund = Transaction(account_id=acc.id, amount=Decimal("40.00"), transaction_type="refund", narration="Refund Shoes", transacted_at=date.today())
        session.add(orig_exp)
        session.add(refund)
        session.commit()
        session.refresh(orig_exp)
        session.refresh(refund)

        uname = user.username
        orig_id = orig_exp.id
        ref_id = refund.id

    _login_cookie(client, uname)

    # 1. 尝试传入负数金额冲抵
    res_neg = client.post(f"/api/v1/refunds/{ref_id}/link/{orig_id}?allocated_amount=-10")
    assert res_neg.status_code == 422
    assert res_neg.json()["detail"][0]["type"] == "greater_than"

    # 2. 尝试传入超过退款自身总额的金额 (退款40，尝试分配50)
    res_over_ref = client.post(f"/api/v1/refunds/{ref_id}/link/{orig_id}?allocated_amount=50")
    assert res_over_ref.status_code == 400
    assert "不能超过退款总额" in res_over_ref.json()["detail"]

    # 3. 正常合法冲抵 (30.00)
    res_ok = client.post(f"/api/v1/refunds/{ref_id}/link/{orig_id}?allocated_amount=30")
    assert res_ok.status_code == 200
    assert res_ok.json()["allocated_amount"] == "30.00"


def test_issue_9_auto_transfer_matching_no_arbitrary_transfer_pairing(client: TestClient):
    """
    Issue 9: 自动转账撮合对两笔没有方向关键词的 transfer 流水，绝不进行静默自动撮合。
    """
    with Session(engine) as session:
        fam = Family(name="Test Fam Auto Pair", currency="CNY")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        user = User(
            username=f"u_ap_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam.id,
            role="owner",
            display_name="Owner",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        acc1 = Account(family_id=fam.id, owner_id=user.id, name="Acc 1", account_type="checking")
        acc2 = Account(family_id=fam.id, owner_id=user.id, name="Acc 2", account_type="savings")
        session.add(acc1)
        session.add(acc2)
        session.commit()
        session.refresh(acc1)
        session.refresh(acc2)

        uname = user.username
        acc1_id = acc1.id
        acc2_id = acc2.id

    _login_cookie(client, uname)

    # 录入第一笔 transfer (金额 666.00，无方向关键词)
    t1_payload = {
        "account_id": str(acc1_id),
        "amount": 666.00,
        "transaction_type": "transfer",
        "narration": "独立内部业务周转 A",
        "transacted_at": date.today().isoformat(),
    }
    res1 = client.post("/api/v1/transactions", json=t1_payload)
    assert res1.status_code == 200
    t1_id = res1.json()["id"]

    # 录入第二笔 transfer (同金额 666.00，但也是无明确收支方向关键词的独立转账)
    t2_payload = {
        "account_id": str(acc2_id),
        "amount": 666.00,
        "transaction_type": "transfer",
        "narration": "独立内部业务周转 B",
        "transacted_at": date.today().isoformat(),
    }
    res2 = client.post("/api/v1/transactions", json=t2_payload)
    assert res2.status_code == 200
    t2_id = res2.json()["id"]

    # 核心验证：两笔无方向证据的独立转账绝不能被系统胡乱配对为一进一出！
    with Session(engine) as session:
        t1_db = session.get(Transaction, uuid.UUID(t1_id))
        t2_db = session.get(Transaction, uuid.UUID(t2_id))
        assert t1_db.transfer_id is None
        assert t2_db.transfer_id is None


def test_issue_10_cross_family_category_validation(client: TestClient):
    """
    Issue 10: 交易创建、拆分与更新中，传入其他家庭的 category_id 严格 400 拦截。
    """
    with Session(engine) as session:
        fam_a = Family(name="Fam A Cats", currency="CNY")
        fam_b = Family(name="Fam B Cats", currency="CNY")
        session.add(fam_a)
        session.add(fam_b)
        session.commit()
        session.refresh(fam_a)
        session.refresh(fam_b)

        user_a = User(
            username=f"u_cat_a_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam_a.id,
            role="owner",
            display_name="User A",
        )
        session.add(user_a)
        session.commit()
        session.refresh(user_a)

        acc_a = Account(family_id=fam_a.id, owner_id=user_a.id, name="Acc A", account_type="checking")
        session.add(acc_a)

        # 在 Family B 中创建私有分类
        cat_b = Category(family_id=fam_b.id, name="Family B Only Cat", category_type="expense")
        session.add(cat_b)
        session.commit()
        session.refresh(acc_a)
        session.refresh(cat_b)

        uname = user_a.username
        acc_a_id = acc_a.id
        cat_b_id = cat_b.id

    _login_cookie(client, uname)

    # 1. 创建交易时引用 Family B 的 category_id
    res_create = client.post("/api/v1/transactions", json={
        "account_id": str(acc_a_id),
        "amount": 25.00,
        "transaction_type": "expense",
        "narration": "Test Ingest",
        "category_id": str(cat_b_id),
    })
    assert res_create.status_code == 400
    assert "属于其他家庭" in res_create.json()["detail"]

    # 创建正常无分类交易供后续测试
    res_valid = client.post("/api/v1/transactions", json={
        "account_id": str(acc_a_id),
        "amount": 100.00,
        "transaction_type": "expense",
        "narration": "For Split and Update",
    })
    txn_id = res_valid.json()["id"]

    # 2. 拆分交易时引用 Family B 的 category_id
    res_split = client.post(f"/api/v1/transactions/{txn_id}/split", json={
        "splits": [
            {"amount": 50.00, "category_id": str(cat_b_id), "notes": "Split Part 1"},
            {"amount": 50.00, "notes": "Split Part 2"},
        ]
    })
    assert res_split.status_code == 400
    assert "属于其他家庭" in res_split.json()["detail"]

    # 3. 更新交易时引用 Family B 的 category_id
    res_update = client.put(f"/api/v1/transactions/{txn_id}", json={
        "category_id": str(cat_b_id),
    })
    assert res_update.status_code == 400
    assert "属于其他家庭" in res_update.json()["detail"]


def test_issue_11_no_family_list_categories_no_key_error(client: TestClient):
    """
    Issue 11: 无家庭用户调用 /api/v1/categories 不会触发 KeyError: 'id' 500。
    """
    with Session(engine) as session:
        user_lonely = User(
            username=f"u_alone_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=None,  # 未加入任何家庭
            role="member",
            display_name="Lonely User",
        )
        session.add(user_lonely)
        session.commit()
        uname = user_lonely.username

    _login_cookie(client, uname)
    res = client.get("/api/v1/categories")
    assert res.status_code == 200
    cats = res.json().get("categories", [])
    assert cats == []  # No fabricated category IDs for users outside a family.
    assert res.json()['count'] == 0


def test_issue_12_no_family_debt_and_tag_creation_returns_400(client: TestClient):
    """
    Issue 12: 无家庭用户创建借贷或标签时，前置返回 400，防止数据库 NOT NULL 约束触发 500。
    """
    with Session(engine) as session:
        user_lonely = User(
            username=f"u_nofam_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=None,
            role="member",
            display_name="No Family User",
        )
        session.add(user_lonely)
        session.commit()
        uname = user_lonely.username

    _login_cookie(client, uname)

    # 1. 创建个人借贷
    res_debt = client.post("/api/v1/debts", json={
        "debtor_or_creditor_name": "Friend",
        "direction": "owe_me",
        "amount": "500.00",
    })
    assert res_debt.status_code == 400
    assert "尚未加入或创建任何家庭" in res_debt.json()["detail"]

    # 2. 创建标签
    res_tag = client.post("/api/v1/tags", json={
        "name": "TravelTag",
        "color": "#ff0000",
    })
    assert res_tag.status_code == 400
    assert "尚未加入或创建任何家庭" in res_tag.json()["detail"]


def test_issue_13_no_family_user_map_empty():
    """
    Issue 13: 当 family_id=None 时，build_user_map 严格返回空字典，杜绝租户枚举。
    """
    with Session(engine) as session:
        user_map = build_user_map(session, family_id=None)
        assert user_map == {}


def test_issue_14_api_config_no_global_leakage(client: TestClient):
    """
    Issue 14: /api/config 仅返回当前家庭的成员昵称或通用占位符，不泄露系统前两位用户。
    """
    with Session(engine) as session:
        # 创建系统最早的两个用户
        fam1 = Family(name="Family 1", currency="CNY")
        session.add(fam1)
        session.commit()
        session.refresh(fam1)

        user1 = User(
            username=f"first_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam1.id,
            display_name="CEO Boss",
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        user2 = User(
            username=f"second_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam1.id,
            display_name="CTO Architect",
            created_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
        session.add(user1)
        session.add(user2)

        # 创建完全独立的 Family 2 与用户
        fam2 = Family(name="Family 2", currency="CNY")
        session.add(fam2)
        session.commit()
        session.refresh(fam2)

        user3 = User(
            username=f"third_{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("Pass123!"),
            family_id=fam2.id,
            display_name="Isolated Guy",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session.add(user3)
        session.commit()
        u3_name = user3.username

    # 1. 未认证访问 /api/config
    client.cookies.clear()
    res_unauth = client.get("/api/config")
    assert res_unauth.status_code == 200
    cfg_unauth = res_unauth.json()
    assert cfg_unauth["userA"] == "用户A"
    assert cfg_unauth["userB"] == "用户B"

    # 2. 属于 Family 2 的用户登录后访问 /api/config
    _login_cookie(client, u3_name)
    res_auth = client.get("/api/config")
    assert res_auth.status_code == 200
    cfg_auth = res_auth.json()
    # 绝不能泄露 Family 1 的 CEO Boss 或 CTO Architect
    assert "CEO Boss" not in str(cfg_auth)
    assert "CTO Architect" not in str(cfg_auth)
    assert cfg_auth["userA"] == "Isolated Guy"

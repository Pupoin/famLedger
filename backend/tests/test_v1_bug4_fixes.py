import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

import database
from main import app
from models import Account, Category, Family, Loan, PersonalDebt, RefundAllocation, Transaction, User


@pytest.fixture(name="client")
def client_fixture():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    def get_test_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[database.get_session] = get_test_session

    with Session(test_engine) as session:
        family = Family(name="测试家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

        user = User(
            family_id=family.id,
            username="owner",
            display_name="家庭所有者",
            role="owner",
        )
        session.add(user)
        session.commit()

    with TestClient(app, headers={"X-FamLedger-CSRF": "1"}) as c:
        yield c

    app.dependency_overrides.clear()


def test_category_parent_validation_and_cycle_prevention(client: TestClient):
    """验证分类父级设置：禁止跨家庭父分类、禁止设置自身为父、禁止多级循环嵌套。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 创建顶层分类 A
    res_a = client.post("/api/v1/categories", json={"name": "一级分类A"}, headers=headers)
    assert res_a.status_code == 200
    cat_a_id = res_a.json()["id"]

    # 2. 创建子分类 B，父级设为 A
    res_b = client.post("/api/v1/categories", json={"name": "二级分类B", "parent_id": cat_a_id}, headers=headers)
    assert res_b.status_code == 200
    cat_b_id = res_b.json()["id"]

    # 3. 尝试将 A 的父级设置为自身，预期拦截 400
    res_self = client.put(f"/api/v1/categories/{cat_a_id}", json={"parent_id": cat_a_id}, headers=headers)
    assert res_self.status_code == 400
    assert "不能将父分类设置为自身" in res_self.json()["detail"]

    # 4. 尝试将 A 的父级设置为 B（形成 A -> B -> A 循环引用），预期拦截 400
    res_cycle = client.put(f"/api/v1/categories/{cat_a_id}", json={"parent_id": cat_b_id}, headers=headers)
    assert res_cycle.status_code == 400
    assert "检测到循环分类引用" in res_cycle.json()["detail"]

    # 5. 尝试传入一个不存在的父分类 UUID，预期拦截 400
    fake_parent = str(uuid.uuid4())
    res_fake = client.post("/api/v1/categories", json={"name": "非法子分类", "parent_id": fake_parent}, headers=headers)
    assert res_fake.status_code == 400


def test_personal_debts_full_lifecycle(client: TestClient):
    """验证借贷完整生命周期：双契约兼容、金额正数校验、超额还款拦截、坏账核销。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 尝试创建金额 <= 0 的借贷，预期拦截 400
    bad_debt = client.post("/api/v1/debts", json={
        "counterparty": "张三",
        "debt_type": "lend",
        "principal_amount": "0.00",
    }, headers=headers)
    assert bad_debt.status_code == 422

    # 2. 使用前端规范（counterparty / debt_type / principal_amount）创建借出借据 1000 元
    res = client.post("/api/v1/debts", json={
        "counterparty": "李四",
        "debt_type": "lend",
        "principal_amount": "1000.00",
        "notes": "借李四应急",
    }, headers=headers)
    assert res.status_code == 200
    debt_data = res.json()
    debt_id = debt_data["id"]
    assert debt_data["counterparty"] == "李四"
    assert debt_data["remaining_amount"] == "1000.00"

    # 3. 尝试还款 <= 0，预期拦截 400
    bad_repay = client.post(f"/api/v1/debts/{debt_id}/repay", json={"amount": "-100.00"}, headers=headers)
    assert bad_repay.status_code == 422

    # 4. 尝试超额还款（1500 > 1000），预期拦截 400
    over_repay = client.post(f"/api/v1/debts/{debt_id}/repay", json={"repay_amount": "1500.00"}, headers=headers)
    assert over_repay.status_code == 400
    assert "超过了当前剩余待还金额" in over_repay.json()["detail"]

    # 5. 部分还款 400 元
    repay_res = client.post(f"/api/v1/debts/{debt_id}/repay", json={"amount": "400.00"}, headers=headers)
    assert repay_res.status_code == 200
    assert repay_res.json()["remaining_amount"] == "600.00"
    assert repay_res.json()["is_settled"] is False

    # 6. 坏账核销
    write_off_res = client.post(f"/api/v1/debts/{debt_id}/write-off", headers=headers)
    assert write_off_res.status_code == 200
    assert write_off_res.json()["status"] == "ok"

    # 7. 再次查询债务列表，确认状态已核销且剩余金额为 0
    list_res = client.get("/api/v1/debts", headers=headers)
    assert list_res.status_code == 200
    target_d = next(d for d in list_res.json()["debts"] if d["id"] == debt_id)
    assert target_d["status"] == "written_off"
    assert target_d["remaining_amount"] == "0.00"


def test_loan_creation_and_listing_contract(client: TestClient):
    """验证长期贷款创建：account_type='loan'，classification='liability'。"""
    headers = {"X-Api-Key": "dev-token"}

    res = client.post("/api/v1/loans", json={
        "name": "招行一手住房按揭贷款",
        "lender": "招商银行",
        "original_principal": "2000000.00",
        "interest_rate": "3.25",
        "term_months": 360,
        "monthly_payment": "8704.12",
        "start_date": "2026-01-01",
    }, headers=headers)
    assert res.status_code == 200
    loan_info = res.json()
    acc_id = loan_info["account_id"]

    # 查验账户详情
    acc_res = client.get(f"/api/v1/accounts/{acc_id}", headers=headers)
    assert acc_res.status_code == 200
    acc_data = acc_res.json()["account"]
    assert acc_data["account_type"] == "loan"
    assert acc_data["classification"] == "liability"


def test_refund_allocation_idempotent_update(client: TestClient):
    """验证退款分配幂等更新：重复为同一原消费分配退款时，更新已有分配而非报 500 唯一键冲突。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 录入一笔消费 500 元
    orig_res = client.post("/api/v1/transactions", json={
        "account_identifier": "招行(8888)",
        "transacted_at": "2026-09-01",
        "amount": "500.00",
        "narration": "电子商城数码配件",
        "transaction_type": "expense",
    }, headers=headers)
    assert orig_res.status_code == 200
    orig_id = orig_res.json()["id"]

    # 2. 录入一笔退款 300 元
    ref_res = client.post("/api/v1/transactions", json={
        "account_identifier": "招行(8888)",
        "transacted_at": "2026-09-05",
        "amount": "300.00",
        "narration": "电子商城退款",
        "transaction_type": "refund",
    }, headers=headers)
    assert ref_res.status_code == 200
    refund_id = ref_res.json()["id"]

    # 3. 首次分配 100 元
    alloc1 = client.post(f"/api/v1/refunds/{refund_id}/allocate", json={
        "original_transaction_id": orig_id,
        "allocated_amount": "100.00",
    }, headers=headers)
    assert alloc1.status_code == 200
    assert Decimal(alloc1.json()["allocated_amount"]) == Decimal("100.00")

    # 4. 第二次为同一对流水分配 200 元（幂等更新），预期返回 200，而不是 500 IntegrityError
    alloc2 = client.post(f"/api/v1/refunds/{refund_id}/allocate", json={
        "original_transaction_id": orig_id,
        "allocated_amount": "200.00",
    }, headers=headers)
    assert alloc2.status_code == 200
    assert Decimal(alloc2.json()["allocated_amount"]) == Decimal("200.00")


def test_account_color_and_icon_persistence(client: TestClient):
    """验证 Account 模型的 color 与 icon 能够被正确保存与读取。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 创建带有自定义 color 和 icon 的账户
    res = client.post("/api/v1/accounts", json={
        "name": "私房钱小金库",
        "account_type": "savings",
        "currency": "CNY",
        "color": "#ec4899",
        "icon": "piggy_bank",
        "balance": "5000.00",
    }, headers=headers)
    assert res.status_code == 200
    acc_id = res.json()["id"]
    assert res.json()["color"] == "#ec4899"
    assert res.json()["icon"] == "piggy_bank"

    # 2. 更新账户颜色与图标
    up_res = client.put(f"/api/v1/accounts/{acc_id}", json={
        "color": "#10b981",
        "icon": "vault",
    }, headers=headers)
    assert up_res.status_code == 200
    assert up_res.json()["account"]["color"] == "#10b981"
    assert up_res.json()["account"]["icon"] == "vault"

    # 3. 获取账户详情再次查验
    get_res = client.get(f"/api/v1/accounts/{acc_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["account"]["color"] == "#10b981"
    assert get_res.json()["account"]["icon"] == "vault"


def test_export_formula_injection_defense(client: TestClient):
    """验证导出 CSV/Excel 时对前缀符号（=, +, -, @）的转义防注入。"""
    headers = {"X-Api-Key": "dev-token"}

    # 录入含有恶意公式注入字符的交易
    client.post("/api/v1/transactions", json={
        "account_identifier": "招行(8888)",
        "transacted_at": "2026-09-10",
        "amount": "100.00",
        "narration": "=cmd|' /C calc'!A0",
        "transaction_type": "expense",
    }, headers=headers)

    # 导出 Excel
    res_export = client.get("/api/export", headers=headers)
    assert res_export.status_code == 200
    import openpyxl
    from io import BytesIO
    wb = openpyxl.load_workbook(BytesIO(res_export.content))
    ws = wb.active
    values = [cell.value for row in ws.rows for cell in row]
    assert "'=cmd|' /C calc'!A0" in values


def test_family_kick_and_migration(client: TestClient):
    """验证移出家庭成员：为成员创建独立空间，迁移名下账户，清理跨家庭共享。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 家庭管理员直接创建成员 Bob
    fam_res = client.get("/api/v1/family/current", headers=headers)
    fam_id = fam_res.json()["id"]

    create_b = client.post("/api/v1/family/members/create", json={
        "username": "bob_member",
        "display_name": "老鲍",
        "password": "Password123!",
        "role": "member",
    }, headers=headers)
    assert create_b.status_code == 200
    bob_id = create_b.json()["user"]["id"]

    # 登录 Bob
    login_b = client.post("/api/auth/login", json={"username": "bob_member", "password": "Password123!"})
    b_cookies = login_b.cookies

    # 3. Bob 创建一个属于自己的私有账户
    acc_res = client.post("/api/v1/accounts", json={
        "name": "Bob的工商银行卡",
        "account_type": "checking",
        "currency": "CNY",
        "balance": "3000.00",
    }, cookies=b_cookies)
    assert acc_res.status_code == 200
    bob_acc_id = acc_res.json()["id"]

    # 4. 家庭管理员移出 Bob
    kick_res = client.post(f"/api/v1/family/members/{bob_id}/kick", headers=headers)
    assert kick_res.status_code == 200

    # 5. 验证 Bob 自动拥有了新的独立个人空间，且名下账户已迁移
    bob_fam_res = client.get("/api/v1/family/current", cookies=b_cookies)
    assert bob_fam_res.status_code == 200
    assert "老鲍的个人空间" in bob_fam_res.json()["name"]
    new_fam_id = bob_fam_res.json()["id"]
    assert new_fam_id != fam_id

    # 查验 Bob 的账户已迁移至其个人空间
    bob_acc_get = client.get(f"/api/v1/accounts/{bob_acc_id}", cookies=b_cookies)
    assert bob_acc_get.status_code == 200


def test_apikey_minting_protection(client: TestClient):
    """验证安全策略：禁止使用 API Key 调用接口再次生成新的 API Key（防凭证套娃）。"""
    # 1. 注册普通用户
    reg = client.post("/api/auth/register", json={
        "username": "key_user",
        "display_name": "密钥用户",
        "password": "Password123!",
        "security_question": "color",
        "security_answer": "blue",
    })
    assert reg.status_code == 201
    cookies = client.post("/api/auth/login", json={"username": "key_user", "password": "Password123!"}).cookies

    # 2. 通过 Cookie 会话创建第一枚 API Key
    key_res = client.post("/api/v1/api-keys", json={"name": "FirstKey"}, cookies=cookies)
    assert key_res.status_code == 201
    raw_key = key_res.json()["raw_key"]

    # 3. 使用该 API Key 尝试生成第二枚 API Key，预期返回 403 拦截
    key_headers = {"Authorization": f"Bearer {raw_key}"}
    mint_res = client.post("/api/v1/api-keys", json={"name": "SecondKey"}, headers=key_headers)
    assert mint_res.status_code == 403
    assert "禁止使用 API Key" in mint_res.json()["detail"]


def test_category_delete_role_check(client: TestClient):
    """验证分类删除权限：普通成员不可删除分类 (403)，管理员/Owner 允许删除。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 创建待删除分类
    cat_res = client.post("/api/v1/categories", json={"name": "临时测试分类"}, headers=headers)
    assert cat_res.status_code == 200
    cat_id = cat_res.json()["id"]

    # 2. 普通成员尝试删除该分类，预期拦截 403
    reg_m = client.post("/api/auth/register", json={
        "username": "normal_member",
        "display_name": "普通成员",
        "password": "Password123!",
        "security_question": "color",
        "security_answer": "blue",
    })
    assert reg_m.status_code == 201
    m_cookies = client.post("/api/auth/login", json={"username": "normal_member", "password": "Password123!"}).cookies
    fam_name = client.get("/api/v1/family/current", headers=headers).json()["name"]
    client.post("/api/v1/family/join", json={"family_name": fam_name}, cookies=m_cookies)

    del_by_member = client.delete(f"/api/v1/categories/{cat_id}", cookies=m_cookies)
    assert del_by_member.status_code == 403

    # 3. 超管/服务凭证删除该分类，预期成功 200
    del_by_admin = client.delete(f"/api/v1/categories/{cat_id}", headers=headers)
    assert del_by_admin.status_code == 200
    assert del_by_admin.status_code == 200

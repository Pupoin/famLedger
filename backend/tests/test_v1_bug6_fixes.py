import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine
from models import Account, AccountShare, Category, Family, Loan, PersonalDebt, RefundAllocation, Rule, Tag, Transaction, TransactionSplit, Transfer, User
from auth import hash_password


def test_backup_dest_initialization(tmp_path):
    """验证备份服务正常初始化 dest 目录，无 UnboundLocalError 且可验证。"""
    from services.backup import BackupManager
    from sqlmodel import SQLModel, create_engine

    db_path = tmp_path / "famledger.db"
    eng = create_engine(f"sqlite:///{db_path}")
    from models import User
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(User(
            username="test_admin",
            display_name="测试管理员",
            password_hash="x",
            security_question="q",
            security_answer_hash="a",
            role="admin",
        ))
        s.commit()
    eng.dispose()

    mgr = BackupManager(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", backup_dir=tmp_path / "backups")
    dest = mgr.create_backup()
    assert dest.exists()
    assert mgr.verify_backup(dest) is True


def test_private_account_idor_defense(client: TestClient):
    """验证家庭 Owner 无法越权修改成员私有账户共享列表，亦不可越权平账。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 创建普通成员 Alice
    reg_a = client.post("/api/v1/family/members/create", json={
        "username": "alice_private",
        "display_name": "爱丽丝",
        "password": "Password123!",
        "role": "member",
    }, headers=headers)
    assert reg_a.status_code == 200
    alice_id = reg_a.json()["user"]["id"]

    # 登录 Alice 并创建私有账户
    alice_login = client.post("/api/auth/login", json={"username": "alice_private", "password": "Password123!"})
    alice_cookies = alice_login.cookies
    acc_res = client.post("/api/v1/accounts", json={
        "name": "Alice私密金库",
        "account_type": "checking",
        "balance": "9999.00",
    }, cookies=alice_cookies)
    assert acc_res.status_code == 200
    acc_id = acc_res.json()["id"]

    # 2. 注册并登录普通家庭 Owner Bob
    reg_b = client.post("/api/v1/family/members/create", json={
        "username": "bob_owner",
        "display_name": "鲍勃管理员",
        "password": "Password123!",
        "role": "owner",
    }, headers=headers)
    assert reg_b.status_code == 200

    bob_login = client.post("/api/auth/login", json={"username": "bob_owner", "password": "Password123!"})
    bob_cookies = bob_login.cookies

    # Bob 试图调用 shares 接口将自己加入 Alice 私有账户的共享列表提权
    attack_payload = {
        "members": [{
            "user_id": str(reg_b.json()["user"]["id"]),
            "permission": "full_control",
        }]
    }
    share_attack = client.patch(f"/api/v1/accounts/{acc_id}/shares", json=attack_payload, cookies=bob_cookies)
    assert share_attack.status_code == 403

    # Bob 试图越权对 Alice 的私有账户平账
    reconcile_attack = client.post(f"/api/v1/accounts/{acc_id}/reconcile-balance", json={
        "new_balance": "0.00",
    }, cookies=bob_cookies)
    assert reconcile_attack.status_code == 403


def test_subcard_management_permission_defense(client: TestClient):
    """验证副卡关联主卡时强制核验主卡管理权，禁止挂靠他人私密主卡。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 成员 Carol 创建主信用卡
    client.post("/api/v1/family/members/create", json={
        "username": "carol_user",
        "display_name": "卡罗尔",
        "password": "Password123!",
        "role": "member",
    }, headers=headers)
    c_login = client.post("/api/auth/login", json={"username": "carol_user", "password": "Password123!"})
    c_cookies = c_login.cookies

    c_acc = client.post("/api/v1/accounts", json={
        "name": "Carol主信用卡",
        "account_type": "credit_card",
        "balance": "0.00",
    }, cookies=c_cookies)
    assert c_acc.status_code == 200
    master_card_id = c_acc.json()["id"]

    # 2. 成员 Dave 试图创建副卡并关联到 Carol 的主卡
    client.post("/api/v1/family/members/create", json={
        "username": "dave_user",
        "display_name": "戴夫",
        "password": "Password123!",
        "role": "member",
    }, headers=headers)
    d_login = client.post("/api/auth/login", json={"username": "dave_user", "password": "Password123!"})
    d_cookies = d_login.cookies

    d_sub = client.post("/api/v1/accounts", json={
        "name": "Dave副卡",
        "account_type": "credit_card",
        "parent_account_id": master_card_id,
    }, cookies=d_cookies)
    assert d_sub.status_code == 403


def test_transaction_update_transfer_sync_and_refund_cap(client: TestClient, service_family):
    """验证转账流水金额修改联动双向同步，以及退款已冲抵金额下限防护。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 创建两个账户
    acc1 = client.post("/api/v1/accounts", json={"name": "转出行", "account_type": "checking", "balance": "5000.00"}, headers=headers).json()["id"]
    acc2 = client.post("/api/v1/accounts", json={"name": "转入行", "account_type": "checking", "balance": "1000.00"}, headers=headers).json()["id"]

    # 2. 创建一笔转账
    txn_out = client.post("/api/v1/transactions", json={
        "account_id": acc1,
        "amount": "200.00",
        "transaction_type": "transfer",
        "extra": {"to_account_id": acc2},
        "transacted_at": "2026-09-25",
        "narration": "测试转账200",
    }, headers=headers).json()
    out_id = txn_out["id"]

    # 3. 更新出账流水金额为 300，验证联动对端与 Transfer 记录
    patch_res = client.patch(f"/api/v1/transactions/{out_id}", json={"amount": "300.00"}, headers=headers)
    assert patch_res.status_code == 200

    # 查验转账记录金额已同步为 300
    tf_list = client.get("/api/v1/transfers", headers=headers).json()["items"]
    assert any(str(t["amount"]) == "300.00" for t in tf_list)

    # 4. 禁止跨账户移动已配对转账
    move_res = client.patch(f"/api/v1/transactions/{out_id}", json={"account_id": acc2}, headers=headers)
    assert move_res.status_code == 400

    # 5. 测试退款冲抵下限防护
    exp_res = client.post("/api/v1/transactions", json={
        "account_id": acc1,
        "amount": "500.00",
        "transaction_type": "expense",
        "transacted_at": "2026-09-20",
        "narration": "购买大件",
    }, headers=headers).json()
    exp_id = exp_res["id"]

    ref_res = client.post("/api/v1/transactions", json={
        "account_id": acc1,
        "amount": "200.00",
        "transaction_type": "refund",
        "transacted_at": "2026-09-22",
        "narration": "大件部分退款",
    }, headers=headers).json()
    ref_id = ref_res["id"]

    client.post(f"/api/v1/refunds/{ref_id}/link/{exp_id}", headers=headers)

    # 尝试将原消费金额修改为 150（低于已冲抵的 200），预期 400 拦截
    cap_res = client.patch(f"/api/v1/transactions/{exp_id}", json={"amount": "150.00"}, headers=headers)
    assert cap_res.status_code == 400
    assert "解除关联" in cap_res.json()["detail"]


def test_delete_category_cascades_subcategories_and_splits(client: TestClient, service_family):
    """验证删除分类级联解绑子分类与流水拆分项，杜绝外键约束 500。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 创建父分类与子分类
    p_cat = client.post("/api/v1/categories", json={"name": "父分类测试"}, headers=headers).json()["id"]
    sub_cat = client.post("/api/v1/categories", json={"name": "子分类测试", "parent_id": p_cat}, headers=headers).json()["id"]

    # 2. 创建带拆分项的交易
    acc = client.post("/api/v1/accounts", json={"name": "分类测试户", "account_type": "checking"}, headers=headers).json()["id"]
    t_res = client.post("/api/v1/transactions", json={
        "account_id": acc,
        "amount": "100.00",
        "transaction_type": "expense",
        "transacted_at": "2026-09-20",
        "category_id": p_cat,
        "splits": [{"amount": "100.00", "category_id": p_cat, "narration": "拆分项"}],
    }, headers=headers)
    assert t_res.status_code == 200

    # 3. 删除父分类，验证成功删除且不报 500
    del_res = client.delete(f"/api/v1/categories/{p_cat}", headers=headers)
    assert del_res.status_code == 200

    # 子分类 parent_id 已解绑为 null
    sub_get = client.get("/api/v1/categories", headers=headers).json()["items"]
    sub_entry = next((c for c in sub_get if c["id"] == sub_cat), None)
    assert sub_entry is not None
    assert sub_entry["parent_id"] is None


def test_loan_positive_liability_balance(client: TestClient, service_family):
    """验证长期贷款建立负债账户时 balance 为正数，契合负债与净资产定义。"""
    headers = {"X-Api-Key": "dev-token"}

    loan_res = client.post("/api/v1/debts/loans", json={
        "name": "测试房贷200万",
        "original_principal": "2000000.00",
        "current_balance": "1800000.00",
        "interest_rate": "3.85",
        "term_months": 360,
        "start_date": "2026-01-01",
    }, headers=headers)
    assert loan_res.status_code == 200
    loan_acc_id = loan_res.json()["account_id"]

    # 验证账户余额为正数 1800000.00
    acc_detail = client.get(f"/api/v1/accounts/{loan_acc_id}", headers=headers).json()["account"]
    assert Decimal(str(acc_detail["balance"])) > 0
    assert Decimal(str(acc_detail["balance"])) == Decimal("1800000.00")


def test_debts_contract_items_and_rules_patch(client: TestClient, service_family, db):
    """验证借贷列表返回 items 契约字段，且规则路由支持 PATCH。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 借贷列表 items 字段
    d_list = client.get("/api/v1/debts", headers=headers).json()
    assert "items" in d_list
    assert isinstance(d_list["items"], list)

    # 2. 规则 PATCH 更新
    category = Category(family_id=service_family.id, name='餐饮美食')
    db.add(category); db.commit()
    r_create = client.post("/api/v1/rules", json={
        "name": "自动打标测试规则",
        "conditions": {"operator": "AND", "rules": [{"field": "narration", "operator": "contains", "value": "星巴克"}]},
        "actions": [{"type": "set_category", "value": str(category.id)}],
        "priority": 10,
    }, headers=headers)
    assert r_create.status_code == 200
    rule_id = r_create.json()["id"]

    patch_res = client.patch(f"/api/v1/rules/{rule_id}", json={"is_active": False}, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["is_active"] is False


def test_export_csv_alias(client: TestClient, service_family):
    """验证设置页面下载链接 /api/export/csv 正常响应。"""
    headers = {"X-Api-Key": "dev-token"}
    res = client.get("/api/export/csv", headers=headers)
    assert res.status_code == 200
    assert "spreadsheet" in res.headers.get("content-type", "")


def test_delete_transaction_unlinks_refund_of_transaction_id(client: TestClient, service_family):
    """验证删除被退款引用的原消费时，自动解除退款流水的 refund_of_transaction_id 引用，无外键 500。"""
    headers = {"X-Api-Key": "dev-token"}
    acc = client.post("/api/v1/accounts", json={"name": "退款自引用测试账户", "account_type": "checking"}, headers=headers).json()["id"]

    # 1. 创建原消费与退款
    orig = client.post("/api/v1/transactions", json={
        "account_id": acc,
        "amount": "500.00",
        "transaction_type": "expense",
        "transacted_at": "2026-09-25",
        "narration": "原消费大件",
    }, headers=headers).json()["id"]

    rf = client.post("/api/v1/transactions", json={
        "account_id": acc,
        "amount": "100.00",
        "transaction_type": "refund",
        "transacted_at": "2026-09-26",
        "narration": "部分退款",
    }, headers=headers).json()["id"]

    # 关联退款
    link_res = client.post(f"/api/v1/refunds/{rf}/link/{orig}", headers=headers)
    assert link_res.status_code == 200

    # 2. 删除原消费交易，验证外键约束下平稳成功
    del_res = client.delete(f"/api/v1/transactions/{orig}", headers=headers)
    assert del_res.status_code == 200

    # 3. 验证退款交易的退款关联已被解绑
    rf_detail = client.get(f"/api/v1/transactions/{rf}", headers=headers).json()
    assert rf_detail["refund_info"]["is_linked"] is False
    assert rf_detail["refund_info"]["original_transaction"] is None


def test_delete_family_cascades_transfers_and_refunds(client: TestClient):
    """验证解散家庭时剩余账户流水包含 Transfer 与退款引用时平稳级联清理，不报外键 500。"""
    from uuid import uuid4
    uname = f"u_del_fam_{uuid4().hex[:6]}"
    pw = "TestPass123456!"
    client.post("/api/auth/register", json={
        "username": uname,
        "display_name": "家庭测试员",
        "password": pw,
        "security_question": "What city were you born in?",
        "security_answer": "Beijing",
    })
    login_res = client.post("/api/auth/login", json={"username": uname, "password": pw})
    u_cookies = login_res.cookies

    # 创建新家庭
    fam_res = client.post("/api/v1/family/create", json={"name": "待解散测试家庭", "currency": "CNY"}, cookies=u_cookies)
    assert fam_res.status_code == 200
    fam_id = fam_res.json()["family"]["id"]

    # 在该家庭创建两账户与转账
    a1 = client.post("/api/v1/accounts", json={"name": "家庭账户A", "account_type": "checking"}, cookies=u_cookies).json()["id"]
    a2 = client.post("/api/v1/accounts", json={"name": "家庭账户B", "account_type": "checking"}, cookies=u_cookies).json()["id"]

    # 创建转账
    tr_res = client.post("/api/v1/transfers", json={
        "from_account_id": a1,
        "to_account_id": a2,
        "amount": "88.00",
        "transacted_at": "2026-09-28",
        "narration": "家庭内部转账",
    }, cookies=u_cookies)
    assert tr_res.status_code == 200

    # 解散家庭，验证无外键约束冲突，成功 200
    del_fam_res = client.delete(f"/api/v1/family/{fam_id}", cookies=u_cookies)
    assert del_fam_res.status_code == 200

import os
import uuid
from decimal import Decimal
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine
from models import (
    Account, Category, Family, Loan, PersonalDebt, Rule, Tag, Transaction, User
)


def test_budget_settings_endpoint_success_and_validation(client: TestClient):
    """验证预算设置接口正常执行无 NameError，且严格校验数值非负与有效性。"""
    headers = {"X-Api-Key": "dev-token"}

    # 0. 先为 alice 关联家庭
    with Session(engine) as s:
        alice = s.exec(select(User).where(User.username == "alice")).first()
        if alice and not alice.family_id:
            fam = Family(name="预算测试家庭", currency="CNY")
            s.add(fam)
            s.commit()
            s.refresh(fam)
            alice.family_id = fam.id
            alice.role = "owner"
            s.add(alice)
            s.commit()

    # 1. 创建管理员用户并登录
    u_name = f"b_admin_{uuid.uuid4().hex[:6]}"
    reg = client.post("/api/v1/family/members/create", json={
        "username": u_name,
        "display_name": "预算管理员",
        "password": "Password123!",
        "role": "admin",
    }, headers=headers)
    assert reg.status_code == 200

    login = client.post("/api/auth/login", json={"username": u_name, "password": "Password123!"})
    cookies = login.cookies

    # 2. 正常配置预算
    res = client.post("/api/v1/budgets/settings", json={
        "total_budget": 12000.0,
        "expected_income": 25000.0,
        "category_budgets": {"餐饮美食": 3000.0, "购物消费": 2000.0},
    }, cookies=cookies)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["settings"]["total_budget"] == 12000.0
    assert data["settings"]["expected_income"] == 25000.0

    # 3. 负数校验拦截
    bad_res = client.post("/api/v1/budgets/settings", json={
        "total_budget": -500.0,
    }, cookies=cookies)
    assert bad_res.status_code == 400

    bad_cat = client.post("/api/v1/budgets/settings", json={
        "category_budgets": {"餐饮美食": -100.0},
    }, cookies=cookies)
    assert bad_cat.status_code == 400


def test_case_insensitive_username_collision_prevention(client: TestClient):
    """验证注册、资料更新、家庭添加成员入口对大小写用户名进行防碰撞拦截。"""
    prefix = uuid.uuid4().hex[:6]
    orig_name = f"AliceUser_{prefix}"
    lower_name = orig_name.lower()

    # 1. 注册原始大写用户名
    reg = client.post("/api/auth/register", json={
        "username": orig_name,
        "display_name": f"Alice {prefix}",
        "password": "Password123!",
        "security_question": "Your pet name?",
        "security_answer": "Fluffy",
    })
    assert reg.status_code == 201

    # 2. 尝试用小写用户名注册 -> 409
    reg_collision = client.post("/api/auth/register", json={
        "username": lower_name,
        "display_name": f"Alice Twin {prefix}",
        "password": "Password123!",
        "security_question": "Your pet name?",
        "security_answer": "Fluffy",
    })
    assert reg_collision.status_code == 409

    # 3. 尝试在家庭管理员接口添加同名小写成员 -> 400
    headers = {"X-Api-Key": "dev-token"}
    fam_add = client.post("/api/v1/family/members/create", json={
        "username": lower_name,
        "display_name": "Fake Alice",
        "password": "Password123!",
        "role": "member",
    }, headers=headers)
    assert fam_add.status_code == 400


def test_reconciliation_type_validation_and_transfer_check(client: TestClient, service_family):
    """验证对账类型非法枚举被 400 拦截，转账对账目标账户归属被严格校验。"""
    headers = {"X-Api-Key": "dev-token"}

    # 创建账户
    acc_res = client.post("/api/v1/accounts", json={
        "name": f"对账账户_{uuid.uuid4().hex[:6]}",
        "account_type": "checking",
        "balance": "1000.00",
    }, headers=headers)
    assert acc_res.status_code == 200
    acc_id = acc_res.json()["id"]

    # 1. 非法 reconciliation_type 拦截
    bad_type = client.post(f"/api/v1/accounts/{acc_id}/reconcile-balance", json={
        "new_balance": "1200.00",
        "reconciliation_type": "arbitrary_hack_string",
    }, headers=headers)
    assert bad_type.status_code == 400

    # 2. 转账对账但对端账户属于不存在的 UUID
    fake_counterparty = str(uuid.uuid4())
    bad_transfer = client.post(f"/api/v1/accounts/{acc_id}/reconcile-balance", json={
        "new_balance": "1200.00",
        "reconciliation_type": "transfer",
        "counterparty_account_id": fake_counterparty,
    }, headers=headers)
    assert bad_transfer.status_code == 400

    # 3. 合法 adjustment 对账成功
    good_adj = client.post(f"/api/v1/accounts/{acc_id}/reconcile-balance", json={
        "new_balance": "1200.00",
        "reconciliation_type": "adjustment",
    }, headers=headers)
    assert good_adj.status_code == 200
    assert good_adj.json()["status"] == "ok"


def test_admin_super_privilege_across_families(client: TestClient):
    """验证系统管理员 (admin) 拥有跨家庭管理借贷与规则的特权。"""
    headers = {"X-Api-Key": "dev-token"}

    # 0. 先为 alice 关联家庭
    with Session(engine) as s:
        alice = s.exec(select(User).where(User.username == "alice")).first()
        if alice and not alice.family_id:
            fam = Family(name="债务测试家庭", currency="CNY")
            s.add(fam)
            s.commit()
            s.refresh(fam)
            alice.family_id = fam.id
            alice.role = "owner"
            s.add(alice)
            s.commit()

    # 1. 创建属于家庭 A 的借贷
    debt_res = client.post("/api/v1/debts", json={
        "person_name": "张三",
        "amount": "1000.00",
        "debt_type": "borrow",
        "due_date": "2026-12-31",
    }, headers=headers)
    assert debt_res.status_code == 200
    debt_id = debt_res.json()["id"]

    # 2. 创建系统管理员用户
    admin_uname = f"sysadmin_{uuid.uuid4().hex[:6]}"
    reg = client.post("/api/v1/family/members/create", json={
        "username": admin_uname,
        "display_name": "系统超管",
        "password": "Password123!",
        "role": "admin",
    }, headers=headers)
    assert reg.status_code == 200

    login = client.post("/api/auth/login", json={"username": admin_uname, "password": "Password123!"})
    cookies = login.cookies

    # 3. 超管成功执行还款
    repay_res = client.post(f"/api/v1/debts/{debt_id}/repay", json={
        "amount": "200.00",
    }, cookies=cookies)
    assert repay_res.status_code == 200
    assert repay_res.json()["remaining_amount"] == "800.00"

    # 4. 超管成功核销借据
    write_off_res = client.post(f"/api/v1/debts/{debt_id}/write-off", json={}, cookies=cookies)
    assert write_off_res.status_code == 200
    assert write_off_res.json()["status"] == "ok"


def test_backup_verify_requires_database_dump_for_postgres(tmp_path, monkeypatch):
    """验证非 SQLite 模式（如 PostgreSQL）下，备份必须包含非空 famledger.sql。"""
    from services.backup import BackupManager
    import database

    # 模拟 PostgreSQL 环境
    monkeypatch.setattr(database, "is_sqlite", False)

    mgr = BackupManager(db_path=tmp_path / "famledger.db", audit_log_path=tmp_path / "audit.jsonl", backup_dir=tmp_path / "backups")
    dest = tmp_path / "backups" / "test_backup"
    dest.mkdir(parents=True)

    # 只有 audit.jsonl，没有 famledger.sql -> 必须返回 False
    (dest / "audit.jsonl").write_text("{}", encoding="utf-8")
    assert mgr.verify_backup(dest) is False

    # 存在空的 famledger.sql -> 必须返回 False
    (dest / "famledger.sql").write_text("", encoding="utf-8")
    assert mgr.verify_backup(dest) is False

    # 存在非空的 famledger.sql -> 验证通过
    (dest / "famledger.sql").write_text("-- PostgreSQL Dump", encoding="utf-8")
    assert mgr.verify_backup(dest) is True

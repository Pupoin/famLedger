import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

import sys
sys.path.insert(0, "backend")

import database
from main import app
from models import Family, User, Account, Category, Transaction, Rule


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
        family = Family(name="规则测试家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

        user = User(family_id=family.id, username="tester", display_name="测试员")
        session.add(user)

        cat_dining = Category(id=uuid.uuid4(), family_id=family.id, name="餐饮美食")
        cat_coffee = Category(id=uuid.uuid4(), family_id=family.id, name="咖啡茶饮")
        session.add(cat_dining)
        session.add(cat_coffee)

        acc = Account(
            family_id=family.id,
            owner_id=user.id,
            name="招行卡",
            account_type="credit_card",
        )
        session.add(acc)
        session.commit()

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_rules_pipeline_and_dry_run(client: TestClient):
    headers = {"X-Api-Key": "dev-token"}

    # 1. 录入几笔未分类交易
    client.post("/api/v1/transactions", json={
        "account_identifier": "招行卡",
        "transacted_at": "2026-09-25",
        "amount": "28.50",
        "name": "美团外卖-黄焖鸡米饭",
        "merchant_name": "美团外卖",
    }, headers=headers)

    client.post("/api/v1/transactions", json={
        "account_identifier": "招行卡",
        "transacted_at": "2026-09-25",
        "amount": "36.00",
        "name": "星巴克咖啡-臻选店",
        "merchant_name": "星巴克咖啡",
    }, headers=headers)

    # 2. 创建一条复合规则（正则表达式匹配美团外卖，自动重命名商户并打标）
    rule_payload = {
        "name": "美团外卖自动清洗",
        "priority": 10,
        "stop_processing": False,
        "is_active": True,
        "conditions": {
            "operator": "AND",
            "rules": [
                {"field": "name", "operator": "regex", "value": "^美团外卖.*"},
                {"field": "amount", "operator": "between", "value": [10, 100]},
            ]
        },
        "actions": [
            {"type": "set_merchant", "value": "美团外卖"},
            {"type": "add_tag", "value": "工作日午餐"},
        ]
    }

    # 3. 先执行 Dry Run 预演，确保不修改数据库
    dry_run_res = client.post("/api/v1/rules/dry-run", json={"rule": rule_payload}, headers=headers)
    assert dry_run_res.status_code == 200
    dry_data = dry_run_res.json()
    assert dry_data["total_evaluated"] == 2
    assert dry_data["total_affected"] == 1 # 仅命中美团外卖，不命中星巴克
    assert "美团外卖" in dry_data["affected_transactions"][0]["matched_rules"][0]["rule_name"]

    # 4. 创建该规则并追溯应用 (Apply retroactively)
    create_res = client.post("/api/v1/rules", json=rule_payload, headers=headers)
    assert create_res.status_code == 200

    rules_list = client.get("/api/v1/rules", headers=headers).json()
    rule_id = rules_list["rules"][0]["id"]

    apply_res = client.post(f"/api/v1/rules/{rule_id}/apply", headers=headers)
    assert apply_res.status_code == 200
    assert apply_res.json()["modified_count"] == 1


def test_personal_debts_and_repayments(client: TestClient):
    headers = {"X-Api-Key": "dev-token"}

    # 1. 记录借出给朋友 500 元
    create_resp = client.post("/api/v1/debts", json={
        "debtor_or_creditor_name": "张三",
        "direction": "owe_me",
        "amount": "500.00",
        "notes": "借张三吃火锅垫付",
    }, headers=headers)
    assert create_resp.status_code == 200
    debt = create_resp.json()
    debt_id = debt["id"]
    assert debt["remaining_balance"] == "500.00"
    assert debt["is_settled"] is False

    # 2. 朋友部分还款 200 元
    repay_resp = client.post(f"/api/v1/debts/{debt_id}/repay", json={
        "repay_amount": "200.00",
        "notes": "微信转账还款",
    }, headers=headers)
    assert repay_resp.status_code == 200
    repay_data = repay_resp.json()
    assert repay_data["remaining_balance"] == "300.00"
    assert repay_data["is_settled"] is False

    # 3. 朋友全部结清余款 300 元
    final_repay = client.post(f"/api/v1/debts/{debt_id}/repay", json={
        "repay_amount": "300.00",
        "notes": "结清",
    }, headers=headers)
    assert final_repay.status_code == 200
    assert final_repay.json()["remaining_balance"] == "0.00"
    assert final_repay.json()["is_settled"] is True

    # 4. 查询统计汇总
    summary_resp = client.get("/api/v1/debts", headers=headers).json()
    assert summary_resp["summary"]["total_owe_me"] == "0.00"

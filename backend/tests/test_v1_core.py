import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

import sys
sys.path.insert(0, "backend")

import database
from main import app
from models import Family, User, Account, Category, StoredEmail, Transaction, Transfer, RefundAllocation


@pytest.fixture(name="client")
def client_fixture():
    # 使用内存 SQLite 测试引擎
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

        cat_food = Category(family_id=family.id, name="餐饮美食")
        cat_shop = Category(family_id=family.id, name="日常购物")
        session.add(cat_food)
        session.add(cat_shop)

        acc = Account(
            family_id=family.id,
            owner_id=user.id,
            name="招商银行信用卡 (9085)",
            account_type="credit_card",
            currency="CNY",
            institution_name="招商银行",
        )
        session.add(acc)
        session.commit()

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_raw_email_import_and_deduplication(client: TestClient):
    headers = {"X-Api-Key": "dev-token"}
    payload = {
        "message_id": "graph_msg_001",
        "mail_kind": "credit_daily",
        "subject": "招商银行信用卡每日信用管家",
        "sender": "ccsvc@message.cmbchina.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "raw_html": "<html><body>您的信用卡消费明细：美团外卖 35.50元</body></html>",
        "raw_text": "您的信用卡消费明细：美团外卖 35.50元",
        "raw_payload": {"id": "graph_msg_001", "body": "test"},
    }

    # 1. 首次存入原始邮件
    resp = client.post("/api/v1/imports/emails", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new"] is True
    assert data["status"] == "pending"
    email_id = data["id"]

    # 2. 再次存入相同 message_id 的邮件（幂等去重）
    dup_resp = client.post("/api/v1/imports/emails", json=payload, headers=headers)
    assert dup_resp.status_code == 200
    dup_data = dup_resp.json()
    assert dup_data["is_new"] is False
    assert dup_data["id"] == email_id

    # 3. 查询邮件列表
    list_resp = client.get("/api/v1/imports/emails", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1

    # 4. 查询单封邮件详情
    detail_resp = client.get(f"/api/v1/imports/emails/{email_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert "美团外卖" in detail["raw_html"]


def test_transaction_ingest_and_email_linkage(client: TestClient):
    headers = {"X-Api-Key": "dev-token"}

    # 1. 先存原始邮件
    email_payload = {
        "message_id": "graph_msg_002",
        "mail_kind": "credit_recent",
        "subject": "近期消费明细",
        "sender": "ccsvc@message.cmbchina.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "raw_html": "<html>星巴克 38.00元</html>",
    }
    email_res = client.post("/api/v1/imports/emails", json=email_payload, headers=headers).json()
    email_id = email_res["id"]

    # 2. 推送解析得到的交易流水并关联 raw_email_id
    txn_payload = {
        "account_identifier": "9085",
        "transacted_at": "2026-09-26",
        "amount": "38.00",
        "currency": "CNY",
        "name": "星巴克咖啡",
        "merchant_name": "星巴克",
        "nature": "expense",
        "external_id": "ext_starbucks_001",
        "raw_email_id": email_id,
        "notes": "信用卡刷卡消费",
    }
    txn_res = client.post("/api/v1/transactions", json=txn_payload, headers=headers)
    assert txn_res.status_code == 200
    txn_data = txn_res.json()
    assert txn_data["status"] == "created"
    assert txn_data["amount"] == "38.00"

    # 3. 校验邮件状态已回写为 parsed，且关联计数为 1
    email_check = client.get(f"/api/v1/imports/emails/{email_id}", headers=headers).json()
    assert email_check["status"] == "parsed"
    assert email_check["parsed_count"] == 1
    assert len(email_check["parsed_transactions"]) == 1
    assert email_check["parsed_transactions"][0]["name"] == "星巴克咖啡"


def test_auto_transfer_matching(client: TestClient):
    headers = {"X-Api-Key": "dev-token"}

    # 1. 录入招行借记卡转出 1000 元
    client.post("/api/v1/transactions", json={
        "account_identifier": "借记卡(6061)",
        "transacted_at": "2026-09-25",
        "amount": "1000.00",
        "name": "招商银行行内转账",
        "transaction_type": "expense",
        "external_id": "outflow_1000",
    }, headers=headers)

    # 2. 录入信用卡还款入账 1000 元（同一天或两天内）
    client.post("/api/v1/transactions", json={
        "account_identifier": "信用卡(9085)",
        "transacted_at": "2026-09-25",
        "amount": "1000.00",
        "name": "信用卡网上还款",
        "transaction_type": "income",
        "external_id": "inflow_1000",
    }, headers=headers)

    # 3. 检查是否自动配对为 Transfer
    transfers_resp = client.get("/api/v1/transfers", headers=headers)
    assert transfers_resp.status_code == 200
    data = transfers_resp.json()
    assert data["count"] == 1
    assert data["transfers"][0]["amount"] == "1000.00"
    assert data["transfers"][0]["status"] == "confirmed"


def test_auto_refund_matching(client: TestClient):
    headers = {"X-Api-Key": "dev-token"}

    # 1. 录入原消费 150 元
    client.post("/api/v1/transactions", json={
        "account_identifier": "信用卡(9085)",
        "transacted_at": "2026-09-20",
        "amount": "150.00",
        "name": "京东商城-图书音像",
        "merchant_name": "京东商城",
        "transaction_type": "expense",
        "external_id": "jd_orig_150",
    }, headers=headers)

    # 2. 录入退款 50 元
    client.post("/api/v1/transactions", json={
        "account_identifier": "信用卡(9085)",
        "transacted_at": "2026-09-22",
        "amount": "50.00",
        "name": "京东退款",
        "merchant_name": "京东商城",
        "nature": "refund",
        "external_id": "jd_refund_50",
    }, headers=headers)

    # 3. 验证退款是否关联成功
    txns = client.get("/api/v1/transactions", headers=headers).json()["items"]
    refund_txn = next(t for t in txns if t["external_id"] == "jd_refund_50")
    orig_txn = next(t for t in txns if t["external_id"] == "jd_orig_150")

    assert refund_txn["refund_of_transaction_id"] == orig_txn["id"]

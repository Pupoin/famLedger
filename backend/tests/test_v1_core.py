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
from models import Family, User, Account, Category, Transaction, Transfer, RefundAllocation


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
        session.flush()

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

    with TestClient(app, headers={"X-FamLedger-CSRF": "1"}) as client:
        yield client

    app.dependency_overrides.clear()


def test_transaction_ingest_direct(client: TestClient):
    headers = {"X-Api-Key": "dev-token"}

    txn_payload = {
        "account_identifier": "9085",
        "transacted_at": "2026-09-26",
        "amount": "38.00",
        "currency": "CNY",
        "narration": "星巴克咖啡",
        "nature": "expense",
        "external_id": "ext_starbucks_001",
        "notes": "信用卡刷卡消费",
    }
    txn_res = client.post("/api/v1/transactions", json=txn_payload, headers=headers)
    assert txn_res.status_code == 200
    txn_data = txn_res.json()
    assert txn_data["status"] == "created"
    assert txn_data["amount"] == "38.00"


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
        "narration": "京东商城-图书音像",
        "transaction_type": "expense",
        "external_id": "jd_orig_150",
    }, headers=headers)

    # 2. 录入退款 50 元
    client.post("/api/v1/transactions", json={
        "account_identifier": "信用卡(9085)",
        "transacted_at": "2026-09-22",
        "amount": "50.00",
        "narration": "京东商城-图书音像退款",
        "nature": "refund",
        "external_id": "jd_refund_50",
    }, headers=headers)

    # 3. 验证退款是否关联成功
    txns = client.get("/api/v1/transactions", headers=headers).json()["items"]
    refund_txn = next(t for t in txns if t["external_id"] == "jd_refund_50")
    orig_txn = next(t for t in txns if t["external_id"] == "jd_orig_150")

    assert refund_txn["refund_of_transaction_id"] == orig_txn["id"]


def test_transaction_split(client):
    """测试单笔流水拆分为多个子分类，并校验金额一致性约束。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 录入一笔 100 元消费
    res = client.post("/api/v1/transactions", json={
        "account_identifier": "信用卡(9085)",
        "transacted_at": "2026-09-26",
        "amount": "100.00",
        "narration": "沃尔玛超市购物",
        "transaction_type": "expense",
        "external_id": "walmart_100",
    }, headers=headers)
    assert res.status_code == 200
    txn_id = res.json()["id"]

    # 2. 尝试不匹配的拆分（总和 90 != 100），预期报错 400
    bad_split = client.post(f"/api/v1/transactions/{txn_id}/split", json={
        "splits": [
            {"amount": "50.00", "notes": "零食"},
            {"amount": "40.00", "notes": "日用品"},
        ]
    }, headers=headers)
    assert bad_split.status_code == 400

    # 3. 正常拆分（30.00 + 70.00 == 100.00）
    good_split = client.post(f"/api/v1/transactions/{txn_id}/split", json={
        "splits": [
            {"amount": "30.00", "notes": "生鲜蔬果"},
            {"amount": "70.00", "notes": "家居厨具"},
        ]
    }, headers=headers)
    assert good_split.status_code == 200
    assert good_split.json()["is_split"] is True

    # 4. 获取拆分项并核实
    splits_res = client.get(f"/api/v1/transactions/{txn_id}/splits", headers=headers)
    assert splits_res.status_code == 200
    splits = splits_res.json()
    assert len(splits) == 2
    amounts = sorted([s["amount"] for s in splits])
    assert amounts == ["30.00", "70.00"]


def test_explicit_refund_matching_and_candidates(client):
    """测试新建退款时的候选消费搜索与显式关联原消费。"""
    headers = {"X-Api-Key": "dev-token"}

    # 1. 录入一笔消费：Apple Store 购买配件 699 元
    res_orig = client.post("/api/v1/transactions", json={
        "account_identifier": "招商信用卡(1234)",
        "transacted_at": "2026-09-25",
        "amount": "699.00",
        "name": "Apple Store 官方直营店消费",
        "category_name": "数码电器",
        "transaction_type": "expense",
        "external_id": "apple_orig_699",
    }, headers=headers)
    assert res_orig.status_code == 200
    orig_id = res_orig.json()["id"]

    # 2. 调用 /api/v1/refunds/candidates 接口检索候选消费
    res_candidates = client.get("/api/v1/refunds/candidates?search=Apple", headers=headers)
    assert res_candidates.status_code == 200
    cands = res_candidates.json()["candidates"]
    matched_cand = next((c for c in cands if c["id"] == orig_id), None)
    assert matched_cand is not None
    assert matched_cand["amount"] == "699.00"
    assert matched_cand["remaining_refundable"] == "699.00"
    assert matched_cand["category_name"] == "数码电器"

    # 3. 显式指定 refund_of_transaction_id 录入一笔退款 200 元 (名称故意不含 Apple，验证非启发式命中)
    res_refund = client.post("/api/v1/transactions", json={
        "account_identifier": "招商信用卡(1234)",
        "transacted_at": "2026-09-28",
        "amount": "200.00",
        "name": "银联在线退回资金款项",
        "transaction_type": "refund",
        "refund_of_transaction_id": orig_id,
        "external_id": "refund_unionpay_200",
    }, headers=headers)
    assert res_refund.status_code == 200
    refund_id = res_refund.json()["id"]

    # 4. 验证退款流水成功关联 orig_id，并且自动继承了原消费的分类
    txns = client.get("/api/v1/transactions", headers=headers).json()["items"]
    refund_txn = next(t for t in txns if t["id"] == refund_id)
    assert refund_txn["refund_of_transaction_id"] == orig_id
    assert refund_txn["category_name"] == "数码电器"

    # 5. 再次查询候选消费，剩余可退额度应已减为 499.00
    res_candidates_2 = client.get("/api/v1/refunds/candidates?search=Apple", headers=headers)
    cand_after = next(c for c in res_candidates_2.json()["candidates"] if c["id"] == orig_id)
    assert cand_after["already_allocated"] == "200.00"
    assert cand_after["remaining_refundable"] == "499.00"

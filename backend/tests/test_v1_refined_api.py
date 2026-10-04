import pytest
from starlette.testclient import TestClient
from database import get_session
from sqlmodel import Session, select
from models import Account, Transaction, Transfer

def test_refined_transaction_ingest(client: TestClient, service_family):
    headers = {"X-Api-Key": "dev-token"}

    # 1. 测试精炼参数日常消费录入（银行:尾号 + narration + occurred_at）
    payload_expense = {
        "account": "招商银行:6061",
        "narration": "星巴克咖啡（深业上城店）",
        "amount": "38.00",
        "currency": "CNY",
        "occurred_at": "2026-09-29T15:20:00+08:00",
        "transaction_type": "expense",
        "external_id": "test_refined_starbucks_01",
    }
    res = client.post("/api/v1/transactions", json=payload_expense, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["name"] == "星巴克咖啡（深业上城店）"
    assert data["amount"] == "38.00"

    # 2. 验证账户是否正确识别招商银行并建卡/绑定
    txns = client.get("/api/v1/transactions", headers=headers).json()["items"]
    starbucks_txn = next(t for t in txns if t["external_id"] == "test_refined_starbucks_01")
    assert starbucks_txn["narration"] == "星巴克咖啡（深业上城店）"
    assert "6061" in starbucks_txn["account_name"]

    # 3. 测试 UUID 直接作为 account 录入
    account_id = starbucks_txn["account_id"]
    payload_uuid = {
        "account": account_id,
        "narration": "全家便利店",
        "amount": "12.50",
        "occurred_at": "2026-09-29T16:00:00+08:00",
        "transaction_type": "expense",
        "external_id": "test_refined_family_02",
    }
    res_uuid = client.post("/api/v1/transactions", json=payload_uuid, headers=headers)
    assert res_uuid.status_code == 200
    uuid_data = res_uuid.json()
    assert uuid_data["account_id"] == account_id

    # 4. 测试信用卡还款转账（transaction_type: "transfer", tags: ["信用卡还款"]）
    payload_cc = {
        "account": "招商银行:6061",
        "narration": "招商银行信用卡还款",
        "amount": "2500.00",
        "occurred_at": "2026-09-29T10:00:00+08:00",
        "transaction_type": "transfer",
        "tags": ["信用卡还款"],
        "external_id": "test_refined_cc_payment_03",
    }
    res_cc = client.post("/api/v1/transactions", json=payload_cc, headers=headers)
    assert res_cc.status_code == 200
    cc_data = res_cc.json()
    assert cc_data["transaction_type"] == "transfer"

    # 5. 测试空格分隔入参：如 "招商银行 7931" 与 "中国银行 6888"
    payload_space_1 = {
        "account": "招商银行 7931",
        "narration": "午餐便当",
        "amount": "25.00",
        "occurred_at": "2026-09-29T12:30:00+08:00",
        "transaction_type": "expense",
        "external_id": "test_refined_space_cmb_7931",
    }
    res_space_1 = client.post("/api/v1/transactions", json=payload_space_1, headers=headers)
    assert res_space_1.status_code == 200, res_space_1.text

    payload_space_2 = {
        "account": "中国银行 6888",
        "narration": "中行存款结息",
        "amount": "150.00",
        "occurred_at": "2026-09-29T09:00:00+08:00",
        "transaction_type": "income",
        "external_id": "test_refined_space_boc_6888",
    }
    res_space_2 = client.post("/api/v1/transactions", json=payload_space_2, headers=headers)
    assert res_space_2.status_code == 200, res_space_2.text

    all_items = client.get("/api/v1/transactions", headers=headers).json()["items"]
    t1 = next(t for t in all_items if t["external_id"] == "test_refined_space_cmb_7931")
    assert "7931" in t1["account_name"]
    t2 = next(t for t in all_items if t["external_id"] == "test_refined_space_boc_6888")
    assert "6888" in t2["account_name"]

"""Account balances must agree across writes, reads, and repeated refreshes."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import select

from models import Account, Transaction, User


def _create(client, account_type="checking", balance="1000"):
    response = client.post("/api/v1/accounts", json={
        "name": "余额回归测试", "account_type": account_type, "balance": balance,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _assert_balance(client, account_id, expected, period="MTD"):
    listed = client.get("/api/v1/accounts")
    assert listed.status_code == 200
    row = next(a for a in listed.json()["items"] if a["id"] == str(account_id))
    detail = client.get(f"/api/v1/accounts/{account_id}?period={period}")
    assert detail.status_code == 200
    assert Decimal(row["balance"]) == Decimal(expected)
    assert Decimal(detail.json()["account"]["balance"]) == Decimal(expected)
    assert Decimal(str(detail.json()["metrics"]["balance"])) == Decimal(expected)


def _activity(db, account_id, kind, amount, narration="日常活动", when=None):
    txn = Transaction(
        account_id=uuid.UUID(str(account_id)), transacted_at=when or date.today(),
        amount=Decimal(amount), currency="CNY", transaction_type=kind,
        narration=narration,
    )
    db.add(txn)
    db.commit()
    return txn


@pytest.mark.parametrize("account_type,expected", [("checking", "895.25"), ("credit_card", "1104.75")])
def test_refresh_uses_all_history_without_writing_balance(auth_client_a, db, account_type, expected):
    created = _create(auth_client_a, account_type)
    account_id = uuid.UUID(created["id"])
    _activity(db, account_id, "expense", "125.25", when=date(2019, 1, 1))
    _activity(db, account_id, "refund", "20.50")
    before = db.get(Account, account_id).model_dump()
    before_txns = len(db.exec(select(Transaction).where(Transaction.account_id == account_id)).all())
    for period in ("MTD", "1M", "ALL", "MTD"):
        _assert_balance(auth_client_a, account_id, expected, period)
    db.refresh(db.get(Account, account_id))
    assert db.get(Account, account_id).model_dump() == before
    assert len(db.exec(select(Transaction).where(Transaction.account_id == account_id)).all()) == before_txns


def test_metadata_edit_returns_current_balance_without_new_activity(auth_client_a, db):
    created = _create(auth_client_a)
    account_id = uuid.UUID(created["id"])
    _activity(db, account_id, "expense", "100")
    response = auth_client_a.patch(f"/api/v1/accounts/{account_id}", json={"name": "改名称"})
    assert response.status_code == 200
    assert Decimal(response.json()["account"]["balance"]) == Decimal("900")
    _assert_balance(auth_client_a, account_id, "900")
    assert len(db.exec(select(Transaction).where(Transaction.account_id == account_id)).all()) == 2
    assert db.get(Account, account_id).balance == Decimal("1000")


@pytest.mark.parametrize("account_type", ["checking", "credit_card"])
def test_explicit_balance_edit_is_one_adjustment_and_is_stable(auth_client_a, db, account_type):
    created = _create(auth_client_a, account_type)
    account_id = uuid.UUID(created["id"])
    _activity(db, account_id, "expense", "100")
    for _ in range(2):
        response = auth_client_a.patch(f"/api/v1/accounts/{account_id}", json={"balance": "800"})
        assert response.status_code == 200
        assert Decimal(response.json()["account"]["balance"]) == Decimal("800")
        _assert_balance(auth_client_a, account_id, "800")
    adjustments = db.exec(select(Transaction).where(
        Transaction.account_id == account_id, Transaction.transaction_type == "adjustment",
    )).all()
    assert len(adjustments) == 1
    assert adjustments[0].excluded_from_stats is True
    assert db.get(Account, account_id).balance == Decimal("1000")


@pytest.mark.parametrize("account_type", ["checking", "credit_card"])
def test_balance_tracks_activity_edit_and_delete(auth_client_a, db, account_type):
    created = _create(auth_client_a, account_type)
    txn = _activity(db, created["id"], "expense", "100")
    expense_sign = -1 if account_type == "checking" else 1
    _assert_balance(auth_client_a, created["id"], str(1000 + expense_sign * 100))
    response = auth_client_a.patch(f"/api/v1/transactions/{txn.id}", json={"amount": "150"})
    assert response.status_code == 200, response.text
    _assert_balance(auth_client_a, created["id"], str(1000 + expense_sign * 150))
    response = auth_client_a.delete(f"/api/v1/transactions/{txn.id}")
    assert response.status_code == 200, response.text
    _assert_balance(auth_client_a, created["id"], "1000")


@pytest.mark.parametrize("account_type", ["checking", "credit_card"])
@pytest.mark.parametrize("reason", ["adjustment", "transfer", "income"])
def test_new_balance_preserves_empty_legacy_opening(auth_client_a, db, account_type, reason):
    # Historical accounts can have an opening amount without an opening transaction.
    _create(auth_client_a, balance="0")
    user = db.exec(select(User).where(User.username == "alice")).one()
    account = Account(
        name="旧账户", family_id=user.family_id, owner_id=user.id,
        account_type=account_type, classification="liability" if account_type == "credit_card" else "asset",
        balance=Decimal("1000"),
    )
    db.add(account)
    db.commit()
    target = "800" if account_type == "credit_card" else "1200"
    for _ in range(2):
        response = auth_client_a.post(f"/api/v1/accounts/{account.id}/reconcile-balance", json={
            "new_balance": target, "reconciliation_type": reason,
        })
        assert response.status_code == 200, response.text
        assert Decimal(response.json()["new_balance"]) == Decimal(target)
        _assert_balance(auth_client_a, account.id, target)
    assert len(db.exec(select(Transaction).where(Transaction.account_id == account.id)).all()) == 2


@pytest.mark.parametrize("account_type", ["checking", "credit_card"])
def test_negative_opening_is_recorded_and_survives_first_expense(auth_client_a, db, account_type):
    created = _create(auth_client_a, account_type, balance="-100")
    _assert_balance(auth_client_a, created["id"], "-100")
    _activity(db, created["id"], "expense", "20")
    _assert_balance(auth_client_a, created["id"], "-120" if account_type == "checking" else "-80")


def test_regular_income_keywords_do_not_erase_opening(auth_client_a, db):
    created = _create(auth_client_a, balance="1000")
    _activity(db, created["id"], "refund", "100", narration="学期初退回押金，初始申请已结清")
    _assert_balance(auth_client_a, created["id"], "1100")


@pytest.mark.parametrize("reason", ["", "expense"])
def test_new_balance_rejects_invalid_or_opposite_direction_without_changes(auth_client_a, db, reason):
    created = _create(auth_client_a)
    account_id = uuid.UUID(created["id"])
    response = auth_client_a.post(f"/api/v1/accounts/{account_id}/reconcile-balance", json={
        "new_balance": "1200", "reconciliation_type": reason,
    })
    assert response.status_code == 400
    _assert_balance(auth_client_a, account_id, "1000")
    assert len(db.exec(select(Transaction).where(Transaction.account_id == account_id)).all()) == 1


@pytest.mark.parametrize("cat_input", [None, "valid-id", "invalid-category"])
def test_reconcile_balance_category_resilience(auth_client_a, db, cat_input):
    """Use persisted category IDs; reject unknown categories without changing money."""
    created = _create(auth_client_a, "checking", "1000")
    account_id = uuid.UUID(created["id"])
    payload = {
        "new_balance": "800",
        "reconciliation_type": "expense",
        "name": "测试容错变动",
    }
    if cat_input == "valid-id":
        from models import Category
        category = Category(family_id=db.get(Account, account_id).family_id, name='Custom category')
        db.add(category); db.commit()
        payload["category_id"] = str(category.id)
    elif cat_input is not None:
        payload["category_id"] = cat_input

    resp = auth_client_a.post(f"/api/v1/accounts/{account_id}/reconcile-balance", json=payload)
    if cat_input == "invalid-category":
        assert resp.status_code == 400
        _assert_balance(auth_client_a, account_id, "1000")
        return
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["new_balance"]) == Decimal("800")
    _assert_balance(auth_client_a, account_id, "800")

    # 验证生成的对账交易记录存在且金额正确
    txns = db.exec(select(Transaction).where(Transaction.account_id == account_id)).all()
    expense_tx = [t for t in txns if t.transaction_type == "expense"]
    assert len(expense_tx) == 1
    assert expense_tx[0].amount == Decimal("200")

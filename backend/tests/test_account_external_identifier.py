"""External identifiers survive metadata edits and unambiguously route bank imports."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from models import Account, AccountShare, Transaction, User


def _create(client, **fields):
    response = client.post("/api/v1/accounts", json={
        "name": "日常消费卡", "institution_name": "招商银行", "account_type": "credit_card",
        "currency": "CNY", "balance": "0", **fields,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _post(client, identifier):
    return client.post("/api/v1/transactions", json={
        "account": identifier, "narration": "外部标识导入测试", "amount": "10", "currency": "CNY",
        "occurred_at": datetime.now(timezone.utc).isoformat(), "transaction_type": "expense",
        "external_id": str(uuid.uuid4()),
    })


def _assert_views(client, account_id, expected):
    listed = client.get("/api/v1/accounts")
    assert listed.status_code == 200
    assert next(a for a in listed.json()["items"] if a["id"] == account_id)["external_identifier"] == expected
    detail = client.get(f"/api/v1/accounts/{account_id}")
    assert detail.status_code == 200
    assert detail.json()["account"]["external_identifier"] == expected
    shares = client.get(f"/api/v1/accounts/{account_id}/shares")
    assert shares.status_code == 200
    assert shares.json()["external_identifier"] == expected
    matrix = client.get("/api/v1/accounts/shares/matrix")
    assert matrix.status_code == 200
    assert next(a for a in matrix.json()["accounts"] if a["account_id"] == account_id)["external_identifier"] == expected


def test_edit_identifier_is_persisted_in_all_edit_entry_points(auth_client_a, db):
    created = _create(auth_client_a)
    account_id = created["id"]
    response = auth_client_a.patch(f"/api/v1/accounts/{account_id}", json={"external_identifier": " 0007 "})
    assert response.status_code == 200, response.text
    assert response.json()["account"]["external_identifier"] == "0007"
    _assert_views(auth_client_a, account_id, "0007")
    assert db.exec(select(Transaction).where(Transaction.account_id == uuid.UUID(account_id))).all() == []
    renamed = auth_client_a.patch(f"/api/v1/accounts/{account_id}", json={"name": "任意别名"})
    assert renamed.status_code == 200
    assert renamed.json()["account"]["external_identifier"] == "0007"
    _assert_views(auth_client_a, account_id, "0007")
    imported = _post(auth_client_a, "招商银行信用卡:0007")
    assert imported.status_code == 200, imported.text
    assert imported.json()["account_id"] == account_id


@pytest.mark.parametrize("value", [None, "", "   "])
def test_identifier_can_be_cleared_without_changing_other_metadata(auth_client_a, value):
    created = _create(auth_client_a, external_identifier="1234")
    response = auth_client_a.patch(f"/api/v1/accounts/{created['id']}", json={"external_identifier": value})
    assert response.status_code == 200
    assert response.json()["account"]["external_identifier"] is None
    assert response.json()["account"]["name"] == created["name"]
    _assert_views(auth_client_a, created["id"], None)


def test_identifier_length_is_validated_and_omission_preserves_it(auth_client_a):
    created = _create(auth_client_a, external_identifier="x" * 100)
    response = auth_client_a.patch(f"/api/v1/accounts/{created['id']}", json={"external_identifier": "x" * 101})
    assert response.status_code == 422
    _assert_views(auth_client_a, created["id"], "x" * 100)
    response = auth_client_a.patch(f"/api/v1/accounts/{created['id']}", json={"name": "改名"})
    assert response.status_code == 200
    assert response.json()["account"]["external_identifier"] == "x" * 100


@pytest.mark.parametrize("permission,allowed", [("read_only", False), ("read_write", False), ("full_control", True)])
def test_shared_identifier_edit_requires_full_control(auth_client_a, auth_client_b, db, permission, allowed):
    created = _create(auth_client_a, external_identifier="1234")
    alice = db.exec(select(User).where(User.username == "alice")).one()
    bob = db.exec(select(User).where(User.username == "bob")).one()
    bob.family_id, bob.role = alice.family_id, "member"
    db.add(bob)
    db.add(AccountShare(account_id=uuid.UUID(created["id"]), user_id=bob.id, permission=permission))
    db.commit()
    response = auth_client_b.patch(f"/api/v1/accounts/{created['id']}", json={"external_identifier": "5678"})
    assert response.status_code == (200 if allowed else 403), response.text
    _assert_views(auth_client_a, created["id"], "5678" if allowed else "1234")


def test_exact_identifier_wins_over_names(auth_client_a):
    _create(auth_client_a, name="招行信用卡 1234")
    _create(auth_client_a, name="招商银行信用卡:1234")
    exact = _create(auth_client_a, name="无尾号别名", external_identifier="1234")
    response = _post(auth_client_a, "招商银行信用卡:1234")
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == exact["id"]


@pytest.mark.parametrize("kind", ["credit_card", "checking"])
def test_same_suffix_is_disambiguated_by_bank_and_card_type(auth_client_a, kind):
    _create(auth_client_a, name="招商银行信用卡 1234", institution_name="中国银行", account_type=kind, external_identifier="1234")
    credit = _create(auth_client_a, account_type="credit_card", external_identifier="1234")
    debit = _create(auth_client_a, account_type="checking", external_identifier="1234")
    bank = "招商银行信用卡" if kind == "credit_card" else "招商银行借记卡"
    response = _post(auth_client_a, f"{bank}:1234")
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == (credit if kind == "credit_card" else debit)["id"]


@pytest.mark.parametrize("configured", [True, False])
def test_ambiguous_identifiers_fail_without_creating_transactions(auth_client_a, db, configured):
    for _ in range(2):
        _create(auth_client_a, name="信用卡 1234", external_identifier="1234" if configured else None)
    response = _post(auth_client_a, "招商银行信用卡:1234")
    assert response.status_code == 409, response.text
    assert len(db.exec(select(Account)).all()) == 2
    assert db.exec(select(Transaction)).all() == []


def test_configured_identifier_cannot_match_by_substring_or_old_name(auth_client_a):
    wrong = _create(auth_client_a, name="信用卡 1234", external_identifier="91234")
    response = _post(auth_client_a, "招商银行信用卡:1234")
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] != wrong["id"]
    new = auth_client_a.get(f"/api/v1/accounts/{response.json()['account_id']}").json()["account"]
    assert new["external_identifier"] == "招商银行信用卡:1234"
    assert new["classification"] == "liability"


def test_legacy_name_suffix_does_not_match_part_of_a_longer_number(auth_client_a):
    wrong = _create(auth_client_a, name="信用卡 91234")
    expected = _create(auth_client_a, name="信用卡 1234")
    response = _post(auth_client_a, "招商银行信用卡:1234")
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == expected["id"] != wrong["id"]


def test_bank_import_never_matches_another_family(auth_client_a, auth_client_b):
    other = _create(auth_client_b, external_identifier="1234")
    expected = _create(auth_client_a, external_identifier="1234")
    response = _post(auth_client_a, "招商银行信用卡:1234")
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == expected["id"] != other["id"]


def test_uuid_selection_is_unaffected_by_duplicate_external_identifiers(auth_client_a):
    _create(auth_client_a, external_identifier="1234")
    expected = _create(auth_client_a, external_identifier="1234")
    response = _post(auth_client_a, expected["id"])
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == expected["id"]


def test_exact_legacy_name_can_contain_spaces(auth_client_a):
    expected = _create(auth_client_a, name="我的 日常消费卡")
    response = _post(auth_client_a, expected["name"])
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == expected["id"]


def test_bank_name_does_not_determine_card_type(auth_client_a):
    expected = _create(auth_client_a, institution_name="Credit Suisse", account_type="checking", external_identifier="1234")
    response = _post(auth_client_a, "Credit Suisse:1234")
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == expected["id"]


@pytest.mark.parametrize("selector,kind,classification", [
    ("招商银行借记卡:2238", "checking", "asset"),
    ("招商银行信用卡:0007", "credit_card", "liability"),
])
def test_empty_ledger_preserves_full_selector_and_reuses_account_after_rename(
    auth_client_a, db, selector, kind, classification,
):
    assert db.exec(select(Account)).all() == []
    first = _post(auth_client_a, selector)
    assert first.status_code == 200, first.text
    account_id = first.json()["account_id"]
    _assert_views(auth_client_a, account_id, selector)
    account = db.get(Account, uuid.UUID(account_id))
    assert account.account_type == kind
    assert account.classification == classification
    assert account.institution_name == "招商银行"
    assert account.name == f"招商银行 {selector.rsplit(':', 1)[1]}"
    renamed = auth_client_a.patch(f"/api/v1/accounts/{account_id}", json={
        "name": "我的卡片别名", "institution_name": "自定义机构名称",
    })
    assert renamed.status_code == 200, renamed.text
    second = _post(auth_client_a, selector)
    assert second.status_code == 200, second.text
    assert second.json()["account_id"] == account_id
    assert len(db.exec(select(Account)).all()) == 1
    assert len(db.exec(select(Transaction)).all()) == 2


def test_full_identifier_wins_over_suffix_only_identifiers(auth_client_a):
    _create(auth_client_a, external_identifier="1234")
    _create(auth_client_a, external_identifier="1234")
    expected = _create(auth_client_a, external_identifier="招商银行信用卡:1234")
    response = _post(auth_client_a, "招商银行信用卡:1234")
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == expected["id"]


def test_duplicate_full_identifiers_reject_instead_of_using_bank_metadata(auth_client_a, db):
    for bank in ("招商银行", "中国银行"):
        _create(auth_client_a, institution_name=bank, external_identifier="招商银行信用卡:1234")
    response = _post(auth_client_a, "招商银行信用卡:1234")
    assert response.status_code == 409, response.text
    assert db.exec(select(Transaction)).all() == []


def test_full_identifier_never_routes_to_other_family(auth_client_a, auth_client_b):
    other = _create(auth_client_b, external_identifier="招商银行信用卡:1234")
    response = _post(auth_client_a, "招商银行信用卡:1234")
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] != other["id"]
    _assert_views(auth_client_a, response.json()["account_id"], "招商银行信用卡:1234")


def test_auto_created_identifier_rejects_oversized_source_without_partial_writes(auth_client_a, db):
    response = _post(auth_client_a, "x" * 101)
    assert response.status_code == 422, response.text
    assert db.exec(select(Account)).all() == []
    assert db.exec(select(Transaction)).all() == []


@pytest.mark.parametrize("selector,bank,kind", [
    ("中国银行借记卡:2238", "中国银行", "checking"),
    ("工商银行信用卡:2238", "工商银行", "credit_card"),
    ("Example Bank CREDIT_CARD:0007", "Example Bank", "credit_card"),
    ("Credit Suisse DEBIT_CARD:0007", "Credit Suisse", "checking"),
])
def test_auto_created_institution_contains_only_bank(auth_client_a, db, selector, bank, kind):
    response = _post(auth_client_a, selector)
    assert response.status_code == 200, response.text
    account = db.get(Account, uuid.UUID(response.json()["account_id"]))
    assert account.institution_name == bank
    assert account.account_type == kind
    assert account.external_identifier == selector
    assert account.name == f"{bank} {selector.rsplit(':', 1)[1]}"

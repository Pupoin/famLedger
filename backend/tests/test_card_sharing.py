"""Sharing is a prerequisite for linking cards, never a side effect of linking."""

from datetime import date
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import update
from sqlmodel import select

from models import Account, AccountShare, Family, Transaction, User
from services.card_sharing import detach_unshared_cards


@pytest.fixture
def cards(db):
    alice = db.exec(select(User).where(User.username == "alice")).one()
    bob = db.exec(select(User).where(User.username == "bob")).one()
    family = Family(name="Card sharing")
    db.add(family)
    db.flush()
    alice.family_id = bob.family_id = family.id
    carol = User(username="carol", display_name="Carol", family_id=family.id)
    db.add_all([alice, bob, carol])
    db.flush()
    parent = Account(name="Primary", family_id=family.id, owner_id=alice.id,
                     account_type="credit_card", classification="liability")
    child = Account(name="Supplementary", family_id=family.id, owner_id=bob.id,
                    account_type="credit_card", classification="liability")
    db.add_all([parent, child])
    db.flush()
    # Bob can manage the primary card, allowing him to link his own card.
    db.add(AccountShare(account_id=parent.id, user_id=bob.id, permission="full_control"))
    txn = Transaction(account_id=child.id, amount=Decimal("123"), transacted_at=date.today(),
                      narration="Supplementary purchase")
    db.add(txn)
    db.commit()
    return alice, bob, carol, parent, child, txn


def set_share(client, card, user, shared=True, permission="read_only", include=True):
    return client.patch(f"/api/v1/accounts/{card.id}/shares", json={"members": [{
        "user_id": str(user.id), "shared": shared, "permission": permission,
        "include_in_finances": include,
    }]})


def link(client, parent, child):
    return client.patch(f"/api/v1/accounts/{child.id}", json={"parent_account_id": str(parent.id)})


def test_unshared_card_cannot_be_linked_and_does_not_grant_access(auth_client_a, auth_client_b, db, cards):
    alice, _, _, parent, child, txn = cards
    response = link(auth_client_b, parent, child)
    assert response.status_code == 400
    assert "先" in response.json()["detail"] and "共享" in response.json()["detail"]
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id is None
    assert db.exec(select(AccountShare).where(AccountShare.account_id == child.id)).all() == []
    assert auth_client_a.get(f"/api/v1/transactions/{txn.id}").status_code == 403


def test_share_first_then_link_provides_read_only_access_and_consistent_balances(auth_client_a, auth_client_b, db, cards):
    alice, _, _, parent, child, txn = cards
    assert set_share(auth_client_b, child, alice).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    for _ in range(2):
        rows = auth_client_a.get("/api/v1/accounts").json()["items"]
        assert Decimal(next(row["balance"] for row in rows if row["id"] == str(parent.id))) == 123
        detail = auth_client_a.get(f"/api/v1/accounts/{parent.id}")
        assert detail.status_code == 200
        assert Decimal(detail.json()["account"]["balance"]) == 123
        activity = auth_client_a.get("/api/v1/transactions", params={"account_id": str(parent.id)})
        assert activity.status_code == 200 and str(txn.id) in activity.text
        dashboard = auth_client_a.get("/api/v1/dashboard/summary").json()["balance_sheet"]
        assert dashboard["total_liabilities"] == 123
        groups = dashboard["by_type"]["liabilities"]["groups"]
        assert sum(group["total"] for group in groups) == 123
        assert auth_client_a.get(f"/api/v1/transactions/{txn.id}").status_code == 200
    assert auth_client_a.patch(f"/api/v1/transactions/{txn.id}", json={"amount": "500"}).status_code == 403
    assert auth_client_a.delete(f"/api/v1/transactions/{txn.id}").status_code == 403
    db.expire_all()
    share = db.exec(select(AccountShare).where(AccountShare.account_id == child.id)).one()
    assert share.permission == "read_only"


def test_primary_balance_sums_own_and_multiple_supplementary_net_activity(auth_client_a, auth_client_b, db, cards):
    alice, _, _, parent, child, _ = cards
    assert set_share(auth_client_b, child, alice).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    second_child = Account(name="Second supplementary", family_id=parent.family_id, owner_id=alice.id,
                           account_type="credit_card", classification="liability", parent_account_id=parent.id)
    db.add(second_child)
    db.flush()
    db.add_all([
        Transaction(account_id=parent.id, transaction_type="expense", amount=Decimal("200"),
                    transacted_at=date(2019, 1, 1), narration="Primary purchase"),
        Transaction(account_id=parent.id, transaction_type="transfer", amount=Decimal("100"),
                    transacted_at=date.today(), narration="Primary repayment", extra={"direction": "inflow"}),
        Transaction(account_id=child.id, transaction_type="refund", amount=Decimal("23"),
                    transacted_at=date.today(), narration="Supplementary refund"),
        Transaction(account_id=second_child.id, transaction_type="expense", amount=Decimal("67"),
                    transacted_at=date.today(), narration="Second supplementary purchase"),
    ])
    db.commit()
    # Primary: 200 - 100 = 100; first supplementary: 123 - 23 = 100; second: 67.
    for period in ("MTD", "ALL", "MTD"):
        listed = auth_client_a.get("/api/v1/accounts").json()["accounts"]
        balances = {a["id"]: Decimal(a["balance"]) for a in listed}
        assert balances[str(parent.id)] == Decimal("267")
        assert balances[str(child.id)] == Decimal("100")
        assert balances[str(second_child.id)] == Decimal("67")
        detail = auth_client_a.get(f"/api/v1/accounts/{parent.id}", params={"period": period}).json()
        assert Decimal(detail["account"]["balance"]) == Decimal("267")
        assert Decimal(str(detail["metrics"]["balance"])) == Decimal("267")
        assert auth_client_a.get("/api/v1/dashboard/summary").json()["balance_sheet"]["total_liabilities"] == 267
    # A recipient of the primary cannot infer a second private supplementary card's balance.
    recipient_detail = auth_client_b.get(f"/api/v1/accounts/{parent.id}").json()["account"]
    assert Decimal(recipient_detail["balance"]) == Decimal("200")
    assert auth_client_b.get(f"/api/v1/accounts/{second_child.id}").status_code == 403


def test_recipient_links_own_private_primary_and_original_owner_sees_relationship(auth_client_a, auth_client_b, db, cards):
    alice, bob, _, parent, child, _ = cards
    assert set_share(auth_client_a, parent, bob, shared=False).status_code == 200
    assert set_share(auth_client_b, child, alice, permission="full_control").status_code == 200
    assert link(auth_client_a, parent, child).status_code == 200

    listed = auth_client_b.get("/api/v1/accounts").json()["accounts"]
    assert str(parent.id) not in {a["id"] for a in listed}
    detail = auth_client_b.get(f"/api/v1/accounts/{child.id}").json()["account"]
    shares = auth_client_b.get(f"/api/v1/accounts/{child.id}/shares").json()
    matrix = auth_client_b.get("/api/v1/accounts/shares/matrix").json()["accounts"]
    expected = {"id": str(parent.id), "name": parent.name, "account_type": "credit_card", "currency": parent.currency,
                "owner_id": str(alice.id), "owner": alice.display_name or alice.username}
    for record in (next(a for a in listed if a["id"] == str(child.id)), detail, shares,
                   next(a for a in matrix if a["account_id"] == str(child.id))):
        assert record["parent_account_id"] == str(parent.id)
        assert record["parent_account"] == expected
    assert auth_client_b.get(f"/api/v1/accounts/{parent.id}").status_code == 403

    # Saving ordinary metadata with the unchanged parent must not require control of that parent.
    response = auth_client_b.patch(f"/api/v1/accounts/{child.id}", json={
        "name": "Owner renamed supplementary", "parent_account_id": str(parent.id),
    })
    assert response.status_code == 200
    assert response.json()["account"]["parent_account"] == expected
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id == parent.id
    assert db.exec(select(AccountShare).where(
        AccountShare.account_id == parent.id, AccountShare.user_id == bob.id)).first() is None
    assert auth_client_b.get(f"/api/v1/accounts/{parent.id}").status_code == 403

    # Displaying one existing link must not authorize linking to another private primary card.
    other_parent = Account(name="Other private primary", family_id=parent.family_id, owner_id=alice.id,
                           account_type="credit_card", classification="liability")
    db.add(other_parent)
    db.commit()
    assert link(auth_client_b, other_parent, child).status_code == 403
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id == parent.id


def test_cancel_primary_owner_share_unlinks_without_deleting_activity(auth_client_a, auth_client_b, db, cards):
    alice, _, _, parent, child, txn = cards
    assert set_share(auth_client_b, child, alice).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    response = set_share(auth_client_b, child, alice, shared=False)
    assert response.status_code == 200 and response.json()["unlinked_from_parent"] is True
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id is None
    assert db.get(Transaction, txn.id).amount == 123
    assert auth_client_a.get(f"/api/v1/accounts/{child.id}").status_code == 403
    assert auth_client_a.get(f"/api/v1/transactions/{txn.id}").status_code == 403
    assert auth_client_a.get("/api/v1/dashboard/summary").json()["balance_sheet"]["total_liabilities"] == 0
    assert auth_client_b.get(f"/api/v1/transactions/{txn.id}").status_code == 200


def test_unrelated_share_cannot_satisfy_primary_owner_access(auth_client_b, db, cards):
    _, _, carol, parent, child, _ = cards
    assert set_share(auth_client_b, child, carol).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 400
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id is None


@pytest.mark.parametrize("permission", ["read_only", "read_write", "full_control"])
def test_changing_permission_or_finance_inclusion_keeps_link(auth_client_b, db, cards, permission):
    alice, _, _, parent, child, _ = cards
    assert set_share(auth_client_b, child, alice).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    assert set_share(auth_client_b, child, alice, permission=permission, include=False).status_code == 200
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id == parent.id


def test_cancelling_another_members_share_keeps_link(auth_client_b, db, cards):
    alice, _, carol, parent, child, _ = cards
    assert set_share(auth_client_b, child, alice).status_code == 200
    assert set_share(auth_client_b, child, carol).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    response = set_share(auth_client_b, child, carol, shared=False)
    assert response.status_code == 200 and response.json()["unlinked_from_parent"] is False
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id == parent.id


def test_failed_share_change_rolls_back_unlink_and_revocation(auth_client_b, db, cards):
    alice, _, _, parent, child, _ = cards
    assert set_share(auth_client_b, child, alice).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    outsider = User(username="outsider", display_name="Other family")
    db.add(outsider)
    db.commit()
    response = auth_client_b.patch(f"/api/v1/accounts/{child.id}/shares", json={"members": [
        {"user_id": str(alice.id), "shared": False},
        {"user_id": str(outsider.id), "shared": True},
    ]})
    assert response.status_code == 400
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id == parent.id
    assert db.exec(select(AccountShare).where(AccountShare.account_id == child.id,
                                            AccountShare.user_id == alice.id)).first() is not None


@pytest.mark.parametrize("shared_with_new_owner", [False, True])
def test_primary_ownership_transfer_rechecks_child_sharing(auth_client_a, auth_client_b, db, cards, shared_with_new_owner):
    alice, _, carol, parent, child, _ = cards
    assert set_share(auth_client_b, child, alice).status_code == 200
    if shared_with_new_owner:
        assert set_share(auth_client_b, child, carol).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    response = auth_client_a.post(f"/api/v1/accounts/{parent.id}/transfer-ownership",
                                  json={"new_owner_id": str(carol.id)})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Account, child.id).parent_account_id == (parent.id if shared_with_new_owner else None)


def test_repair_detaches_legacy_unshared_link_without_granting_or_deleting(db, cards):
    _, _, _, parent, child, txn = cards
    # Simulate a link written by an older build, bypassing current ORM guards.
    db.execute(update(Account).where(Account.id == child.id).values(parent_account_id=parent.id))
    db.commit()
    db.expire_all()
    assert detach_unshared_cards(db) == [child.id]
    db.commit()
    assert db.get(Account, child.id).parent_account_id is None
    assert db.get(Transaction, txn.id).amount == 123
    assert db.exec(select(AccountShare).where(AccountShare.account_id == child.id)).all() == []


def test_same_owner_can_link_without_redundant_self_share(auth_client_a, db, cards):
    _, _, _, parent, _, _ = cards
    response = auth_client_a.post("/api/v1/accounts", json={
        "name": "My supplementary", "account_type": "credit_card", "parent_account_id": str(parent.id),
    })
    assert response.status_code == 200
    assert response.json()["parent_account_id"] == str(parent.id)
    assert db.exec(select(AccountShare).where(AccountShare.account_id == uuid.UUID(response.json()["id"]))).all() == []


def test_primary_shared_viewer_cannot_read_unshared_child(auth_client_a, auth_client_b, db, cards):
    alice, _, carol, parent, child, txn = cards
    assert set_share(auth_client_b, child, alice).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    assert set_share(auth_client_a, parent, carol).status_code == 200
    from routes.v1_dashboard import get_dashboard_summary
    from starlette.requests import Request
    from services.stats_engine import get_user_visible_account_ids
    visible = get_user_visible_account_ids(db, carol, carol.family_id)
    assert parent.id in visible and child.id not in visible
    result = get_dashboard_summary(Request({"type": "http"}), period="monthly", selected_month=None,
        start_date=None, end_date=None, account_id=None, user_filter=None, session=db, user_or_ctx="carol")
    assert result["balance_sheet"]["total_liabilities"] == 0


def test_family_move_keeps_same_owner_links_across_intermediate_flushes(auth_client_a, db, cards):
    alice, _, _, parent, _, _ = cards
    response = auth_client_a.post("/api/v1/accounts", json={
        "name": "My supplementary", "account_type": "credit_card", "parent_account_id": str(parent.id),
    })
    assert response.status_code == 200
    child_id = uuid.UUID(response.json()["id"])
    family = Family(name="New family")
    db.add(family)
    db.flush()
    alice.family_id = family.id
    db.add(alice)
    db.flush()
    parent.family_id = family.id
    db.add(parent)
    db.flush()
    child = db.get(Account, child_id)
    child.family_id = family.id
    db.add(child)
    db.commit()
    assert db.get(Account, child_id).parent_account_id == parent.id


@pytest.mark.parametrize("role", ["member", "admin"])
@pytest.mark.parametrize("permission", ["read_only", "read_write"])
@pytest.mark.parametrize("method", ["PATCH", "PUT"])
def test_shared_recipient_cannot_change_account_information(auth_client_a, auth_client_b, db, cards, role, permission, method):
    alice, _, _, parent, child, txn = cards
    alice.role = role
    db.add(alice)
    db.commit()
    assert set_share(auth_client_b, child, alice, permission=permission).status_code == 200
    assert link(auth_client_b, parent, child).status_code == 200
    db.expire_all()
    before = db.get(Account, child.id).model_dump()
    activity_before = db.get(Transaction, txn.id).model_dump()
    response = auth_client_a.request(method, f"/api/v1/accounts/{child.id}", json={
        "name": "unauthorized rename", "institution_name": "another bank", "account_type": "checking",
        "currency": "USD", "balance": "999", "color": "red", "icon": "other",
        "is_archived": True, "parent_account_id": "",
    })
    assert response.status_code == 403
    db.expire_all()
    assert db.get(Account, child.id).model_dump() == before
    assert db.get(Transaction, txn.id).model_dump() == activity_before
    for account in (
        next(row for row in auth_client_a.get("/api/v1/accounts").json()["items"] if row["id"] == str(child.id)),
        auth_client_a.get(f"/api/v1/accounts/{child.id}").json()["account"],
    ):
        assert account["can_manage"] is False
        assert account["can_edit"] == (permission == "read_write")
    assert auth_client_a.get(f"/api/v1/accounts/{child.id}/shares").json()["can_manage"] is False


@pytest.mark.parametrize("role", ["member", "admin"])
def test_read_only_recipient_cannot_write_or_escalate_via_other_endpoints(auth_client_a, auth_client_b, db, cards, role):
    alice, bob, _, parent, child, txn = cards
    alice.role = role
    db.add(alice)
    db.commit()
    assert set_share(auth_client_b, child, alice).status_code == 200
    assert auth_client_a.delete(f"/api/v1/accounts/{child.id}").status_code == 403
    assert auth_client_a.post(f"/api/v1/accounts/{child.id}/transfer-ownership",
                              json={"new_owner_id": str(bob.id)}).status_code == 403
    assert set_share(auth_client_a, child, alice, permission="full_control").status_code == 403
    assert auth_client_a.post(f"/api/v1/accounts/{child.id}/reconcile-balance",
                              json={"new_balance": "900", "reconciliation_type": "adjustment"}).status_code == 403
    assert auth_client_a.patch(f"/api/v1/transactions/{txn.id}", json={"amount": "900"}).status_code == 403
    assert auth_client_a.delete(f"/api/v1/transactions/{txn.id}").status_code == 403
    assert auth_client_a.get(f"/api/v1/transactions/{txn.id}").status_code == 200
    from services.stats_engine import get_user_writable_account_ids
    assert child.id not in get_user_writable_account_ids(db, alice, alice.family_id)
    assert auth_client_a.post("/api/v1/transfers", json={
        "from_account_id": str(child.id), "to_account_id": str(parent.id),
        "amount": "10", "currency": "CNY",
    }).status_code == 403
    refund = Transaction(account_id=child.id, amount=Decimal("10"), transacted_at=date.today(),
                         narration="Refund", transaction_type="refund")
    db.add(refund)
    db.commit()
    assert auth_client_a.post(f"/api/v1/refunds/{refund.id}/allocate", json={
        "original_transaction_id": str(txn.id), "allocated_amount": "10",
    }).status_code == 403


@pytest.mark.parametrize("role", ["member", "admin"])
def test_full_control_recipient_can_edit_account_information(auth_client_a, auth_client_b, db, cards, role):
    alice, _, _, _, child, _ = cards
    alice.role = role
    db.add(alice)
    db.commit()
    assert set_share(auth_client_b, child, alice, permission="full_control").status_code == 200
    response = auth_client_a.patch(f"/api/v1/accounts/{child.id}", json={"name": "Authorized rename"})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Account, child.id).name == "Authorized rename"


@pytest.mark.parametrize("role", ["member", "admin"])
@pytest.mark.parametrize("permission", ["read_only", "read_write"])
@pytest.mark.parametrize("method", ["PATCH", "PUT"])
def test_shared_recipient_cannot_delegate_change_or_revoke_sharing(auth_client_a, auth_client_b, db, cards, role, permission, method):
    alice, _, carol, _, child, _ = cards
    alice.role = role
    db.add(alice)
    db.commit()
    assert set_share(auth_client_b, child, alice, permission=permission).status_code == 200
    assert set_share(auth_client_b, child, carol).status_code == 200
    assert auth_client_a.get(f"/api/v1/accounts/{child.id}/shares").json()["can_manage"] is False
    info = auth_client_a.get(f"/api/v1/accounts/{child.id}").json()["account"]
    assert info["can_manage_shares"] is False
    assert info["can_manage"] == (permission == "full_control")
    matrix = auth_client_a.get("/api/v1/accounts/shares/matrix").json()["accounts"]
    assert next(a for a in matrix if a["account_id"] == str(child.id))["can_manage_shares"] is False
    for member in (
        {"user_id": str(alice.id), "permission": "full_control", "shared": True},
        {"user_id": str(carol.id), "permission": "full_control", "shared": True},
        {"user_id": str(carol.id), "shared": False},
    ):
        response = auth_client_a.request(method, f"/api/v1/accounts/{child.id}/shares", json={"members": [member]})
        assert response.status_code == 403
    db.expire_all()
    recipients = {share.user_id: share.permission for share in db.exec(
        select(AccountShare).where(AccountShare.account_id == child.id)).all()}
    assert recipients == {alice.id: permission, carol.id: "read_only"}


@pytest.mark.parametrize("role", ["member", "admin"])
@pytest.mark.parametrize("method", ["PATCH", "PUT"])
def test_full_control_recipient_can_add_change_and_revoke_sharing(auth_client_a, auth_client_b, db, cards, role, method):
    alice, bob, carol, _, child, _ = cards
    alice.role = role
    db.add(alice)
    db.commit()
    assert set_share(auth_client_b, child, alice, permission="full_control").status_code == 200
    assert auth_client_a.get(f"/api/v1/accounts/{child.id}/shares").json()["can_manage"] is True
    info = auth_client_a.get(f"/api/v1/accounts/{child.id}").json()["account"]
    assert info["can_manage_shares"] is True
    listed = auth_client_a.get("/api/v1/accounts").json()["accounts"]
    assert next(a for a in listed if a["id"] == str(child.id))["can_manage_shares"] is True
    matrix = auth_client_a.get("/api/v1/accounts/shares/matrix").json()["accounts"]
    assert next(a for a in matrix if a["account_id"] == str(child.id))["can_manage_shares"] is True
    for permission in ("read_only", "read_write", "full_control"):
        response = auth_client_a.request(method, f"/api/v1/accounts/{child.id}/shares", json={"members": [{
            "user_id": str(carol.id), "permission": permission, "shared": True,
        }]})
        assert response.status_code == 200
        db.expire_all()
        assert db.exec(select(AccountShare).where(
            AccountShare.account_id == child.id, AccountShare.user_id == carol.id)).one().permission == permission
    response = auth_client_a.request(method, f"/api/v1/accounts/{child.id}/shares", json={"members": [{
        "user_id": str(carol.id), "shared": False,
    }]})
    assert response.status_code == 200
    db.expire_all()
    assert db.exec(select(AccountShare).where(
        AccountShare.account_id == child.id, AccountShare.user_id == carol.id)).first() is None
    assert db.get(Account, child.id).owner_id == bob.id


@pytest.mark.parametrize("permission", ["read_only", "read_write", "full_control"])
def test_recipient_updates_own_finance_preference_without_changing_others(auth_client_a, auth_client_b, db, cards, permission):
    alice, _, carol, _, child, _ = cards
    assert set_share(auth_client_b, child, alice, permission=permission).status_code == 200
    assert set_share(auth_client_b, child, carol).status_code == 200
    response = auth_client_a.patch(f"/api/v1/accounts/{child.id}/shares", json={"include_in_finances": False})
    assert response.status_code == 200
    db.expire_all()
    recipients = {share.user_id: share for share in db.exec(
        select(AccountShare).where(AccountShare.account_id == child.id)).all()}
    assert recipients[alice.id].include_in_finances is False
    assert recipients[alice.id].permission == permission
    assert recipients[carol.id].include_in_finances is True


def test_full_control_recipient_cannot_share_outside_family(auth_client_a, auth_client_b, db, cards):
    alice, _, _, _, child, _ = cards
    other_family = Family(name="Other family")
    db.add(other_family)
    db.flush()
    outsider = User(username="outsider", display_name="Outsider", family_id=other_family.id)
    db.add(outsider)
    db.commit()
    assert set_share(auth_client_b, child, alice, permission="full_control").status_code == 200
    response = set_share(auth_client_a, child, outsider)
    assert response.status_code == 400
    assert db.exec(select(AccountShare).where(
        AccountShare.account_id == child.id, AccountShare.user_id == outsider.id)).first() is None


@pytest.mark.parametrize("role", ["member", "admin"])
def test_full_control_recipient_retains_account_management(auth_client_a, auth_client_b, db, cards, role):
    alice, bob, _, _, child, _ = cards
    alice.role = role
    db.add(alice)
    db.commit()
    assert set_share(auth_client_b, child, alice, permission="full_control").status_code == 200
    response = auth_client_a.post(f"/api/v1/accounts/{child.id}/transfer-ownership", json={"new_owner_id": str(alice.id)})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Account, child.id).owner_id == alice.id

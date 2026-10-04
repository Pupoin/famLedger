import pytest
from datetime import datetime, timezone
from decimal import Decimal
import uuid
from starlette.testclient import TestClient
from sqlmodel import Session, select
from models import User, Family, Account, Transaction, Category, PersonalDebt, FamilyBudget, FamilyInvitation, UserPreference
from database import get_session
from auth import _make_token, SESSION_COOKIE

def auth_cookie(user: User | str) -> dict:
    uname = user if isinstance(user, str) else user.username
    return {SESSION_COOKIE: _make_token(uname)}


def test_system_family_list_exposes_archive_and_dissolution_capability(client, db):
    active = Family(name="Active collaboration")
    archived = Family(name="Archived collaboration", status="dissolved", dissolved_at=datetime.now(timezone.utc))
    personal = Family(name="Personal space", kind="personal", is_solo=True)
    admin = User(username="archive_admin", display_name="Admin", role="admin")
    db.add_all([active, archived, personal, admin])
    db.commit()
    ids = {str(active.id), str(archived.id), str(personal.id)}
    response = client.get("/api/v1/family/system/all", cookies=auth_cookie(admin))
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["families"] if row["id"] in ids}
    assert rows[str(active.id)]["can_dissolve"] is True
    assert rows[str(archived.id)]["status"] == "dissolved"
    assert rows[str(archived.id)]["dissolved_at"]
    assert rows[str(archived.id)]["can_dissolve"] is False
    assert rows[str(personal.id)]["kind"] == "personal"
    assert rows[str(personal.id)]["can_dissolve"] is False
    available = client.get("/api/v1/family/list", cookies=auth_cookie(admin))
    assert available.status_code == 200
    available_ids = {row["id"] for row in available.json()["families"]}
    assert str(active.id) in available_ids
    assert str(personal.id) not in available_ids
    # Client presentation must not weaken the server-side rejection.
    repeat = client.delete(f"/api/v1/family/{archived.id}", cookies=auth_cookie(admin))
    assert repeat.status_code == 400
    assert repeat.json()["detail"] == "该家庭组已处于解散归档状态"


def test_family_invitation_lifecycle_and_tenant_merge(client: TestClient, db: Session):
    """
    测试家庭组两阶段邀请完整生命周期：
    1. 管理员发送邀请；
    2. 越权与边界条件防御；
    3. 查看收件箱与发件箱；
    4. 婉拒邀请；
    5. 接受邀请并执行带资入组（Tenant Merge 数据迁移验证）。
    """
    # 准备测试用户与家庭
    # 协作家庭 A：拥有者 user_a
    fam_a = Family(name="幸福之家", currency="CNY", kind="collaborative", status="active")
    db.add(fam_a)
    db.commit()
    db.refresh(fam_a)

    user_a = User(
        username="owner_a",
        password_hash="test_hash",
        security_answer_hash="ans_hash",
        display_name="一家之主A",
        family_id=fam_a.id,
        role="owner",
    )
    # 受邀人 user_b：拥有个人独立空间与私有账户、交易、分类
    fam_b_solo = Family(name="小明个人空间", currency="CNY", kind="personal", is_solo=True, personal_owner_user_id=None)
    db.add(fam_b_solo)
    db.commit()
    db.refresh(fam_b_solo)

    user_b = User(
        username="user_b",
        password_hash="test_hash",
        security_answer_hash="ans_hash",
        display_name="小明",
        family_id=fam_b_solo.id,
        role="owner",
    )
    # 普通成员 user_c：在家庭 A 中
    user_c = User(
        username="member_c",
        password_hash="test_hash",
        security_answer_hash="ans_hash",
        display_name="成员C",
        family_id=fam_a.id,
        role="member",
    )
    pref_b = UserPreference(username=user_b.username, currency="CAD")
    db.add_all([user_a, user_b, user_c, pref_b])
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    db.refresh(user_c)

    # 给 user_b 创建账户与分类
    cat_dining = Category(family_id=fam_b_solo.id, name="餐饮美食", category_type="expense", icon="🍽️", color="#6366f1")
    acc_b = Account(family_id=fam_b_solo.id, owner_id=user_b.id, name="小明的招行卡", account_type="checking", currency="CNY")
    db.add_all([cat_dining, acc_b])
    db.commit()
    db.refresh(cat_dining)
    db.refresh(acc_b)

    txn_b = Transaction(
        account_id=acc_b.id,
        category_id=cat_dining.id,
        transacted_at=datetime.now(timezone.utc).date(),
        narration="午餐汉堡",
        amount=Decimal("-35.00"),
        currency="CNY",
        transaction_type="expense",
        occurred_at=datetime.now(timezone.utc),
    )
    debt_b = PersonalDebt(
        family_id=fam_b_solo.id,
        owner_id=user_b.id,
        debt_type="lend",
        counterparty="朋友小李",
        principal_amount=Decimal("100.00"),
        remaining_amount=Decimal("100.00"),
        currency="CNY",
        borrowed_date=datetime.now(timezone.utc).date(),
        due_date=datetime.now(timezone.utc).date(),
    )
    db.add_all([txn_b, debt_b])
    db.commit()

    # 1. 越权测试：普通成员 user_c 尝试发送邀请 -> 403
    res_c = client.post(
        "/api/v1/family/invitations",
        json={"username": "user_b"},
        cookies=auth_cookie(user_c),
    )
    assert res_c.status_code == 403, res_c.text

    # 2. 个人独立空间 user_b 尝试发送邀请 -> 400
    res_b_solo = client.post(
        "/api/v1/family/invitations",
        json={"username": "owner_a"},
        cookies=auth_cookie(user_b),
    )
    assert res_b_solo.status_code == 400
    assert "个人独立空间无法邀请" in res_b_solo.json()["detail"]

    # 3. 管理员 user_a 发送邀请给不存在的用户 -> 404
    res_non_exist = client.post(
        "/api/v1/family/invitations",
        json={"username": "non_existent_999"},
        cookies=auth_cookie(user_a),
    )
    assert res_non_exist.status_code == 404

    # 4. 管理员 user_a 成功向 user_b 发出邀请
    res_inv1 = client.post(
        "/api/v1/family/invitations",
        json={"username": "user_b", "message": "欢迎加入幸福之家！"},
        cookies=auth_cookie(user_a),
    )
    assert res_inv1.status_code == 200, res_inv1.text
    inv1_id = res_inv1.json()["invitation_id"]

    # 重复发送未决邀请 -> 400
    res_inv1_repeat = client.post(
        "/api/v1/family/invitations",
        json={"username": "user_b"},
        cookies=auth_cookie(user_a),
    )
    assert res_inv1_repeat.status_code == 400

    # 5. 管理员查看发出的邀请
    res_sent = client.get("/api/v1/family/invitations/sent", cookies=auth_cookie(user_a))
    assert res_sent.status_code == 200
    sent_list = res_sent.json()["invitations"]
    assert any(i["id"] == inv1_id and i["status"] == "pending" for i in sent_list)

    # 6. 管理员测试撤回邀请
    res_cancel = client.delete(f"/api/v1/family/invitations/{inv1_id}", cookies=auth_cookie(user_a))
    assert res_cancel.status_code == 200
    # 再次查询发出的邀请，确认状态变为 canceled
    res_sent2 = client.get("/api/v1/family/invitations/sent", cookies=auth_cookie(user_a))
    inv1_data = next(i for i in res_sent2.json()["invitations"] if i["id"] == inv1_id)
    assert inv1_data["status"] == "canceled"

    # 7. 管理员重新向 user_b 发送邀请2
    res_inv2 = client.post(
        "/api/v1/family/invitations",
        json={"username": "user_b", "message": "这次是正式邀请！"},
        cookies=auth_cookie(user_a),
    )
    assert res_inv2.status_code == 200
    inv2_id = res_inv2.json()["invitation_id"]

    # 8. 受邀人 user_b 查看收件箱
    res_recv = client.get("/api/v1/family/invitations/received", cookies=auth_cookie(user_b))
    assert res_recv.status_code == 200
    recv_list = res_recv.json()["invitations"]
    assert len(recv_list) == 1
    assert recv_list[0]["id"] == inv2_id
    assert recv_list[0]["family_name"] == "幸福之家"
    assert recv_list[0]["message"] == "这次是正式邀请！"

    # 9. user_b 测试婉言谢绝邀请2
    res_reject = client.post(f"/api/v1/family/invitations/{inv2_id}/reject", cookies=auth_cookie(user_b))
    assert res_reject.status_code == 200
    # 收件箱应该变空
    res_recv_empty = client.get("/api/v1/family/invitations/received", cookies=auth_cookie(user_b))
    assert len(res_recv_empty.json()["invitations"]) == 0

    # 10. 管理员发送邀请3，由 user_b 接受加入
    res_inv3 = client.post(
        "/api/v1/family/invitations",
        json={"username": "user_b", "message": "一起来记账吧！"},
        cookies=auth_cookie(user_a),
    )
    assert res_inv3.status_code == 200
    inv3_id = res_inv3.json()["invitation_id"]

    # 越权测试：他人尝试接受邀请 -> 404/403
    res_hack_accept = client.post(f"/api/v1/family/invitations/{inv3_id}/accept", cookies=auth_cookie(user_c))
    assert res_hack_accept.status_code in (403, 404)

    # user_b 正式接受加入
    res_accept = client.post(f"/api/v1/family/invitations/{inv3_id}/accept", cookies=auth_cookie(user_b))
    assert res_accept.status_code == 200, res_accept.text
    accept_data = res_accept.json()
    assert "您已成功加入家庭组" in accept_data["message"]
    assert accept_data["family"]["name"] == "幸福之家"
    assert accept_data["currency_change"]["changed"] is True
    assert accept_data["currency_change"]["previous_currency"] == "CAD"
    assert accept_data["currency_change"]["new_currency"] == "CNY"

    # 11. 验证 Tenant Merge 数据迁移效果
    db.expire_all()
    user_b_updated = db.get(User, user_b.id)
    assert user_b_updated.family_id == fam_a.id
    assert user_b_updated.role == "member"

    # 账户归属迁移
    acc_b_updated = db.get(Account, acc_b.id)
    assert acc_b_updated.family_id == fam_a.id
    assert acc_b_updated.owner_id == user_b.id

    # 个人债务归属迁移
    debt_b_updated = db.get(PersonalDebt, debt_b.id)
    assert debt_b_updated.family_id == fam_a.id
    assert debt_b_updated.owner_id == user_b.id

    # 流水与其分类映射完整性
    txn_b_updated = db.get(Transaction, txn_b.id)
    assert txn_b_updated.category_id is not None
    cat_mapped = db.get(Category, txn_b_updated.category_id)
    assert cat_mapped.family_id == fam_a.id
    assert cat_mapped.name == "餐饮美食"

    # 验证受邀人结算货币已自动从 CAD 对齐切换为新家庭法定基准货币 CNY
    pref_b_updated = db.exec(select(UserPreference).where(UserPreference.username == user_b.username)).first()
    assert pref_b_updated is not None
    assert pref_b_updated.currency == fam_a.currency

    res_b_pref = client.get("/api/user-preferences", cookies=auth_cookie(user_b))
    assert res_b_pref.status_code == 200
    assert res_b_pref.json()["currency"] == fam_a.currency


def test_family_dissolution_archive_and_foreign_keys(client: TestClient, db: Session):
    """
    测试家庭组解散归档与数据安全：
    1. 拥有者创建协作家庭，配置预算与借贷；
    2. 解散家庭，验证不触发外键完整性崩溃；
    3. 验证原家庭被标记为 dissolved；
    4. 验证成员自动降级/切入个人独立空间，流水与资产无损保留。
    """
    fam = Family(name="待解散的测试家庭", currency="CNY", kind="collaborative", status="active")
    db.add(fam)
    db.commit()
    db.refresh(fam)

    owner = User(
        username="dissolve_owner",
        password_hash="test_hash",
        security_answer_hash="ans_hash",
        display_name="解散测试管理者",
        family_id=fam.id,
        role="owner",
    )
    member = User(
        username="dissolve_member",
        password_hash="test_hash",
        security_answer_hash="ans_hash",
        display_name="解散测试普通成员",
        family_id=fam.id,
        role="member",
    )
    db.add_all([owner, member])
    db.commit()
    db.refresh(owner)
    db.refresh(member)

    # 建立家庭预算（此前触发 SQLite 外键冲突的核心模型）
    budget = FamilyBudget(family_id=fam.id, settings={"monthly_budget": 8888.0})
    # 建立账户与流水
    acc_owner = Account(family_id=fam.id, owner_id=owner.id, name="管理者卡", account_type="checking", currency="CNY")
    acc_member = Account(family_id=fam.id, owner_id=member.id, name="成员卡", account_type="checking", currency="CNY")
    db.add_all([budget, acc_owner, acc_member])
    db.commit()
    db.refresh(acc_owner)
    db.refresh(acc_member)

    txn = Transaction(
        account_id=acc_owner.id,
        transacted_at=datetime.now(timezone.utc).date(),
        narration="测试日常支出",
        amount=Decimal("-50.00"),
        currency="CNY",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(txn)
    db.commit()

    # 普通成员尝试解散 -> 403
    res_deny = client.delete("/api/v1/family/current", cookies=auth_cookie(member))
    assert res_deny.status_code == 403

    # 管理员执行解散操作 -> 200
    res_dissolve = client.delete("/api/v1/family/current", cookies=auth_cookie(owner))
    assert res_dissolve.status_code == 200, res_dissolve.text
    dissolve_data = res_dissolve.json()
    assert "已成功解散" in dissolve_data["message"]

    # 验证原家庭组状态为 dissolved，预算依然无损保留（归档保存）
    db.expire_all()
    old_fam = db.get(Family, fam.id)
    assert old_fam.status == "dissolved"
    old_budget = db.get(FamilyBudget, fam.id)
    assert old_budget is not None
    assert old_budget.settings.get("monthly_budget") == 8888.0

    # 验证原成员均被切入独立的个人空间
    owner_refreshed = db.get(User, owner.id)
    member_refreshed = db.get(User, member.id)

    assert owner_refreshed.family_id != fam.id
    assert member_refreshed.family_id != fam.id
    assert owner_refreshed.family_id != member_refreshed.family_id

    owner_solo = db.get(Family, owner_refreshed.family_id)
    assert owner_solo.kind == "personal"
    assert owner_solo.is_solo is True

    member_solo = db.get(Family, member_refreshed.family_id)
    assert member_solo.kind == "personal"
    assert member_solo.is_solo is True

    # 验证账户与流水完整性
    acc_owner_refreshed = db.get(Account, acc_owner.id)
    assert acc_owner_refreshed.family_id == owner_solo.id
    assert acc_owner_refreshed.owner_id == owner.id

    acc_member_refreshed = db.get(Account, acc_member.id)
    assert acc_member_refreshed.family_id == member_solo.id
    assert acc_member_refreshed.owner_id == member.id

    # 验证解散后调用 get_current_family
    res_fam_curr = client.get("/api/v1/family/current", cookies=auth_cookie(owner))
    assert res_fam_curr.status_code == 200
    curr_data = res_fam_curr.json()
    assert curr_data["is_solo"] is True
    assert curr_data["kind"] == "personal"
    assert curr_data["members"] == []  # 单人空间 members 应当为空


def test_transaction_currency_auto_align_with_account(client: TestClient, db: Session):
    """
    测试新账户添加交易时流水币种自适应账户基准币种：
    1. 纯新账户币种为 USD；
    2. 创建流水未显式传递 currency 字段 -> 自动适配账户币种 USD 并成功落库（不再报错 400）；
    3. 创建流水传递了不一致的 currency (如 CNY) -> 后端自适应修正为账户币种 USD 并成功落库。
    """
    fam = Family(name="币种测试家庭", currency="USD", kind="personal", is_solo=True)
    db.add(fam)
    db.commit()
    db.refresh(fam)

    user = User(
        username="usd_user",
        password_hash="test_hash",
        security_answer_hash="ans_hash",
        display_name="美元用户",
        family_id=fam.id,
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    acc = Account(
        family_id=fam.id,
        owner_id=user.id,
        name="美元活期储蓄",
        account_type="checking",
        currency="USD",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)

    # 1. 提交交易时未传 currency 字段
    res1 = client.post(
        "/api/v1/transactions",
        json={
            "account_id": str(acc.id),
            "transacted_at": "2026-10-02",
            "amount": "15.50",
            "transaction_type": "expense",
            "narration": "买咖啡（未传币种）",
        },
        cookies=auth_cookie(user),
    )
    assert res1.status_code == 200, res1.text
    data1 = res1.json()
    assert data1["currency"] == "USD"

    # 2. 提交交易时传递了与账户不一致的 currency ("CNY")
    res2 = client.post(
        "/api/v1/transactions",
        json={
            "account_id": str(acc.id),
            "transacted_at": "2026-10-02",
            "amount": "20.00",
            "currency": "CNY",
            "transaction_type": "expense",
            "narration": "买书（前端默认CNY传入USD账户）",
        },
        cookies=auth_cookie(user),
    )
    assert res2.status_code == 200, res2.text
    data2 = res2.json()
    # 验证已被自动对齐为账户基准币种 USD
    assert data2["currency"] == "USD"


def test_delete_user_cascade_with_invitations_and_debts(client: TestClient, db: Session):
    """
    测试删除用户或注销时，外键级联清理 FamilyInvitation、PersonalDebt 与 Family 引用，
    防止 SQLite PRAGMA foreign_keys = ON 下抛出 FOREIGN KEY constraint failed (409 数据约束冲突)。
    """
    from auth import hash_password

    # 1. 准备家庭与用户
    fam = Family(name="测试删除大家庭", currency="CNY", kind="collaborative", status="active")
    db.add(fam)
    db.commit()
    db.refresh(fam)

    admin_user = User(
        username="admin_deleter",
        password_hash=hash_password("admin_pass"),
        display_name="管理员",
        family_id=fam.id,
        role="admin",
    )
    target_user = User(
        username="target_member",
        password_hash=hash_password("target_pass"),
        display_name="被删成员",
        family_id=fam.id,
        role="member",
    )
    third_user = User(
        username="third_party",
        password_hash=hash_password("third_pass"),
        display_name="第三方受邀人",
        family_id=fam.id,
        role="member",
    )
    db.add_all([admin_user, target_user, third_user])
    db.commit()
    db.refresh(admin_user)
    db.refresh(target_user)
    db.refresh(third_user)

    # 2. 为 target_user 建立各种外键关联数据：
    # 2.1 账户与流水
    target_acc = Account(family_id=fam.id, owner_id=target_user.id, name="待删账户", account_type="checking")
    db.add(target_acc)
    db.commit()
    db.refresh(target_acc)

    # 2.2 债务记录 PersonalDebt
    debt = PersonalDebt(
        family_id=fam.id,
        owner_id=target_user.id,
        debt_type="borrow",
        counterparty="张三",
        principal_amount=Decimal("500.00"),
        remaining_amount=Decimal("500.00"),
        borrowed_date=datetime.now(timezone.utc).date(),
    )
    db.add(debt)

    # 2.3 邀请记录 1：target_user 作为受邀人
    inv1 = FamilyInvitation(
        family_id=fam.id,
        inviter_user_id=admin_user.id,
        invitee_user_id=target_user.id,
        status="accepted",
        processed_by_user_id=target_user.id,
        processed_at=datetime.now(timezone.utc),
    )
    # 2.4 邀请记录 2：target_user 作为发起人邀请 third_user
    inv2 = FamilyInvitation(
        family_id=fam.id,
        inviter_user_id=target_user.id,
        invitee_user_id=third_user.id,
        status="pending",
    )
    db.add_all([inv1, inv2])

    # 2.5 建立一个指向 target_user 的个人空间家庭记录 (弱引用)
    solo_fam = Family(
        name="待删用户的过往空间",
        currency="CNY",
        personal_owner_user_id=target_user.id,
        dissolved_by_user_id=target_user.id,
    )
    db.add(solo_fam)
    db.commit()
    db.refresh(solo_fam)

    fam_id = fam.id
    admin_user_id = admin_user.id
    solo_fam_id = solo_fam.id
    target_user_id = target_user.id

    # 3. 执行管理员删除成员 DELETE /api/v1/family/members/{target_user.id}
    del_res = client.request(
        "DELETE",
        f"/api/v1/family/members/{target_user_id}",
        json={"admin_password": "admin_pass"},
        cookies=auth_cookie(admin_user),
    )
    assert del_res.status_code == 200, del_res.text
    del_data = del_res.json()
    assert del_data["status"] == "ok"

    # 4. 验证数据库中关联记录已级联清理或解绑
    db.expunge_all()
    # 4.1 用户已被删除
    assert db.exec(select(User).where(User.id == target_user_id)).first() is None
    # 4.2 涉及 target_user 的邀请记录已被全部清理
    rem_invs = db.exec(
        select(FamilyInvitation).where(
            (FamilyInvitation.invitee_user_id == target_user_id)
            | (FamilyInvitation.inviter_user_id == target_user_id)
            | (FamilyInvitation.processed_by_user_id == target_user_id)
        )
    ).all()
    assert len(rem_invs) == 0
    # 4.3 债务记录已被清理
    rem_debts = db.exec(select(PersonalDebt).where(PersonalDebt.owner_id == target_user_id)).all()
    assert len(rem_debts) == 0
    # 4.4 弱引用外键已被置空，未产生孤儿外键或冲突
    refreshed_solo = db.exec(select(Family).where(Family.id == solo_fam_id)).first()
    assert refreshed_solo.personal_owner_user_id is None
    assert refreshed_solo.dissolved_by_user_id is None

    # 5. 测试用户自主注销场景 DELETE /api/auth/account
    # 构造待注销用户 self_user，并同样为其赋予邀请关联
    self_user = User(
        username="self_deleter",
        password_hash=hash_password("mypassword123"),
        display_name="自主注销用户",
        family_id=fam_id,
        role="member",
    )
    db.add(self_user)
    db.commit()
    db.refresh(self_user)
    self_user_id = self_user.id

    inv3 = FamilyInvitation(
        family_id=fam_id,
        inviter_user_id=admin_user_id,
        invitee_user_id=self_user_id,
        status="pending",
    )
    db.add(inv3)
    db.commit()

    self_del_res = client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": "mypassword123", "data_action": "delete"},
        cookies=auth_cookie(self_user),
    )
    assert self_del_res.status_code == 200, self_del_res.text
    db.expunge_all()
    assert db.exec(select(User).where(User.id == self_user_id)).first() is None
    rem_inv3 = db.exec(
        select(FamilyInvitation).where(FamilyInvitation.invitee_user_id == self_user_id)
    ).all()
    assert len(rem_inv3) == 0


def test_voluntary_leave_family_lifecycle(client: TestClient, db: Session):
    """
    测试用户主动退出家庭组全流程：
    1. 个人空间用户调用退出 -> 400 拦截；
    2. 多人家庭 Owner 调用退出 -> 400 拦截并提示转让或解散；
    3. 普通成员主动退出 -> 200 成功，账户无损迁移到个人独立空间；
    4. 独身多人家庭 Owner 调用退出 -> 200 成功，原家庭自动解散归档。
    """
    # 1. 准备多人协作家庭
    fam_multi = Family(name="测试大家庭", currency="CNY", kind="collaborative", status="active")
    db.add(fam_multi)
    db.commit()
    db.refresh(fam_multi)
    fam_multi_id = fam_multi.id

    owner_u = User(
        username="fam_owner_user",
        password_hash="hash",
        security_answer_hash="ans",
        display_name="大户主",
        family_id=fam_multi_id,
        role="owner",
    )
    member_u = User(
        username="fam_member_user",
        password_hash="hash",
        security_answer_hash="ans",
        display_name="小成员",
        family_id=fam_multi_id,
        role="member",
    )
    db.add_all([owner_u, member_u])
    db.commit()
    db.refresh(owner_u)
    db.refresh(member_u)
    owner_u_id = owner_u.id
    member_u_id = member_u.id

    # 给 member_u 创建个人账户和流水
    acc_m = Account(family_id=fam_multi_id, owner_id=member_u_id, name="小成员私房钱", account_type="checking", currency="CNY")
    db.add(acc_m)
    db.commit()
    db.refresh(acc_m)
    acc_m_id = acc_m.id

    admin_2 = User(
        username="fam_admin_user_2",
        password_hash="hash",
        security_answer_hash="ans",
        display_name="第二管理员",
        family_id=fam_multi_id,
        role="owner",
    )
    db.add(admin_2)
    db.commit()
    db.refresh(admin_2)
    admin_2_id = admin_2.id

    owner_username = "fam_owner_user"
    member_username = "fam_member_user"
    admin_2_username = "fam_admin_user_2"

    # Case 1: 家庭内有多个管理员（owner_u 和 admin_2），其中一个管理员（owner_u）主动退出 -> 200 成功
    res_owner_leave = client.post("/api/v1/family/leave", cookies=auth_cookie(owner_username))
    assert res_owner_leave.status_code == 200, res_owner_leave.text
    data_owner_leave = res_owner_leave.json()
    assert data_owner_leave["status"] == "ok"
    assert "已成功退出家庭组" in data_owner_leave["message"]

    # 验证 owner_u 已迁移至其个人独立空间，原家庭依然活跃，且由 admin_2 担任管理员
    db.expunge_all()
    refreshed_owner = db.get(User, owner_u_id)
    assert refreshed_owner.family_id != fam_multi_id
    old_fam = db.get(Family, fam_multi_id)
    assert old_fam.status == "active"
    refreshed_admin_2 = db.get(User, admin_2_id)
    assert refreshed_admin_2.family_id == fam_multi_id

    # Case 2: 此时原家庭只剩 admin_2 (唯一管理员) 和 member_u (普通成员)，admin_2 尝试退出 -> 拦截 400
    res_sole_admin_leave = client.post("/api/v1/family/leave", cookies=auth_cookie(admin_2_username))
    assert res_sole_admin_leave.status_code == 400
    assert "唯一的管理员" in res_sole_admin_leave.json()["detail"]

    # Case 3: 普通成员 member_u 主动退出 -> 成功 200
    res_member_leave = client.post("/api/v1/family/leave", cookies=auth_cookie(member_username))
    assert res_member_leave.status_code == 200, res_member_leave.text
    data_leave = res_member_leave.json()
    assert data_leave["status"] == "ok"
    assert "已成功退出家庭组" in data_leave["message"]
    assert data_leave["family"]["is_solo"] is True

    # 验证数据库状态
    db.expunge_all()
    refreshed_member = db.get(User, member_u_id)
    assert refreshed_member.family_id != fam_multi_id
    solo_fam = db.get(Family, refreshed_member.family_id)
    assert solo_fam.is_solo is True
    assert solo_fam.kind == "personal"
    assert refreshed_member.role == "owner"

    # 验证账户归属已平滑迁移到个人空间
    refreshed_acc = db.get(Account, acc_m_id)
    assert refreshed_acc.family_id == solo_fam.id

    # Case 4: 此时已经在个人独立空间，再次调用退出 -> 400 拦截
    res_repeat_leave = client.post("/api/v1/family/leave", cookies=auth_cookie(member_username))
    assert res_repeat_leave.status_code == 400
    assert "个人独立空间" in res_repeat_leave.json()["detail"]

    # Case 5: 原多人家庭此时只剩 admin_2 1 人，admin_2 调用退出 -> 成功 200，原家庭标记为 dissolved
    res_admin_solo_leave = client.post("/api/v1/family/leave", cookies=auth_cookie(admin_2))
    assert res_admin_solo_leave.status_code == 200, res_admin_solo_leave.text

    db.expunge_all()
    refreshed_admin_2 = db.get(User, admin_2_id)
    assert refreshed_admin_2.family_id != fam_multi_id
    old_fam = db.get(Family, fam_multi_id)
    assert old_fam.status == "dissolved"

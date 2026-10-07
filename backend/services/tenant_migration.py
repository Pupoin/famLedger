import logging
import uuid
from typing import List, Optional
from datetime import datetime, timezone
from sqlmodel import Session, select, or_

from models import (
    User,
    Family,
    Account,
    Transaction,
    TransactionSplit,
    Transfer,
    RefundAllocation,
    AccountShare,
    PersonalDebt,
    Category,
    Tag,
    FamilyInvitation,
    UserPreference,
)

logger = logging.getLogger("mosaic.migration")


def remap_categories_and_tags(
    session: Session,
    moved_account_ids: List[uuid.UUID],
    target_family_id: uuid.UUID,
    source_family_id: Optional[uuid.UUID] = None,
) -> None:
    """
    智能重定向流水的分类与标签（无损映射）：
    1. 查询迁移账户流水的全部分类引用；
    2. 在目标家庭中按名称与类型匹配分类；若目标家庭不存在，复制该分类至目标家庭；
    3. 将流水和拆分项的 category_id 更新为目标家庭的对应分类 ID；
    4. 提取流水的标签字符串，在目标家庭中补齐缺失的 Tag 实体定义。
    """
    if not moved_account_ids:
        return

    # 1. 查找涉及迁移的所有流水 ID
    moved_txns = session.exec(
        select(Transaction).where(Transaction.account_id.in_(moved_account_ids))
    ).all()
    if not moved_txns:
        return

    moved_txn_ids = [t.id for t in moved_txns]

    # 2. 收集需要重映射的分类
    old_cat_ids = set()
    for t in moved_txns:
        if t.category_id:
            old_cat_ids.add(t.category_id)

    splits = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id.in_(moved_txn_ids))
    ).all()
    for sp in splits:
        if sp.category_id:
            old_cat_ids.add(sp.category_id)

    # 3. 建立旧分类 -> 新分类 ID 映射表
    cat_id_mapping = {}
    if old_cat_ids:
        target_cats = session.exec(
            select(Category).where(Category.family_id == target_family_id)
        ).all()
        target_cat_by_key = {
            (c.parent_id, c.name.strip(), c.category_type or "expense"): c for c in target_cats
        }
        visiting = set()

        def copy_category(old_cid, depth=0):
            if old_cid in cat_id_mapping:
                return cat_id_mapping[old_cid]
            if old_cid in visiting or depth > 100:
                raise ValueError("分类树存在循环或深度超限")
            old_cat = session.get(Category, old_cid)
            if not old_cat:
                raise ValueError("迁移分类不存在")
            if old_cat.family_id == target_family_id:
                cat_id_mapping[old_cid] = old_cid
                return old_cid
            visiting.add(old_cid)
            parent_id = None
            if old_cat.parent_id:
                parent = session.get(Category, old_cat.parent_id)
                if not parent or parent.family_id != old_cat.family_id:
                    raise ValueError("分类父级不存在或属于其他家庭")
                parent_id = copy_category(parent.id, depth + 1)
            match_key = (parent_id, old_cat.name.strip(), old_cat.category_type or "expense")
            match = target_cat_by_key.get(match_key)
            if match is None:
                match = Category(
                    family_id=target_family_id, parent_id=parent_id,
                    name=old_cat.name.strip(), icon=old_cat.icon, color=old_cat.color,
                    category_type=old_cat.category_type or "expense", i18n_key=old_cat.i18n_key,
                )
                session.add(match)
                session.flush()
                target_cat_by_key[match_key] = match
            cat_id_mapping[old_cid] = match.id
            visiting.remove(old_cid)
            return match.id

        for old_cid in sorted(old_cat_ids, key=str):
            copy_category(old_cid)

    # 4. 执行分类重映射
    if cat_id_mapping:
        for t in moved_txns:
            if t.category_id and t.category_id in cat_id_mapping:
                t.category_id = cat_id_mapping[t.category_id]
                session.add(t)

        for sp in splits:
            if sp.category_id and sp.category_id in cat_id_mapping:
                sp.category_id = cat_id_mapping[sp.category_id]
                session.add(sp)

    # Preserve source tag metadata and normalize aliases to stable names.
    existing_tags = session.exec(select(Tag).where(Tag.family_id == target_family_id)).all()
    existing_tag_names = {t.name for t in existing_tags}
    source_tags = session.exec(select(Tag).where(Tag.family_id == source_family_id)).all() if source_family_id else []
    source_by_label = {}
    for tag in source_tags:
        for label in [tag.name, *(tag.aliases or [])]:
            source_by_label.setdefault(label, tag)
    for txn in moved_txns:
        labels = []
        for label in txn.tags or []:
            if not isinstance(label, str) or not label.strip():
                continue
            label = label.strip()
            source_tag = source_by_label.get(label)
            name = source_tag.name if source_tag else label
            if name not in labels:
                labels.append(name)
            if name not in existing_tag_names:
                session.add(Tag(
                    family_id=target_family_id, name=name,
                    color=source_tag.color if source_tag else "#71717a",
                    aliases=list(source_tag.aliases or []) if source_tag else [],
                    is_archived=source_tag.is_archived if source_tag else False,
                ))
                existing_tag_names.add(name)
        txn.tags = labels
        session.add(txn)


def migrate_transfers_and_refunds(
    session: Session,
    moved_account_ids: List[uuid.UUID],
    target_family_id: uuid.UUID,
) -> None:
    """迁移账户关联的内部转账归属，解绑跨家庭转账与退款，保存原始单边外部转账语义。"""
    if not moved_account_ids:
        return

    moved_txns = session.exec(
        select(Transaction.id).where(Transaction.account_id.in_(moved_account_ids))
    ).all()
    if not moved_txns:
        return
    moved_txn_id_set = set(moved_txns)

    # 1. 转账处理
    affected_transfers = session.exec(
        select(Transfer).where(
            or_(
                Transfer.outflow_transaction_id.in_(moved_txn_id_set),
                Transfer.inflow_transaction_id.in_(moved_txn_id_set),
            )
        )
    ).all()

    for tr in affected_transfers:
        out_moved = tr.outflow_transaction_id in moved_txn_id_set
        in_moved = tr.inflow_transaction_id in moved_txn_id_set
        if out_moved and in_moved:
            # 双端均迁移到目标家庭：更新 Transfer.family_id 保留配对
            tr.family_id = target_family_id
            session.add(tr)
        else:
            # 单端迁移：解除跨家庭转账配对，保留各端为外部转账，防止破坏收支统计
            if tr.outflow_transaction_id:
                out_txn = session.get(Transaction, tr.outflow_transaction_id)
                if out_txn:
                    out_txn.transfer_id = None
                    out_txn.transaction_type = "expense"
                    session.add(out_txn)
            if tr.inflow_transaction_id:
                in_txn = session.get(Transaction, tr.inflow_transaction_id)
                if in_txn:
                    in_txn.transfer_id = None
                    in_txn.transaction_type = "income"
                    session.add(in_txn)
            session.delete(tr)

    # 2. 退款处理
    affected_allocs = session.exec(
        select(RefundAllocation).where(
            or_(
                RefundAllocation.refund_transaction_id.in_(moved_txn_id_set),
                RefundAllocation.original_transaction_id.in_(moved_txn_id_set),
            )
        )
    ).all()
    for al in affected_allocs:
        ref_in = al.refund_transaction_id in moved_txn_id_set
        orig_in = al.original_transaction_id in moved_txn_id_set
        if not (ref_in and orig_in):
            ref_txn = session.get(Transaction, al.refund_transaction_id)
            if ref_txn and ref_txn.refund_of_transaction_id == al.original_transaction_id:
                ref_txn.refund_of_transaction_id = None
                session.add(ref_txn)
            session.delete(al)

    # 3. 清除单边跨家庭退款指针
    for ref_t in session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(moved_account_ids),
            Transaction.refund_of_transaction_id.is_not(None),
        )
    ).all():
        orig = session.get(Transaction, ref_t.refund_of_transaction_id)
        if orig and orig.id not in moved_txn_id_set:
            ref_t.refund_of_transaction_id = None
            session.add(ref_t)

    for rem_t in session.exec(
        select(Transaction).where(
            Transaction.refund_of_transaction_id.in_(moved_txn_id_set),
            ~Transaction.account_id.in_(moved_account_ids),
        )
    ).all():
        rem_t.refund_of_transaction_id = None
        session.add(rem_t)


def migrate_user_to_family(
    session: Session,
    user: User,
    target_family_id: uuid.UUID,
    role: str = "member",
    dissolving: bool = False,
) -> int:
    """
    统一的数据迁移服务（Tenant Merge）：
    将用户、用户名下资产账户、个人借贷完整迁移至目标家庭组。
    返回成功迁移的账户数量。
    """
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    if not dissolving and user.family_id != target_family_id:
        from services.membership import ensure_can_leave
        ensure_can_leave(session, user)
    target = session.get(Family, target_family_id)
    if not target or target.status != "active":
        from fastapi import HTTPException
        raise HTTPException(400, "不能迁入已归档或不存在的家庭")
    old_family_id = user.family_id

    # 1. 查找用户拥有的所有账户
    user_accounts = session.exec(
        select(Account).where(Account.owner_id == user.id)
    ).all()
    account_ids = [acc.id for acc in user_accounts]

    # Carry each card's unpaid share across the tenant boundary before changing
    # family IDs. Once moved, the old group's tenant filter cannot see that debt.
    moved_ids = set(account_ids)
    related_cards = session.exec(select(Account).where(
        Account.parent_account_id.is_not(None),
        or_(Account.id.in_(moved_ids), Account.parent_account_id.in_(moved_ids)),
    )).all() if moved_ids else []
    for child in related_cards:
        if (child.id in moved_ids) != (child.parent_account_id in moved_ids):
            child.parent_account_id = None
            session.add(child)
    session.flush()

    # Pending source records follow their account but never auto-use old-family links.
    from models import PendingFxTransaction
    for pending in session.exec(select(PendingFxTransaction).where(PendingFxTransaction.account_id.in_(account_ids))).all():
        pending.family_id = target_family_id
        pending.status = "canceled"
        pending.last_error = "账户迁移家庭，待入账来源需重新核对后录入"
        pending.payload = {key: value for key, value in pending.payload.items()
                           if key not in {"refund_of_transaction_id", "category_id"}}
        session.add(pending)

    # 2. 更新账户租户归属
    for acc in user_accounts:
        acc.family_id = target_family_id
        session.add(acc)

    # 3. 迁移该用户所有的个人借贷 PersonalDebt（不再删除）
    user_debts = session.exec(
        select(PersonalDebt).where(PersonalDebt.owner_id == user.id)
    ).all()
    for debt in user_debts:
        debt.family_id = target_family_id
        session.add(debt)

    # 4. 执行分类与标签重映射
    if account_ids:
        remap_categories_and_tags(session, account_ids, target_family_id, source_family_id=old_family_id)
        migrate_transfers_and_refunds(session, account_ids, target_family_id)

    # Scheduled jobs only move when every linked account moves together.
    # Require an explicit resume after the permission/family boundary changes.
    from models import ScheduledPlan
    from services.schedules import delete_plans, plan_account_ids
    plans = [p for p in session.exec(select(ScheduledPlan)).all()
             if p.owner_id == user.id or plan_account_ids(p) & set(account_ids)]
    for plan in plans:
        all_ids = plan_account_ids(plan)
        if all_ids.issubset(set(account_ids)):
            plan.family_id, plan.owner_id = target_family_id, user.id
            if plan.status != 'cancelled':
                plan.status = 'paused'
                plan.config = {**plan.config, 'pause_reason': '账户迁移家庭，请核对计划后恢复'}
            from models import ScheduledOccurrence
            for row in session.exec(select(ScheduledOccurrence).where(ScheduledOccurrence.plan_id == plan.id)).all():
                if row.linked_original:
                    row.linked_original = {**row.linked_original, 'category_id': None, 'tags': []}
                    session.add(row)
            session.add(plan)
        else:
            delete_plans(session, [plan])

    # 5. 清理跨家庭账户共享权限
    if account_ids:
        # 清除该账户向原家庭其他成员开放的共享
        session.exec(
            select(AccountShare).where(AccountShare.account_id.in_(account_ids))
        )
        for ash in session.exec(
            select(AccountShare).where(AccountShare.account_id.in_(account_ids))
        ).all():
            session.delete(ash)

    # 清除该用户在旧家庭中接收到的来自他人的共享授权
    for rsh in session.exec(
        select(AccountShare).where(AccountShare.user_id == user.id)
    ).all():
        session.delete(rsh)

    # 6. 取消该用户此前收到的所有未决邀请
    pending_invites = session.exec(
        select(FamilyInvitation).where(
            FamilyInvitation.invitee_user_id == user.id,
            FamilyInvitation.status == "pending",
        )
    ).all()
    now_utc = datetime.now(timezone.utc)
    for inv in pending_invites:
        inv.status = "canceled"
        inv.cancel_reason = "用户已加入其他家庭组"
        inv.processed_at = now_utc
        session.add(inv)

    # 7. 更新用户身份与家庭归属
    user.family_id = target_family_id
    if user.role != "admin":
        user.role = role
    session.add(user)

    # 8. 自动将用户的默认结算币种对齐为目标家庭组的基准货币
    target_family = session.get(Family, target_family_id)
    if target_family and target_family.currency:
        pref = session.exec(
            select(UserPreference).where(UserPreference.username == user.username)
        ).first()
        if pref:
            pref.currency = target_family.currency
            session.add(pref)
        else:
            pref = UserPreference(username=user.username, currency=target_family.currency)
            session.add(pref)

    logger.info(
        f"User {user.username} successfully migrated from family {old_family_id} to {target_family_id} with {len(account_ids)} accounts."
    )
    return len(account_ids)

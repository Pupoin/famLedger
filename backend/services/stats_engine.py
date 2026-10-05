"""
Unified Statistics and Cashflow Netting Engine (Single Source of Truth).
统一财务收支统计、分类归集与净额化退款冲抵算法引擎。
保证 Dashboard (Sankey), Budgets, Analytics 三大模块在同一周期与作用域下计算逻辑完全一致。
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
from sqlmodel import Session, select

from models import Account, Category, Family, Transaction
from services.account_types import financial_classification

OTHER_CATEGORY_DEF = {"id": "cat_other", "name": "其他", "icon": "📦", "color": "#f97316"}


def get_family_active_account_ids(session: Session, family_id: Optional[uuid.UUID] = None) -> Set[uuid.UUID]:
    """获取家庭下所有有效存续账户的 ID 集合。若未加入任何家庭，必须严格返回空集合。"""
    if not family_id:
        return set()
    stmt = select(Account.id).where(Account.is_active == True, Account.family_id == family_id)
    return set(session.exec(stmt).all())


def get_user_visible_account_ids(
    session: Session,
    user: Optional[Any],
    family_id: Optional[uuid.UUID] = None
) -> Set[uuid.UUID]:
    """获取当前用户有权查看的有效存续账户 ID 集合（遵循显式共享原则，防同家庭私有账户越权泄露）。"""
    if not user:
        return set()
    from models import AccountShare, User

    # 系统服务凭证（如 service:dev, service:bill）具备家庭内所有账户的全局读取权限
    if isinstance(user, str) and user.startswith("service:"):
        from services.principals import service_family
        bound_id = service_family(session).id
        if family_id and family_id != bound_id:
            return set()
        family_id = bound_id
        if family_id:
            stmt = select(Account.id).where(Account.is_active == True, Account.family_id == family_id)
        else:
            stmt = select(Account.id).where(Account.is_active == True)
        return set(session.exec(stmt).all())

    target_fid = family_id or getattr(user, "family_id", None)

    # 系统管理员（admin）：拥有家庭内（或全库）所有有效账户的全局可读权限
    if getattr(user, "role", None) == "admin":
        if target_fid:
            stmt = select(Account.id).where(Account.is_active == True, Account.family_id == target_fid)
        else:
            stmt = select(Account.id).where(Account.is_active == True)
        return set(session.exec(stmt).all())

    # 普通成员（含 owner 与普通 member）：仅能访问自己拥有的账户或被他人显式授权共享的账户
    user_id = getattr(user, "id", None)
    if not user_id:
        return set()

    shared_acc_ids = set(session.exec(
        select(AccountShare.account_id).where(AccountShare.user_id == user_id)
    ).all())

    if shared_acc_ids:
        cond = (Account.owner_id == user_id) | (Account.id.in_(shared_acc_ids))
    else:
        cond = (Account.owner_id == user_id)

    if target_fid:
        stmt = select(Account.id).where(
            Account.family_id == target_fid,
            Account.is_active == True,
            cond,
        )
    else:
        stmt = select(Account.id).where(
            Account.is_active == True,
            cond,
        )
    return set(session.exec(stmt).all())


def get_user_writable_account_ids(
    session: Session,
    user: Optional[Any],
    family_id: Optional[uuid.UUID] = None
) -> Set[uuid.UUID]:
    """获取当前用户有权写入/变更的有效存续账户 ID 集合（账户所有者、拥有 read_write/full_control 权限，或系统管理员）。"""
    if not user:
        return set()
    from models import AccountShare, User

    # 系统服务凭证（如 service:dev, service:bill）具备家庭内所有账户的全局写权限
    if isinstance(user, str) and user.startswith("service:"):
        from services.principals import service_family
        bound_id = service_family(session).id
        if family_id and family_id != bound_id:
            return set()
        family_id = bound_id
        if family_id:
            stmt = select(Account.id).where(Account.is_active == True, Account.family_id == family_id)
        else:
            stmt = select(Account.id).where(Account.is_active == True)
        return set(session.exec(stmt).all())

    target_fid = family_id or getattr(user, "family_id", None)

    if getattr(user, "role", None) == "admin":
        if target_fid:
            stmt = select(Account.id).where(Account.is_active == True, Account.family_id == target_fid)
        else:
            stmt = select(Account.id).where(Account.is_active == True)
        allowed = set(session.exec(stmt).all())
        restricted = set(session.exec(select(AccountShare.account_id).join(
            Account, Account.id == AccountShare.account_id).where(
                AccountShare.user_id == user.id, Account.owner_id != user.id,
                AccountShare.permission.notin_(("read_write", "full_control")),
            )).all())
        return allowed - restricted

    user_id = getattr(user, "id", None)
    if not user_id:
        return set()

    write_shares = set(session.exec(
        select(AccountShare.account_id).where(
            AccountShare.user_id == user_id,
            AccountShare.permission.in_(("read_write", "full_control")),
        )
    ).all())

    if write_shares:
        cond = (Account.owner_id == user_id) | (Account.id.in_(write_shares))
    else:
        cond = (Account.owner_id == user_id)

    if target_fid:
        stmt = select(Account.id).where(
            Account.family_id == target_fid,
            Account.is_active == True,
            cond,
        )
    else:
        stmt = select(Account.id).where(
            Account.is_active == True,
            cond,
        )
    return set(session.exec(stmt).all())


def is_genuine_income(t: Transaction, account_map: Dict[uuid.UUID, Account]) -> bool:
    """判定是否为真正的外部增量收入（排除平账、还贷冲减、卡间互转、排除统计等）。"""
    if t.transaction_type != "income":
        return False
    if t.excluded_from_stats:
        return False
    acc = account_map.get(t.account_id)
    if acc and financial_classification(acc) == "liability":
        return False
    return True


def is_genuine_expense(t: Transaction, account_map: Dict[uuid.UUID, Account]) -> bool:
    """判定是否为真正的日常消费支出（排除贷款放款、还贷本金、对账平账、排除统计等）。"""
    if t.transaction_type != "expense":
        return False
    if t.excluded_from_stats:
        return False
    return True


def is_genuine_refund(t: Transaction) -> bool:
    """判定是否为有效退款冲抵项。"""
    if t.transaction_type != "refund":
        return False
    if t.excluded_from_stats:
        return False
    return True


def category_definition(category):
    return {"id": str(category.id), "name": category.name,
            "icon": category.icon or "📦", "color": category.color or "#f97316"}


def classify_transaction(t: Transaction, category_map: Dict[uuid.UUID, Category]) -> Dict[str, Any]:
    """Read the persisted classification, including explicit Other choices."""
    category = category_map.get(t.category_id)
    if category:
        return category_definition(category)
    other = next((c for c in category_map.values() if c.name == '其他' and not c.parent_id), None)
    return category_definition(other) if other else OTHER_CATEGORY_DEF.copy()


def classify_split_item(split_cat_id, split_notes, fallback_txn, category_map):
    category = category_map.get(split_cat_id)
    return category_definition(category) if category else classify_transaction(fallback_txn, category_map)


def compute_netted_category_distribution(
    expense_txns: List[Transaction],
    refund_txns: List[Transaction],
    category_map: Dict[uuid.UUID, Category],
    splits_map: Optional[Dict[uuid.UUID, List[Any]]] = None,
    session: Optional[Session] = None,
    allowed_account_ids: Optional[Set[uuid.UUID]] = None,
    report_money=None,
) -> Tuple[List[Dict[str, Any]], float, float, float]:
    """Signed category totals conserve gross spending minus period refunds.

    Linked refunds use the original spending categories, including original
    splits and previous-period spending. Unlinked refunds retain their own
    categories. Negative buckets remain visible. Percentages describe the
    positive category subtotal; negative adjustments have no pie share.
    """
    from models import RefundAllocation, TransactionSplit
    buckets = {}
    zero = Decimal("0")
    gross = sum((Decimal(str(t.amount)) for t in expense_txns), zero)
    refunds = sum((Decimal(str(t.amount)) for t in refund_txns), zero)
    net = (gross - refunds).quantize(Decimal("0.01"))

    def add(category, amount, count=0):
        key = category["id"]
        if key not in buckets:
            buckets[key] = dict(category, amount=zero, count=0)
        buckets[key]["amount"] += amount
        buckets[key]["count"] += count

    def portions(txn, splits, amount):
        native_total = Decimal(str(txn.amount))
        consumed = zero
        if txn.is_split and native_total > 0:
            for split in splits or []:
                native_amount = Decimal(str(split.amount))
                weight = min(max(native_amount, zero), max(native_total - consumed, zero))
                if not weight:
                    continue
                consumed += weight
                yield classify_split_item(split.category_id, split.notes, txn, category_map), amount * weight / native_total
        if consumed < native_total or native_total <= 0:
            weight = (native_total - consumed) / native_total if native_total > 0 else Decimal("1")
            yield classify_transaction(txn, category_map), amount * weight

    for txn in expense_txns:
        for category, amount in portions(txn, (splits_map or {}).get(txn.id, []), Decimal(str(txn.amount))):
            add(category, amount, 1)

    refunds = zero
    for refund in refund_txns:
        remainder = Decimal(str(refund.amount))
        links = []
        if session is not None and allowed_account_ids:
            from services.refund_money import report_offsets
            from services.report_currency import ReportCurrency
            converter = report_money or ReportCurrency(session, currency=refund.currency)
            links, remainder, _, _ = report_offsets(session, refund, allowed_account_ids, converter)
        for original, converted_share in links:
            refunds += converted_share
            original_splits = session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == original.id)).all() if original.is_split else []
            for category, amount in portions(original, original_splits, converted_share):
                add(category, -amount)
        refunds += remainder
        if remainder:
            for category, amount in portions(refund, (splits_map or {}).get(refund.id, []), remainder):
                add(category, -amount)
    net = (gross - refunds).quantize(Decimal("0.01"))

    rows = list(buckets.values())
    for item in rows:
        item["amount"] = item["amount"].quantize(Decimal("0.01"))
    # Preserve the rounded global amount when proportional allocations round.
    difference = net - sum((item["amount"] for item in rows), zero)
    if rows and difference:
        max(rows, key=lambda item: abs(item["amount"]))["amount"] += difference
    rows = [item for item in rows if item["amount"] != 0]
    positive = sum((item["amount"] for item in rows if item["amount"] > 0), zero)
    for item in rows:
        item["percentage"] = round(float(item["amount"] / positive * 100), 1) if item["amount"] > 0 and positive else 0.0
        item["percentage_basis"] = "positive_category_net"
        item["is_refund_credit"] = item["amount"] < 0
        item["amount"] = float(item["amount"])
    rows.sort(key=lambda item: item["amount"], reverse=True)
    if positive:
        rows[0]["percentage"] = round(rows[0]["percentage"] + 100 - sum(item["percentage"] for item in rows), 1)
    return rows, float(net), float(gross.quantize(Decimal("0.01"))), float(refunds.quantize(Decimal("0.01")))


def get_user_report_account_ids(session, user, family_id=None):
    """Report participation is narrower than authorization to read an account."""
    from models import AccountShare
    visible = get_user_visible_account_ids(session, user, family_id)
    if not visible:
        return set()
    included = set(session.exec(select(Account.id).where(Account.id.in_(visible),
                                                        Account.exclude_from_reports == False)).all())
    user_id = getattr(user, 'id', None)
    if user_id:
        hidden = set(session.exec(select(AccountShare.account_id).where(
            AccountShare.user_id == user_id, AccountShare.include_in_finances == False)).all())
        included -= hidden
    return included


def get_report_account_balances(session, accounts, money):
    """Each participating account contributes its own ledger exactly once."""
    from routes.v1_accounts import _calc_raw_account_balance
    from models import Account
    from services.booking_money import master_contribution
    included = {account.id for account in accounts}
    values = {}
    for account in accounts:
        parent = session.get(Account, account.parent_account_id) if account.parent_account_id in included else None
        if parent:
            balance = master_contribution(session, account, parent)
            values[account.id] = float(money.amount(balance, parent.currency))
        else:
            values[account.id] = float(money.amount(_calc_raw_account_balance(session, account.id, financial_classification(account), account.balance), account.currency))
    return values

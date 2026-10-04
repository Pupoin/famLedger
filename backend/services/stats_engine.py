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

# 标准预置分类与关键词映射定义
STANDARD_CATEGORY_DEFS = [
    {
        "id": "cat_dining",
        "name": "餐饮美食",
        "icon": "🍴",
        "color": "#8b5cf6",
        "aliases": ["dining", "food", "餐饮", "餐饮美食"],
        "kws": [
            "餐饮", "烧烤", "拉扎斯", "饿了么", "食欲主义", "鑫牛", "酒家", "小馆",
            "美食", "咖啡", "星巴克", "麦当劳", "肯德基", "厨房", "友宝", "外卖",
            "火锅", "面馆", "团队聚餐", "肉夹馍", "奶茶", "脆皮手枪腿", "海底捞"
        ],
    },
    {
        "id": "cat_groceries",
        "name": "超市便利",
        "icon": "🛒",
        "color": "#10b981",
        "aliases": ["groceries", "supermarket", "超市", "超市便利"],
        "kws": [
            "超市", "生鲜", "好蔬果", "物美", "便利", "果蔬", "买菜", "沃尔玛",
            "山姆", "全家", "罗森", "柒一拾壹", "多点新鲜", "卖场"
        ],
    },
    {
        "id": "cat_utilities",
        "name": "生活缴费",
        "icon": "⚡",
        "color": "#ef4444",
        "aliases": ["utilities", "bills", "生活缴费"],
        "kws": [
            "自来水", "燃气", "供暖", "电费", "电网", "物业", "移动", "联通",
            "电信", "水务", "缴费", "电力", "手机充值"
        ],
    },
    {
        "id": "cat_transport",
        "name": "交通出行",
        "icon": "🚗",
        "color": "#06b6d4",
        "aliases": ["transport", "transportation", "交通", "交通出行"],
        "kws": [
            "高德打车", "滴滴", "地铁", "公交", "铁路", "12306", "打车", "加油",
            "停车", "出行", "中石化", "中石油"
        ],
    },
    {
        "id": "cat_shopping",
        "name": "购物消费",
        "icon": "🛍️",
        "color": "#eab308",
        "aliases": ["shopping", "购物", "购物消费"],
        "kws": [
            "京东", "拼多多", "淘宝", "天猫", "环胜电子", "虞唯", "宽达", "商贸",
            "商行", "数码", "服饰", "唯品会", "淘天物流", "百宝阁"
        ],
    },
    {
        "id": "cat_social",
        "name": "人情往来",
        "icon": "🤝",
        "color": "#0ea5e9",
        "aliases": ["social", "人情往来", "人情随礼", "随礼"],
        "kws": ["微信红包", "红包", "人情", "随礼", "份子钱", "礼金", "赵自宽"],
    },
]

OTHER_CATEGORY_DEF = {
    "id": "cat_other",
    "name": "其他",
    "icon": "🍪",
    "color": "#f97316",
}

NON_INCOME_KWS = ["对账", "期初", "建账", "还款", "转账", "转入", "划转", "借据", "借款"]
NON_EXPENSE_KWS = ["对账", "期初", "建账", "还贷", "放款", "借据", "调账"]


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
    if acc and getattr(acc, "classification", "asset") == "liability":
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


def classify_transaction(t: Transaction, category_map: Dict[uuid.UUID, Category]) -> Dict[str, Any]:
    """统一交易分类归集算法。"""
    # 1. 优先读取数据库外键绑定分类
    if t.category_id and t.category_id in category_map:
        c_db = category_map[t.category_id]
        c_db_name = (c_db.name or "").strip()
        c_db_name_lower = c_db_name.lower()

        # 别名映射到标准分类
        for cdef in STANDARD_CATEGORY_DEFS:
            if cdef["name"] == c_db_name or c_db_name_lower in cdef["aliases"]:
                return {
                    "id": cdef["id"],
                    "name": cdef["name"],
                    "icon": cdef["icon"],
                    "color": cdef["color"],
                }
        # 如果不是标准分类，但明确有自定义分类名（且不是“其他”），则保留自定义分类
        if c_db_name and c_db_name not in ("其他", "Other", "其他支出"):
            return {
                "id": str(c_db.id),
                "name": c_db_name,
                "icon": c_db.icon or "📦",
                "color": getattr(c_db, "color", None) or "#f97316",
            }

    # 2. 文本关键词匹配标准分类
    full_text = (t.narration or "").lower()
    for cdef in STANDARD_CATEGORY_DEFS:
        for kw in cdef["kws"]:
            if kw.lower() in full_text:
                return {
                    "id": cdef["id"],
                    "name": cdef["name"],
                    "icon": cdef["icon"],
                    "color": cdef["color"],
                }

    # 3. 兜底归入“其他”
    return OTHER_CATEGORY_DEF.copy()


def classify_split_item(
    split_cat_id: Optional[uuid.UUID],
    split_notes: Optional[str],
    fallback_txn: Transaction,
    category_map: Dict[uuid.UUID, Category],
) -> Dict[str, Any]:
    """对拆分子项进行分类归集。"""
    if split_cat_id and split_cat_id in category_map:
        c_db = category_map[split_cat_id]
        c_db_name = (c_db.name or "").strip()
        c_db_name_lower = c_db_name.lower()
        for cdef in STANDARD_CATEGORY_DEFS:
            if cdef["name"] == c_db_name or c_db_name_lower in cdef["aliases"]:
                return {
                    "id": cdef["id"],
                    "name": cdef["name"],
                    "icon": cdef["icon"],
                    "color": cdef["color"],
                }
        if c_db_name and c_db_name not in ("其他", "Other", "其他支出"):
            return {
                "id": str(c_db.id),
                "name": c_db_name,
                "icon": c_db.icon or "📦",
                "color": getattr(c_db, "color", None) or "#f97316",
            }

    if split_notes:
        full_text = split_notes.lower()
        for cdef in STANDARD_CATEGORY_DEFS:
            for kw in cdef["kws"]:
                if kw.lower() in full_text:
                    return {
                        "id": cdef["id"],
                        "name": cdef["name"],
                        "icon": cdef["icon"],
                        "color": cdef["color"],
                    }

    return classify_transaction(fallback_txn, category_map)


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
            values[account.id] = float(money.amount(_calc_raw_account_balance(session, account.id, account.classification, account.balance), account.currency))
    return values

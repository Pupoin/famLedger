from services.refund_money import report_offsets, refund_report_summary, spending_refund
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import tempfile
import uuid
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from database import get_session, DATA_DIR
from auth import get_current_user_or_token
from models import Account, Category, Transaction, TransactionSplit, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["v1-budgets"])

BUDGET_CONFIG_DIR = DATA_DIR / "budgets"


def _get_budget_config_file(family_id: Optional[uuid.UUID] = None) -> Path:
    BUDGET_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if family_id:
        return BUDGET_CONFIG_DIR / f"budget_settings_{family_id}.json"
    return BUDGET_CONFIG_DIR / "budget_settings_default.json"


DEFAULT_SETTINGS = {
    "total_budget": 10000.0,
    "expected_income": 20000.0,
    "category_budgets": {
        "餐饮美食": 2500.0,
        "购物消费": 2500.0,
        "超市便利": 1500.0,
        "个人/转账": 800.0,
        "生活缴费": 500.0,
        "交通出行": 400.0,
        "其他": 500.0,
    },
}


def _category_percentages(settings: Dict[str, Any]) -> Dict[str, float]:
    if "category_percentages" in settings:
        return dict(settings["category_percentages"])
    total = Decimal(str(settings.get("total_budget", 0)))
    return {
        name: float((Decimal(str(amount)) * 100 / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if total > 0 else 0.0
        for name, amount in settings.get("category_budgets", {}).items()
    }


def _allocate_category_budgets(total: float, percentages: Dict[str, float]) -> Dict[str, float]:
    # Allocate whole cents and distribute rounding remainders without exceeding the total.
    cents = int((Decimal(str(total)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    raw = {name: Decimal(cents) * Decimal(str(percent)) / 100 for name, percent in percentages.items()}
    allocated = {name: int(amount.to_integral_value(rounding=ROUND_FLOOR)) for name, amount in raw.items()}
    target = int(sum(raw.values(), Decimal(0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    order = sorted(raw, key=lambda name: raw[name] - allocated[name], reverse=True)
    for name in order[:target - sum(allocated.values())]:
        allocated[name] += 1
    return {name: amount / 100 for name, amount in allocated.items()}


def _load_budget_settings(family_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    cfg_file = _get_budget_config_file(family_id)
    # 兼容迁移历史根目录单文件
    legacy_file = Path(__file__).parent.parent / "budget_settings.json"
    old_family_file = Path(__file__).parent.parent / "data" / "budgets" / cfg_file.name
    target_file = cfg_file if cfg_file.exists() else old_family_file if family_id and old_family_file.exists() else None
    if target_file and target_file.exists():
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_SETTINGS, **data}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def _save_budget_settings(settings: Dict[str, Any], family_id: Optional[uuid.UUID] = None):
    cfg_file = _get_budget_config_file(family_id)
    try:
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=cfg_file.parent, delete=False, encoding="utf-8") as tf:
            json.dump(settings, tf, ensure_ascii=False, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, cfg_file)
    except Exception as e:
        logger.error(f"Error saving budget settings: {e}")
        raise HTTPException(status_code=500, detail="保存预算设置失败")


@router.get("/v1/budgets/summary")
def get_budgets_summary(
    month: Optional[str] = Query(default=None, description="Month in YYYY-MM format, default current month"),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    预算管理看板汇总接口（基于真实纯净收支与净额化退款计算）。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    family_id = current_user.family_id if current_user else None
    from models import FamilyBudget
    stored = session.get(FamilyBudget, family_id) if family_id else None
    settings = {**DEFAULT_SETTINGS, **stored.settings} if stored else _load_budget_settings(family_id)

    today = datetime.date.today()
    default_month_str = today.strftime("%Y-%m")
    target_month = month or default_month_str
    try:
        if len(target_month) != 7 or target_month[4] != "-":
            raise ValueError()
        y, m = map(int, target_month.split("-"))
        if not (1 <= y <= 9998 and 1 <= m <= 12):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="月份必须为 YYYY-MM，年份范围 0001—9998")

    start_d = datetime.date(y, m, 1)
    if m == 12:
        end_d = datetime.date(y + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end_d = datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)

    if start_d <= today <= end_d:
        remaining_days = max(1, (end_d - today).days + 1)
    elif today > end_d:
        remaining_days = 0
    else:
        remaining_days = (end_d - start_d).days + 1

    from services.stats_engine import (
        get_user_report_account_ids,
        is_genuine_income,
        is_genuine_expense,
        is_genuine_refund,
        compute_netted_category_distribution,
    )

    active_account_ids = get_user_report_account_ids(session, current_user, family_id=family_id)

    # 查询当月所有有效交易（严格限定于存续有效账户，排除对账调整、期初建账等）
    stmt = select(Transaction).where(
        Transaction.transacted_at >= start_d,
        Transaction.transacted_at <= end_d,
        Transaction.excluded_from_stats == False,
    )
    if not active_account_ids:
        stmt = stmt.where(False)
    else:
        stmt = stmt.where(Transaction.account_id.in_(active_account_ids))

    from services.report_currency import ReportCurrency, persist_fx_cache
    from models import Family
    family = session.get(Family, family_id) if family_id else None
    report_money = ReportCurrency(session, currency=family.currency if family else "CNY", cache_independently=True)
    report_money.account_ids = set(active_account_ids)
    original_txns = session.exec(stmt).all()
    txns = report_money.transactions(original_txns)

    all_accs = session.exec(select(Account)).all()
    all_acc_map = {a.id: a for a in all_accs}
    all_categories = session.exec(select(Category)).all()
    cat_by_id = {c.id: c for c in all_categories}
    family_categories = {c.name: c for c in all_categories if family_id and c.family_id == family_id}

    income_txns = [t for t in txns if is_genuine_income(t, all_acc_map)]
    expense_txns = [t for t in txns if is_genuine_expense(t, all_acc_map)]
    refund_txns = [t for t in txns if is_genuine_refund(t)]

    total_income = round(sum(float(t.amount) for t in income_txns), 2)
    split_txn_ids = [t.id for t in (expense_txns + refund_txns) if t.is_split]
    splits_map = {}
    if split_txn_ids:
        for sp in report_money.splits(session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(split_txn_ids))).all(), original_txns):
            splits_map.setdefault(sp.transaction_id, []).append(sp)

    categories_data, total_spent, total_expense_raw, total_refund = compute_netted_category_distribution(
        expense_txns, refund_txns, cat_by_id, splits_map=splits_map, session=session, allowed_account_ids=set(active_account_ids), report_money=report_money
    )

    # 预算与超支判定
    configured_category_budgets = settings.get("category_budgets", {})
    categories_list = []

    # 将所有计算得到的分类转为 map 方便与预算配置合并
    calc_map = {c["name"]: c for c in categories_data}
    all_cat_names = list(calc_map.keys())
    for cfg_name in configured_category_budgets.keys():
        if cfg_name not in all_cat_names:
            all_cat_names.append(cfg_name)

    cat_spent_map = {}
    for cname in all_cat_names:
        if cname in calc_map:
            cat_spent_map[cname] = {
                "name": cname,
                "icon": calc_map[cname]["icon"],
                "color": calc_map[cname]["color"],
                "spent": calc_map[cname]["amount"],
            }
        else:
            configured_category = family_categories.get(cname)
            cat_spent_map[cname] = {
                "name": cname,
                "icon": (configured_category.icon if configured_category else None) or "📦",
                "color": (configured_category.color if configured_category else None) or "#f97316",
                "spent": 0.0,
            }

    for cname, item in cat_spent_map.items():
        spent = round(item["spent"], 2)
        # 未分配或已移除的分类没有独立限额，避免自动恢复已删除的预算。
        c_budget = float(configured_category_budgets.get(cname, 0.0))
        is_over = spent > c_budget
        over = round(spent - c_budget, 2) if is_over else 0.0
        rem = round(c_budget - spent, 2) if not is_over else 0.0
        progress = max(0.0, round((spent / c_budget * 100), 1)) if c_budget > 0 else (100.0 if spent > 0 else 0.0)
        daily = round((rem / remaining_days), 2) if (remaining_days > 0 and rem > 0) else 0.0

        # 仅展示有消费或有预算的分类
        if spent != 0 or c_budget > 0:
            categories_list.append({
                "name": cname,
                "icon": item["icon"],
                "color": item["color"],
                "spent": spent,
                "budget": c_budget,
                "is_over": is_over,
                "over": over,
                "remaining": rem,
                "remaining_days": remaining_days,
                "daily_suggested": daily,
                "progress": progress,
                "status": "over" if is_over else "normal",
            })

    # 区分超支组与正常组
    over_categories = [c for c in categories_list if c["is_over"]]
    over_categories.sort(key=lambda x: x["over"], reverse=True)

    normal_categories = [c for c in categories_list if not c["is_over"]]
    normal_categories.sort(key=lambda x: x["spent"], reverse=True)

    total_budget = float(settings.get("total_budget", 10000.0))
    expected_income = float(settings.get("expected_income", 20000.0))
    is_total_over = total_spent > total_budget
    total_remaining = round(max(0.0, total_budget - total_spent), 2)
    total_over = round(max(0.0, total_spent - total_budget), 2)
    usage_pct = round((total_spent / total_budget * 100), 1) if total_budget > 0 else 100.0

    persist_fx_cache(session)
    return {
        **report_money.metadata(),
        **refund_report_summary(session, refund_txns, set(active_account_ids), report_money),
        "month": target_month,
        "month_display": f"{y}年{str(m).padStart(2, '0') if hasattr(str(m), 'padStart') else f'{m:02d}'}月",
        "total_budget": total_budget,
        "category_percentages": _category_percentages(settings),
        "category_budgets": configured_category_budgets,
        "total_spent": total_spent,
        "total_remaining": total_remaining,
        "total_over": total_over,
        "is_total_over": is_total_over,
        "usage_pct": usage_pct,
        "expected_income": expected_income,
        "earned_income": total_income,
        "income_diff": round(total_income - expected_income, 2),
        "over_categories": over_categories,
        "normal_categories": normal_categories,
        "all_categories": categories_list,
        "remaining_days": remaining_days,
    }


@router.post("/v1/budgets/settings")
def update_budget_settings(
    payload: Dict[str, Any],
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    保存用户自定义总预算和分类预算配置。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="仅家庭组管理者或系统管理员有权修改预算配置")
    if not current_user.family_id:
        raise HTTPException(status_code=400, detail="您尚未加入家庭组，无法保存家庭预算配置")

    family_id = current_user.family_id
    from models import Family, FamilyBudget
    # Lock an existing stable row even before a budget is first created.
    # SQLite acquires a write lock through the no-op UPDATE; PostgreSQL locks
    # the same family row, so all partial updates follow one locking protocol.
    from sqlalchemy import update
    session.execute(update(Family).where(Family.id == family_id).values(name=Family.name))
    stored = session.get(FamilyBudget, family_id, populate_existing=True)
    current = {**DEFAULT_SETTINGS, **stored.settings} if stored else _load_budget_settings(family_id)
    percentages = _category_percentages(current)
    import math
    if "total_budget" in payload:
        try:
            val = float(payload["total_budget"])
            if not math.isfinite(val) or val < 0:
                raise ValueError()
            current["total_budget"] = val
        except Exception:
            raise HTTPException(status_code=400, detail="预算总额必须为非负有效数值")
    if "expected_income" in payload:
        try:
            val = float(payload["expected_income"])
            if not math.isfinite(val) or val < 0:
                raise ValueError()
            current["expected_income"] = val
        except Exception:
            raise HTTPException(status_code=400, detail="预期收入必须为非负有效数值")
    if "category_budgets" in payload and isinstance(payload["category_budgets"], dict):
        cat_budgets = {}
        for k, v in payload["category_budgets"].items():
            try:
                val = float(v)
                if not math.isfinite(val) or val < 0:
                    raise ValueError()
                cat_budgets[str(k)] = val
            except Exception:
                raise HTTPException(status_code=400, detail=f"分类预算「{k}」必须为非负有效数值")
        current["category_budgets"] = cat_budgets
        current.pop("category_percentages", None)
        percentages = _category_percentages(current)

    if "category_percentages" in payload:
        if not isinstance(payload["category_percentages"], dict):
            raise HTTPException(status_code=400, detail="分类预算比例必须为分类与百分比的映射")
        percentages = {}
        for name, value in payload["category_percentages"].items():
            try:
                if not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > 100 or isinstance(value, bool):
                    raise ValueError()
                percent = Decimal(str(value))
                if not percent.is_finite() or percent < 0 or percent > 100 or percent != percent.quantize(Decimal("0.01")):
                    raise ValueError()
                percentages[name] = float(percent)
            except Exception:
                raise HTTPException(status_code=400, detail=f"分类「{name}」比例必须为 0 至 100 的有效百分比，最多两位小数")
        if sum((Decimal(str(value)) for value in percentages.values()), Decimal(0)) > 100:
            raise HTTPException(status_code=400, detail="分类预算比例合计不能超过 100%")

    current["category_percentages"] = percentages
    current["category_budgets"] = _allocate_category_budgets(current["total_budget"], percentages)

    if stored is None:
        stored = FamilyBudget(family_id=family_id)
    stored.settings = current
    session.add(stored)
    session.commit()
    return {"status": "ok", "settings": current}

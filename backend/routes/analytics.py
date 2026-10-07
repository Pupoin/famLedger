from services.refund_money import report_offsets, refund_report_summary, spending_refund
"""
全面财务统计与全景分析报告 API (纯净生产实现，基于真实 SQLite 交易流水)。
"""

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from database import get_session
from auth import get_current_user_or_token
from models import User
from services.account_types import account_type_is, financial_classification

router = APIRouter()


def _report_user(session, user_or_ctx):
    username = user_or_ctx.get("username") if isinstance(user_or_ctx, dict) else user_or_ctx
    if isinstance(username, str) and not username.startswith("service:"):
        return session.exec(select(User).where(User.username == username)).first()
    return None


@router.get("/v1/analytics/report")
def get_comprehensive_report(
    request: Request,
    period: str = "monthly",
    selected_month: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_history: bool = True,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    全面财务统计报表接口（100% 依据真实 SQLite 交易流水与账户计算，严禁假数据）。
    """
    from models import Transaction, Account, Category

    from services.report_period import resolve_period
    start_d, end_d, prev_start, prev_end, y, m = resolve_period(period, selected_month, start_date, end_date)
    selected_month = f"{y:04d}-{m:02d}"

    # 确定当前用户家庭范围
    user_db = _report_user(session, user_or_ctx)

    family_id = user_db.family_id if user_db else None
    from services.report_currency import ReportCurrency
    report_money = ReportCurrency(session, user_db, cache_independently=True)

    from services.stats_engine import (
        get_user_report_account_ids,
        is_genuine_income,
        is_genuine_expense,
        is_genuine_refund,
        compute_netted_category_distribution,
    )

    active_account_ids = get_user_report_account_ids(session, user_db, family_id=family_id)
    report_money.account_ids = set(active_account_ids)

    # 2. 查询当前周期所有真实流水（严格排除非统计流水，如对账调整、期初存入、放款本金）
    curr_stmt = select(Transaction).where(
        Transaction.transacted_at >= start_d,
        Transaction.transacted_at <= end_d,
        Transaction.excluded_from_stats == False,
    )
    prev_stmt = select(Transaction).where(
        Transaction.transacted_at >= prev_start,
        Transaction.transacted_at <= prev_end,
        Transaction.excluded_from_stats == False,
    )
    if active_account_ids:
        curr_stmt = curr_stmt.where(Transaction.account_id.in_(active_account_ids))
        prev_stmt = prev_stmt.where(Transaction.account_id.in_(active_account_ids))
    else:
        curr_stmt = curr_stmt.where(Transaction.id == None)
        prev_stmt = prev_stmt.where(Transaction.id == None)
    curr_original = session.exec(curr_stmt).all()
    prev_original = session.exec(prev_stmt).all() if period.lower() != "all" else []
    curr_txns = report_money.transactions(curr_original)
    prev_txns = report_money.transactions(prev_original)

    acc_stmt = select(Account).where(Account.id.in_(active_account_ids)) if active_account_ids else select(Account).where(False)
    all_accs = session.exec(acc_stmt).all()
    all_acc_map = {a.id: a for a in all_accs}

    cat_stmt = select(Category)
    if family_id:
        cat_stmt = cat_stmt.where(Category.family_id == family_id)
    else:
        cat_stmt = cat_stmt.where(Category.id == None)
    all_categories = session.exec(cat_stmt).all()
    cat_by_id = {c.id: c for c in all_categories}

    # 3. 计算收支与退款（基于真实纯净业务口径）
    income_txns = [t for t in curr_txns if is_genuine_income(t, all_acc_map)]
    expense_txns = [t for t in curr_txns if is_genuine_expense(t, all_acc_map)]
    refund_txns = [t for t in curr_txns if is_genuine_refund(t)]

    total_income = round(sum(float(t.amount) for t in income_txns), 2)
    curr_split_ids = [t.id for t in (expense_txns + refund_txns) if t.is_split]
    curr_splits_map = {}
    if curr_split_ids:
        splits = [sp for key in curr_split_ids for sp in report_money.read.splits.get(key, [])]
        for sp in report_money.splits(splits, curr_original):
            curr_splits_map.setdefault(sp.transaction_id, []).append(sp)

    categories_data, total_expense, total_expense_raw, total_refund = compute_netted_category_distribution(
        expense_txns, refund_txns, cat_by_id, splits_map=curr_splits_map, session=session, allowed_account_ids=set(active_account_ids), report_money=report_money
    )
    fx_summary = refund_report_summary(session, refund_txns, set(active_account_ids), report_money)
    net_savings = round(total_income - total_expense + fx_summary["fx_gain"] - fx_summary["fx_loss"], 2)
    savings_rate = round((net_savings / total_income * 100), 1) if total_income > 0 else 0.0

    # 上一周期收支计算
    prev_income = round(sum(float(t.amount) for t in prev_txns if is_genuine_income(t, all_acc_map)), 2)
    prev_expense_txns = [t for t in prev_txns if is_genuine_expense(t, all_acc_map)]
    prev_refund_txns = [t for t in prev_txns if is_genuine_refund(t)]
    prev_split_ids = [t.id for t in (prev_expense_txns + prev_refund_txns) if t.is_split]
    prev_splits_map = {}
    if prev_split_ids:
        splits = [sp for key in prev_split_ids for sp in report_money.read.splits.get(key, [])]
        for sp in report_money.splits(splits, prev_original):
            prev_splits_map.setdefault(sp.transaction_id, []).append(sp)

    _, prev_expense, prev_exp_raw, prev_refund = compute_netted_category_distribution(
        prev_expense_txns, prev_refund_txns, cat_by_id, splits_map=prev_splits_map, session=session, allowed_account_ids=set(active_account_ids), report_money=report_money
    )

    income_pct_change = round(((total_income - prev_income) / prev_income * 100), 1) if prev_income > 0 else 0.0
    expense_pct_change = round(((total_expense - prev_expense) / prev_expense * 100), 1) if prev_expense > 0 else 0.0

    # 4. 智能分类汇总（基于统一 stats_engine 计算结果）
    expense_categories = [
        {
            "name": c["name"],
            "count": c["count"],
            "amount": c["amount"],
            "percentage": f"{c['percentage']}%",
            "icon": c["icon"],
        }
        for c in categories_data
    ]

    # 统计收入分类（仅真实外部经营/劳动收入）
    inc_cat_map = {}
    for t in income_txns:
        iname = t.narration or "工资收入"
        if iname not in inc_cat_map:
            inc_cat_map[iname] = {"name": iname, "count": 0, "amount": 0.0, "icon": "💰"}
        inc_cat_map[iname]["count"] += 1
        inc_cat_map[iname]["amount"] += float(t.amount)

    income_categories = []
    base_inc = total_income if total_income > 0 else 1.0
    for iname, item in inc_cat_map.items():
        amt = round(item["amount"], 2)
        pct = round((amt / base_inc) * 100, 1)
        income_categories.append({
            "name": iname,
            "count": item["count"],
            "amount": amt,
            "percentage": f"{pct}%",
            "icon": item["icon"],
        })
    income_categories.sort(key=lambda x: x["amount"], reverse=True)
    if not income_categories:
        income_categories.append({
            "name": "其他收入",
            "count": 0,
            "amount": 0.0,
            "percentage": "0.0%",
            "icon": "💰",
        })

    # 6. 真实账户与净资产（严格限定家庭与用户可见权限，杜绝越权泄露）
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    from services.balance_sheet import visible_balance_accounts
    accounts = visible_balance_accounts(session, user_or_ctx if is_service else user_db)

    cash_accounts = []
    investment_accounts = []
    credit_accounts = []
    loan_accounts = []

    from services.stats_engine import get_report_account_balances
    report_balances = get_report_account_balances(session, accounts, report_money)
    visible_ids = {a.id for a in accounts}
    for a in accounts:
        if a.parent_account_id in visible_ids:
            continue
        # 基于统一单一口径动态严格计算账户当前净额
        final_bal = report_balances[a.id]

        acc_obj = {
            "id": str(a.id),
            "name": a.name,
            "institution": a.institution_name,
            "type": a.account_type,
            "balance": final_bal,
            "icon": (a.institution_name or a.name or "银")[0],
        }

        if financial_classification(a) == "liability":
            if a.account_type.lower() in ("credit_card", "credit", "信用卡"):
                credit_accounts.append(acc_obj)
            else:
                loan_accounts.append(acc_obj)
        elif account_type_is(a.account_type, 'investment'):
            investment_accounts.append(acc_obj)
        else:
            cash_accounts.append(acc_obj)

    total_cash = sum(a["balance"] for a in cash_accounts)
    total_invest = sum(a["balance"] for a in investment_accounts)
    total_assets = round(total_cash + total_invest, 2)

    total_credit = sum(a["balance"] for a in credit_accounts)
    total_loan = sum(a["balance"] for a in loan_accounts)
    total_liabilities = round(total_credit + total_loan, 2)

    current_net_worth = round(total_assets - total_liabilities, 2)

    from services.report_history import build_report_history
    history = build_report_history(session, accounts, active_account_ids, all_acc_map,
                                   report_money, end_d, selected_month) if include_history else None

    from services.report_currency import persist_fx_cache
    persist_fx_cache(session)

    return {
        **report_money.metadata(),
        **fx_summary,
        "history_loaded": include_history,
        "period": period,
        "selected_month": selected_month,
        "date_range": {
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
        },
        "kpis": {
            "total_income": total_income,
            "income_pct_change": income_pct_change,
            "total_expense": total_expense,
            "expense_pct_change": expense_pct_change,
            "net_savings": net_savings,
            "savings_rate": savings_rate,
            "budget_usage_pct": 0,
        },
        "trends": history["trends"] if history else None,
        "activity": {
            "income_categories": income_categories,
            "expense_categories": expense_categories,
            "total_transactions_count": len(curr_txns),
        },
        "net_worth": {
            "current": current_net_worth,
            "assets_total": total_assets,
            "liabilities_total": total_liabilities,
            "cash_total": round(total_cash, 2),
            "invest_total": round(total_invest, 2),
            "credit_total": round(total_credit, 2),
            "loan_total": round(total_loan, 2),
            "trend": history["net_worth"]["trend"] if history else [],
            "trend_basis": "recorded_account_ledger",
            "trend_label": "账户净资产走势（不含个人借贷）",
        },
        "investments": {
            "portfolio_value": round(total_invest, 2),
            "accounts": investment_accounts,
        },
    }


@router.get("/v1/analytics/history")
def get_report_history(
    period: str = "monthly",
    selected_month: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """Load historical curves after the report's current figures are visible."""
    from models import Account
    from services.report_period import resolve_period
    from services.report_currency import ReportCurrency, persist_fx_cache
    from services.stats_engine import get_user_report_account_ids
    from services.balance_sheet import visible_balance_accounts
    from services.report_history import build_report_history

    start_d, end_d, _, _, y, m = resolve_period(period, selected_month, start_date, end_date)
    user_db = _report_user(session, user_or_ctx)
    family_id = user_db.family_id if user_db else None
    report_money = ReportCurrency(session, user_db, cache_independently=True)
    active_ids = get_user_report_account_ids(session, user_db, family_id=family_id)
    report_money.account_ids = set(active_ids)
    all_accs = session.exec(select(Account).where(Account.id.in_(active_ids))).all() if active_ids else []
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith('service:')
    accounts = visible_balance_accounts(session, user_or_ctx if is_service else user_db)
    history = build_report_history(session, accounts, active_ids, {a.id: a for a in all_accs},
                                   report_money, end_d, f'{y:04d}-{m:02d}')
    persist_fx_cache(session)
    return {**report_money.metadata(), **history, 'history_loaded': True,
            'period': period, 'selected_month': f'{y:04d}-{m:02d}',
            'date_range': {'start': start_d.isoformat(), 'end': end_d.isoformat()}}

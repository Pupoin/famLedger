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

router = APIRouter()


@router.get("/v1/analytics/report")
def get_comprehensive_report(
    request: Request,
    period: str = "monthly",
    selected_month: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    全面财务统计报表接口（100% 依据真实 SQLite 交易流水与账户计算，严禁假数据）。
    """
    import datetime
    import calendar
    from models import Transaction, Account, Category, TransactionSplit

    from services.report_period import resolve_period
    start_d, end_d, prev_start, prev_end, y, m = resolve_period(period, selected_month, start_date, end_date)
    selected_month = f"{y:04d}-{m:02d}"

    # 确定当前用户家庭范围
    user_db = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        user_db = session.exec(select(User).where(User.username == user_or_ctx)).first()
    elif isinstance(user_or_ctx, dict):
        user_db = session.exec(select(User).where(User.username == user_or_ctx.get("username"))).first()

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
        Transaction.transacted_at >= start_d.isoformat(),
        Transaction.transacted_at <= end_d.isoformat(),
        Transaction.excluded_from_stats == False,
    )
    prev_stmt = select(Transaction).where(
        Transaction.transacted_at >= prev_start.isoformat(),
        Transaction.transacted_at <= prev_end.isoformat(),
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
        for sp in report_money.splits(session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(curr_split_ids))).all(), curr_original):
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
        for sp in report_money.splits(session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(prev_split_ids))).all(), prev_original):
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

    # 5. 过去若干月真实收支明细
    history_months = []
    curr_m = end_d.replace(day=1)
    m_list = []
    for _ in range(6):
        m_list.append(curr_m)
        curr_m = (curr_m - datetime.timedelta(days=1)).replace(day=1)
    m_list.reverse()

    for hm in m_list:
        if hm.month == 12:
            next_hm = hm.replace(year=hm.year + 1, month=1)
        else:
            next_hm = hm.replace(month=hm.month + 1)
        h_stmt = select(Transaction).where(
            Transaction.transacted_at >= hm.isoformat(),
            Transaction.transacted_at < next_hm.isoformat(),
            Transaction.excluded_from_stats == False,
        )
        if active_account_ids:
            h_stmt = h_stmt.where(Transaction.account_id.in_(active_account_ids))
        else:
            h_stmt = h_stmt.where(Transaction.id == None)
        h_all = report_money.transactions(session.exec(h_stmt).all())

        h_inc = round(sum(float(t.amount) for t in h_all if is_genuine_income(t, all_acc_map)), 2)
        h_exp_raw = round(sum(float(t.amount) for t in h_all if is_genuine_expense(t, all_acc_map)), 2)
        h_refunds = [t for t in h_all if is_genuine_refund(t)]
        h_fx = refund_report_summary(session, h_refunds, set(active_account_ids), report_money)
        h_ref = round(h_fx['spending_refund_amount'], 2)
        h_exp = round(h_exp_raw - h_ref, 2)
        h_net = round(h_inc - h_exp + h_fx['fx_gain'] - h_fx['fx_loss'], 2)
        h_rate = round((h_net / h_inc * 100), 1) if h_inc > 0 else 0.0
        history_months.append({
            "month_label": hm.strftime("%b %Y"),
            "year_month": hm.strftime("%Y-%m"),
            "income": h_inc,
            "expense": h_exp,
            "net": h_net,
            "fx_gain": h_fx['fx_gain'],
            "fx_loss": h_fx['fx_loss'],
            "savings_rate": f"{h_rate}%",
            "is_current": hm.strftime("%Y-%m") == selected_month,
        })

    # 计算 6 个月的月均值
    avg_income = round(sum(h["income"] for h in history_months) / len(history_months), 2)
    avg_expense = round(sum(h["expense"] for h in history_months) / len(history_months), 2)
    avg_savings = round(sum(h["net"] for h in history_months) / len(history_months), 2)

    # 6. 真实账户与净资产（严格限定家庭与用户可见权限，杜绝越权泄露）
    from routes.v1_accounts import get_account_realtime_balance

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")

    if not family_id:
        accounts = []
    else:
        all_fam_accs = session.exec(
            select(Account).where(Account.family_id == family_id, Account.is_active == True)
        ).all()
        from services.stats_engine import get_user_report_account_ids
        vis_ids = get_user_report_account_ids(session, user_or_ctx if is_service else user_db, family_id=family_id)
        accounts = [a for a in all_fam_accs if a.id in vis_ids]

    cash_accounts = []
    investment_accounts = []
    credit_accounts = []
    loan_accounts = []

    from services.stats_engine import get_report_account_balances
    report_balances = get_report_account_balances(session, accounts, report_money)
    for a in accounts:
        # 基于统一单一口径动态严格计算账户当前净额
        final_bal = report_balances[a.id]

        acc_obj = {
            "id": str(a.id),
            "name": a.name,
            "institution": a.institution_name or "招商银行",
            "type": a.account_type,
            "balance": final_bal,
            "icon": (a.institution_name or a.name or "银")[0],
        }

        if a.classification == "liability" or a.account_type in ("credit_card", "loan"):
            if a.account_type == "loan" or "贷款" in a.name:
                loan_accounts.append(acc_obj)
            else:
                credit_accounts.append(acc_obj)
        elif a.account_type in ("investment", "brokerage", "mutual_fund") or "理财" in a.name or "证券" in a.name or "基金" in a.name or "投资" in a.name:
            investment_accounts.append(acc_obj)
        else:
            cash_accounts.append(acc_obj)

    # Both overview and reports include the same authorized outstanding debts.
    from services.balance_sheet import debt_accounts, ledger_net_worth_history
    for debt in debt_accounts(session, user_db):
        amount = float(report_money.amount(debt.balance, debt.currency))
        entry = {"id": str(debt.id), "name": debt.name, "institution": debt.institution_name,
                 "type": debt.account_type, "balance": amount, "icon": "债"}
        (loan_accounts if debt.classification == 'liability' else cash_accounts).append(entry)

    total_cash = sum(a["balance"] for a in cash_accounts)
    total_invest = sum(a["balance"] for a in investment_accounts)
    total_assets = round(total_cash + total_invest, 2)

    total_credit = sum(a["balance"] for a in credit_accounts)
    total_loan = sum(a["balance"] for a in loan_accounts)
    total_liabilities = round(total_credit + total_loan, 2)

    current_net_worth = round(total_assets - total_liabilities, 2)

    # Reconstruct actual account balances; subtracting monthly income/spending
    # from today's balance loses openings, adjustments, FX and refund cash.
    cutoffs = [(h['month_label'], min(date.today(), end_d,
                date.fromisoformat(h['year_month'] + '-01').replace(
                    day=calendar.monthrange(int(h['year_month'][:4]), int(h['year_month'][5:]))[1])))
               for h in history_months]
    net_worth_trend = ledger_net_worth_history(session, accounts, report_money, cutoffs)

    from services.report_currency import persist_fx_cache
    persist_fx_cache(session)

    return {
        **report_money.metadata(),
        **refund_report_summary(session, refund_txns, set(active_account_ids), report_money),
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
        "trends": {
            "monthly_breakdown": history_months,
            "averages": {
                "income": avg_income,
                "expense": avg_expense,
                "savings": avg_savings,
            },
        },
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
            "trend": net_worth_trend,
            "trend_basis": "recorded_account_ledger",
            "trend_label": "账户净资产走势（不含个人借贷）",
        },
        "investments": {
            "portfolio_value": round(total_invest, 2),
            "accounts": investment_accounts,
        },
    }

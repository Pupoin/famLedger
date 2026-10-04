from services.refund_money import report_offsets, refund_report_summary, spending_refund
import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlmodel import Session, select

from database import get_session
from auth import get_current_user_or_token
from models import Account, Category, Family, PersonalDebt, Transaction, TransactionSplit, User

router = APIRouter(tags=["v1-dashboard"])


@router.get("/v1/dashboard/summary")
def get_dashboard_summary(
    request: Request,
    period: str = Query(default="monthly", description="Time period: monthly, quarterly, ytd, 6m, custom, MTD, 30D, YTD, ALL"),
    selected_month: Optional[str] = Query(default=None, description="Selected month formatted as YYYY-MM"),
    start_date: Optional[str] = Query(default=None, description="Start date for custom period (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(default=None, description="End date for custom period (YYYY-MM-DD)"),
    account_id: Optional[str] = Query(default=None),
    user_filter: Optional[str] = Query(default=None, alias="user", description="Filter by user username/id or '全部'"),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    Returns complete dashboard aggregates matching Sure layout:
    - Cashflow Sankey data
    - Outflows donut & category ranking
    - Balance sheet summary
    - Merchant Treemap & ranking
    - Spending heatmap calendar
    - Investment total
    """
    # 1. Resolve current user name & family members
    current_user_name = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user_name = user_or_ctx
    elif isinstance(user_or_ctx, dict):
        current_user_name = user_or_ctx.get("username")

    user_db = None
    if current_user_name:
        user_db = session.exec(select(User).where(User.username == current_user_name)).first()

    if not user_db:
        # 服务端 Key 情况下找第一个拥有 family 的用户或首个有效用户
        user_db = session.exec(select(User).where(User.family_id != None)).first()

    current_user = user_db.username if user_db else (current_user_name or "user")
    display_name = user_db.display_name if user_db and user_db.display_name else current_user

    # Fetch family members
    family_id = user_db.family_id if user_db else None

    family_members = []
    if family_id:
        all_m = session.exec(select(User).where(User.family_id == family_id)).all()
        for m in all_m:
            family_members.append({
                "id": str(m.id),
                "username": m.username,
                "display_name": m.display_name or m.username,
                "is_current": m.username == current_user,
            })

    # 2. Determine allowed and filtered accounts
    from models import AccountShare
    shares = session.exec(select(AccountShare)).all()
    user_shares = {s.account_id: s for s in shares if user_db and s.user_id == user_db.id}

    from services.stats_engine import (
        get_family_active_account_ids,
        is_genuine_income,
        is_genuine_expense,
        is_genuine_refund,
        compute_netted_category_distribution,
    )

    family_active_ids = get_family_active_account_ids(session, family_id)
    all_family_accounts = session.exec(
        select(Account).where(Account.id.in_(family_active_ids)) if family_active_ids else select(Account).where(False)
    ).all()

    # Permissions filter for current user: 严格基于自己拥有或他人授权共享，杜绝越权
    visible_accounts = []
    for a in all_family_accounts:
        is_my_acc = user_db and a.owner_id == user_db.id
        sh = user_shares.get(a.id)
        if (is_my_acc or sh or (user_db and user_db.role == "admin")) and not a.exclude_from_reports and (not sh or sh.include_in_finances):
            visible_accounts.append(a)

    # If user_filter is given (e.g. 'alice', 'qq', or a user uuid) and not '全部'/'ALL'
    target_user_obj = None
    if user_filter and user_filter not in ("全部", "ALL", "all", ""):
        for m in (all_m if family_id else []):
            if m.username == user_filter or m.display_name == user_filter or str(m.id) == user_filter:
                target_user_obj = m
                break

    if target_user_obj:
        active_accounts = [a for a in visible_accounts if a.owner_id == target_user_obj.id]
    else:
        active_accounts = visible_accounts

    active_account_ids = [a.id for a in active_accounts]

    from services.report_period import resolve_period
    start_date, end_date, _, _, y, m = resolve_period(period, selected_month, start_date, end_date)
    from services.report_currency import ReportCurrency
    report_money = ReportCurrency(session, user_db, cache_independently=True)
    report_money.account_ids = set(active_account_ids)

    # 3. Query transactions within period (scoped strictly to valid accounts)
    txn_stmt = select(Transaction).where(
        Transaction.transacted_at >= start_date.isoformat(),
        Transaction.transacted_at <= end_date.isoformat(),
        Transaction.excluded_from_stats == False,
    )
    real_account_id = None
    if isinstance(account_id, str) and account_id.strip():
        try:
            real_account_id = uuid.UUID(account_id.strip())
        except Exception:
            pass

    if real_account_id:
        if real_account_id not in active_account_ids:
            txn_stmt = txn_stmt.where(False)
        else:
            txn_stmt = txn_stmt.where(Transaction.account_id == real_account_id)
    elif active_account_ids:
        txn_stmt = txn_stmt.where(Transaction.account_id.in_(active_account_ids))
    else:
        txn_stmt = txn_stmt.where(False)

    original_txns = session.exec(txn_stmt).all()
    txns = report_money.transactions(original_txns)

    all_acc_map = {a.id: a for a in all_family_accounts}
    all_categories = session.exec(select(Category)).all()
    cat_by_id = {c.id: c for c in all_categories}

    # 4. Use unified stats_engine functions
    from services.stats_engine import (
        is_genuine_income,
        is_genuine_expense,
        is_genuine_refund,
        compute_netted_category_distribution,
    )

    expense_txns = [t for t in txns if is_genuine_expense(t, all_acc_map)]
    income_txns = [t for t in txns if is_genuine_income(t, all_acc_map)]
    refund_txns = [t for t in txns if is_genuine_refund(t)]

    total_income_raw = sum(float(t.amount) for t in income_txns)
    total_net_income = round(total_income_raw, 2)

    split_txn_ids = [t.id for t in (expense_txns + refund_txns) if t.is_split]
    splits_map = {}
    if split_txn_ids:
        all_splits = session.exec(
            select(TransactionSplit).where(TransactionSplit.transaction_id.in_(split_txn_ids))
        ).all()
        for sp in report_money.splits(all_splits, original_txns):
            splits_map.setdefault(sp.transaction_id, []).append(sp)

    categories_data, total_net_expense, total_expense_raw, total_refund_raw = compute_netted_category_distribution(
        expense_txns, refund_txns, cat_by_id, splits_map=splits_map, session=session, allowed_account_ids=set(active_account_ids), report_money=report_money
    )

    # 4.2 Outflow by Account from real expense transactions (净额化扣除账户退款)
    all_accs = session.exec(select(Account)).all()
    acc_map = {a.id: a for a in all_accs}

    acc_buckets = {}
    ACC_PALETTE = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4"]
    for t in expense_txns:
        a_obj = acc_map.get(t.account_id)
        if a_obj:
            aname = a_obj.name or a_obj.institution_name or '银行卡'
            ext = getattr(a_obj, 'external_identifier', None)
            if ext and str(ext)[-4:] not in aname:
                aname = f"{aname} {str(ext)[-4:]}"
        else:
            aname = "默认主账户"
        aid = str(t.account_id) if t.account_id else "default_acc"
        if aid not in acc_buckets:
            idx = len(acc_buckets)
            acc_buckets[aid] = {
                "id": aid,
                "account_id": aid,
                "name": aname,
                "icon": "💳",
                "color": ACC_PALETTE[idx % len(ACC_PALETTE)],
                "amount": 0.0,
            }
        acc_buckets[aid]["amount"] += float(t.amount)

    for r in refund_txns:
        links, remainder, _, _ = report_offsets(session, r, set(active_account_ids), report_money)
        for source, value in links + [(r, remainder)]:
            if not value:
                continue
            aid = str(source.account_id)
            if aid not in acc_buckets:
                account = acc_map.get(source.account_id)
                acc_buckets[aid] = {"id": aid, "account_id": aid, "name": account.name if account else "退款账户",
                    "icon": "💳", "color": ACC_PALETTE[len(acc_buckets) % len(ACC_PALETTE)], "amount": 0.0}
            acc_buckets[aid]["amount"] -= float(value)

    accounts_outflow_data = []
    base_sum = sum(max(0, item["amount"]) for item in acc_buckets.values()) or 1.0
    for aid, ainfo in acc_buckets.items():
        if ainfo["amount"] != 0:
            ainfo["amount"] = round(ainfo["amount"], 2)
            ainfo["percentage"] = round((max(0, ainfo["amount"]) / base_sum) * 100, 1)
            accounts_outflow_data.append(ainfo)
    accounts_outflow_data.sort(key=lambda x: x["amount"], reverse=True)

    # If no transactions found, keep clean empty states without fake fallbacks
    if not categories_data:
        categories_data = []

    if not accounts_outflow_data:
        accounts_outflow_data = []

    adjustments = []
    if total_refund_raw > 0:
        adjustments.append({
            "name": "退款冲抵（已计入净额）",
            "amount": -round(total_refund_raw, 2),
            "hint": "以下账户本期退款已从总支出中真实冲抵扣除"
        })

    # 5. Cashflow Sankey model (Real Income Categories -> Cashflow Pool -> Real Expense Destinations)
    real_income_sources = []
    if income_txns:
        inc_cat_buckets = {}
        for it in income_txns:
            cat = cat_by_id.get(it.category_id)
            cname = cat.name if cat else "其他收入"
            cicon = cat.icon if (cat and cat.icon) else "💰"
            ccolor = cat.color if (cat and cat.color) else None
            cid = str(cat.id) if cat else f"cat_{hash(cname)}"

            if cid not in inc_cat_buckets:
                inc_cat_buckets[cid] = {
                    "id": cid,
                    "name": cname,
                    "amount": 0.0,
                    "icon": cicon,
                    "color": ccolor,
                }
            inc_cat_buckets[cid]["amount"] += float(it.amount)

        INC_PALETTE = ["#10b981", "#0d9488", "#0284c7", "#6366f1", "#8b5cf6", "#f59e0b", "#eab308"]
        sorted_incomes = sorted(inc_cat_buckets.values(), key=lambda x: x["amount"], reverse=True)
        for idx, inc_item in enumerate(sorted_incomes):
            if not inc_item["color"]:
                inc_item["color"] = INC_PALETTE[idx % len(INC_PALETTE)]
            inc_item["amount"] = round(inc_item["amount"], 2)
            real_income_sources.append(inc_item)
    elif total_net_income > 0:
        real_income_sources = [
            {"id": "inc_salary", "name": "收入汇总", "amount": round(total_net_income, 2), "icon": "💰", "color": "#10b981"}
        ]
    else:
        real_income_sources = []

    sankey_data = {
        "income_sources": real_income_sources,
        "pool": {
            "name": "Cash Flow",
            "amount": round(total_net_expense, 2) if total_net_expense > 0 else 0.0,
            "color": "#10A861",
        },
        "expense_destinations": [
            {
                "name": cat["name"],
                "amount": cat["amount"],
                "icon": cat["icon"],
                "color": cat["color"],
            }
            for cat in categories_data if cat["amount"] > 0
        ],
    }

    # 6. Merchant Spending (TreeMap & Top 10 Ranking from real transactions)
    merchant_counts = {}
    merchant_amounts = {}
    for t in expense_txns:
        mname = t.narration or "其他"
        merchant_counts[mname] = merchant_counts.get(mname, 0) + 1
        merchant_amounts[mname] = merchant_amounts.get(mname, 0.0) + float(t.amount)

    sorted_merchants = sorted(merchant_amounts.items(), key=lambda x: x[1], reverse=True)
    ranking_data = []
    for rank_idx, (mname, amt) in enumerate(sorted_merchants[:10], start=1):
        cnt = merchant_counts[mname]
        ranking_data.append({
            "rank": rank_idx,
            "name": mname,
            "count": cnt,
            "average": round(amt / cnt, 2) if cnt > 0 else round(amt, 2),
            "amount": round(amt, 2),
        })

    # Treemap (Top merchants + Other)
    grid_placements = [
        ("1 / 1 / 5 / 4", "bg-red-100/70 dark:bg-red-950/30", "border-red-200 dark:border-red-900/50"),
        ("1 / 4 / 4 / 6", "bg-orange-100/70 dark:bg-orange-950/30", "border-orange-200 dark:border-orange-900/50"),
        ("1 / 6 / 4 / 7", "bg-emerald-100/70 dark:bg-emerald-950/30", "border-emerald-200 dark:border-emerald-900/50"),
        ("4 / 4 / 7 / 5", "bg-red-50/70 dark:bg-red-950/20", "border-red-200 dark:border-red-900/40"),
        ("4 / 5 / 7 / 7", "bg-orange-50/70 dark:bg-orange-950/20", "border-orange-200 dark:border-orange-900/40"),
        ("5 / 1 / 7 / 2", "bg-emerald-50/70 dark:bg-emerald-950/20", "border-emerald-200 dark:border-emerald-900/40"),
        ("5 / 2 / 7 / 3", "bg-zinc-50 dark:bg-zinc-800/60", "border-zinc-200 dark:border-zinc-700"),
    ]
    treemap_data = []
    other_sum = 0.0
    for idx, (mname, amt) in enumerate(sorted_merchants):
        if idx < len(grid_placements):
            placement, bg, border = grid_placements[idx]
            treemap_data.append({
                "name": mname,
                "amount": round(amt, 2),
                "placement": placement,
                "bg": bg,
                "border": border,
            })
        else:
            other_sum += amt

    if other_sum > 0:
        treemap_data.append({
            "name": "其他",
            "is_other": True,
            "amount": round(other_sum, 2),
            "placement": "5 / 3 / 7 / 4",
            "bg": "bg-zinc-50 dark:bg-zinc-800/60",
            "border": "border-zinc-200 dark:border-zinc-700",
        })

    # Calendar and trend share the exact authorized, period-filtered ledger
    # used by cashflow and outflows. Whole-week padding contains no activity.
    calendar_start = start_date
    if start_date == datetime.date.min:
        calendar_start = min((t.transacted_at for t in original_txns), default=end_date)
    cal_start = calendar_start - datetime.timedelta(days=calendar_start.weekday())
    cal_end = end_date
    cal_end_week = end_date + datetime.timedelta(days=6 - end_date.weekday())
    all_cal_txns = expense_txns + refund_txns

    daily_spend = {}
    daily_names = {}
    for activity in all_cal_txns:
        tat, ttype, tname = activity.transacted_at, activity.transaction_type, activity.narration
        amt = spending_refund(session, activity, set(active_account_ids), report_money) if ttype == "refund" else activity.amount
        if isinstance(tat, datetime.date):
            tat_str = tat.isoformat()
        else:
            tat_str = str(tat)
        if ttype == "expense":
            daily_spend[tat_str] = daily_spend.get(tat_str, 0.0) + float(amt)
            if tname:
                daily_names.setdefault(tat_str, []).append(tname)
        elif ttype == "refund":
            daily_spend[tat_str] = daily_spend.get(tat_str, 0.0) - float(amt)
            if tname:
                daily_names.setdefault(tat_str, []).append(f"退款: {tname}")

    # 计算 Sure 风格分位数阈值
    positive_spends = sorted([v for v in daily_spend.values() if v > 0])
    if positive_spends:
        n = len(positive_spends)
        q1 = positive_spends[int(n * 0.25)]
        q2 = positive_spends[int(n * 0.50)]
        q3 = positive_spends[int(n * 0.75)]
        thresholds = [q1, q2, q3]
    else:
        thresholds = [50.0, 150.0, 300.0]

    # Build weeks array (Monday to Sunday = 7 rows)
    weeks = []
    curr = cal_start
    while curr <= cal_end_week:
        week_days = []
        for _ in range(7):
            d_str = curr.isoformat()
            if d_str in daily_spend:
                amt = daily_spend[d_str]
                is_refund = amt < 0
                if amt == 0:
                    level = 0
                elif amt < 0:
                    level = 2
                elif amt <= thresholds[0]:
                    level = 1
                elif amt <= thresholds[1]:
                    level = 2
                elif amt <= thresholds[2]:
                    level = 3
                else:
                    level = 4
            else:
                amt = 0.0
                level = 0
                is_refund = False

            names_for_day = daily_names.get(d_str, [])
            desc = names_for_day[0] if names_for_day else ""

            week_days.append({
                "date": d_str,
                "amount": round(amt, 2),
                "level": level,
                "is_refund": is_refund,
                "outside": curr > end_date or curr < calendar_start,
                "description": desc,
            })
            curr += datetime.timedelta(days=1)
        weeks.append(week_days)

    # Independent 6/12-month trend, ending in the selected period's month.
    # The summary below still follows the top-level period selection.
    from services.report_period import month_shift
    last_month = end_date.replace(day=1)
    earliest_month = month_shift(last_month, -11)
    next_month = month_shift(last_month, 1)
    trend_stmt = select(Transaction).where(
        Transaction.transacted_at >= earliest_month.isoformat(),
        Transaction.transacted_at < next_month.isoformat(),
        Transaction.excluded_from_stats == False,
    )
    if real_account_id:
        trend_stmt = trend_stmt.where(Transaction.account_id == real_account_id,
                                      Transaction.account_id.in_(active_account_ids))
    elif active_account_ids:
        trend_stmt = trend_stmt.where(Transaction.account_id.in_(active_account_ids))
    else:
        trend_stmt = trend_stmt.where(False)

    trend_buckets = {}
    for activity in session.exec(trend_stmt).all():
        if is_genuine_income(activity, all_acc_map):
            kind, amount = "income", report_money.ledger_amount(activity)
        elif is_genuine_expense(activity, all_acc_map):
            kind, amount = "expense", report_money.ledger_amount(activity)
        elif is_genuine_refund(activity):
            kind, amount = "expense", -spending_refund(session, activity, set(active_account_ids), report_money)
        else:
            continue
        ym = activity.transacted_at.strftime("%Y-%m")
        bucket = trend_buckets.setdefault(ym, {"income": Decimal(0), "expense": Decimal(0)})
        bucket[kind] += amount

    m_bars = []
    for offset in range(12):
        month = month_shift(earliest_month, offset)
        bucket = trend_buckets.get(month.strftime("%Y-%m"), {"income": Decimal(0), "expense": Decimal(0)})
        m_bars.append({
            "month": f"{month.month}月",
            "year_month": month.strftime("%Y年%m月"),
            "ym": month.strftime("%Y-%m"),
            "start_date": month.isoformat(),
            "end_date": (month_shift(month, 1) - datetime.timedelta(days=1)).isoformat(),
            "income": float(round(bucket["income"], 2)),
            "expense": float(round(bucket["expense"], 2)),
        })

    # Balance Sheet from DB accounts with real-time transaction balance verification
    from services.stats_engine import get_report_account_balances
    acc_list = [a for a in active_accounts if a.is_active]
    from services.balance_sheet import debt_accounts
    personal_debts = debt_accounts(session, user_db, target_user_obj.id if target_user_obj else None)
    debt_ids = {a.id for a in personal_debts}
    acc_list += personal_debts
    realtime_map = get_report_account_balances(session, acc_list, report_money)
    user_map = {u.id: (u.display_name or u.username) for u in session.exec(select(User)).all()}

    import re

    def build_account_obj(a, class_total):
        bal = realtime_map.get(a.id, float(a.balance or 0))
        weight = round(bal / class_total * 100, 1) if class_total > 0 else 0.0
        mask_m = re.search(r"(\d{4})", a.name or "")
        mask = mask_m.group(1) if mask_m else "0000"
        return {
            "id": str(a.id),
            "record_type": "personal_debt" if a.id in debt_ids else "account",
            "name": a.name,
            "mask": mask,
            "account_type": a.account_type,
            "classification": a.classification,
            "institution_name": a.institution_name or "中国招商银行",
            "owner": user_map.get(a.owner_id, display_name or "当前用户"),
            "balance": round(bal, 2),
            "weight": weight,
        }

    asset_accs = [a for a in acc_list if a.classification == "asset"]
    liab_accs = [a for a in acc_list if a.classification == "liability"]

    # 报表只累计各参与账户自身活动；卡片详情的合并账单不参与重复累加。
    total_assets = round(sum(realtime_map.get(a.id, float(a.balance or 0)) for a in asset_accs), 2)
    total_liabilities = round(sum(realtime_map.get(a.id, 0) for a in liab_accs), 2)
    net_worth = round(total_assets - total_liabilities, 2)

    # Color maps
    TYPE_COLORS = {
        "活期储蓄": "#10b981",
        "借据": "#06b6d4",
        "投资理财": "#6366f1",
        "信用卡": "#f97316",
        "贷款": "#ef4444",
        "其他": "#8b5cf6",
    }
    TYPE_NAMES = {
        "checking": "活期储蓄",
        "savings": "活期储蓄",
        "iou": "借据",
        "receivable": "借据",
        "loan_receivable": "借据",
        "借据": "借据",
        "investment": "投资理财",
        "credit_card": "信用卡",
        "loan": "贷款",
        "other": "其他",
    }
    INST_COLORS = {
        "中国招商银行": "#ea580c",
        "招商银行": "#ea580c",
        "中国银行": "#2563eb",
        "贷款": "#ef4444",
        "支付宝": "#0284c7",
        "微信支付": "#16a34a",
    }
    FALLBACK_COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"]

    def group_accounts(accounts, group_by_field, class_total):
        groups_dict = {}
        for a in accounts:
            if group_by_field == "type":
                g_key = TYPE_NAMES.get(a.account_type, "活期储蓄")
            else:
                g_key = a.institution_name or "其他机构"
            if g_key not in groups_dict:
                groups_dict[g_key] = []
            groups_dict[g_key].append(a)

        res = []
        for idx, (gname, g_accs) in enumerate(groups_dict.items()):
            # 分类/银行分组按活动所属账户归集。
            g_total = round(sum(realtime_map.get(acc.id, 0.0) for acc in g_accs), 2)
            g_weight = round(g_total / class_total * 100, 1) if class_total > 0 else 0.0
            if group_by_field == "type":
                color = TYPE_COLORS.get(gname, FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])
            else:
                color = INST_COLORS.get(gname, FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])
            acc_objs = [build_account_obj(acc, class_total) for acc in g_accs]
            acc_objs.sort(key=lambda x: x["balance"], reverse=True)
            res.append({
                "name": gname,
                "color": color,
                "total": g_total,
                "weight": g_weight,
                "accounts": acc_objs,
            })
        res.sort(key=lambda x: x["total"], reverse=True)
        return res

    balance_sheet_data = {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
        "currency_symbol": report_money.symbol,
        "by_type": {
            "assets": {
                "name": "资产",
                "total": total_assets,
                "groups": group_accounts(asset_accs, "type", total_assets),
            },
            "liabilities": {
                "name": "负债",
                "total": total_liabilities,
                "groups": group_accounts(liab_accs, "type", total_liabilities),
            },
        },
        "by_institution": {
            "assets": {
                "name": "资产",
                "total": total_assets,
                "groups": group_accounts(asset_accs, "institution", total_assets),
            },
            "liabilities": {
                "name": "负债",
                "total": total_liabilities,
                "groups": group_accounts(liab_accs, "institution", total_liabilities),
            },
        },
    }

    # Real investment calculation based on visible active asset accounts
    INVESTMENT_KEYWORDS = ("理财", "证券", "基金", "投资", "股票", "朝朝宝", "余额宝")
    total_investment = round(
        sum(
            realtime_map.get(a.id, float(a.balance or 0))
            for a in asset_accs
            if (
                a.account_type in ("investment", "brokerage", "mutual_fund", "投资理财")
                or any(k in (a.name or "") for k in INVESTMENT_KEYWORDS)
            )
        ),
        2,
    )

    from services.report_currency import persist_fx_cache
    persist_fx_cache(session)

    fx_summary = refund_report_summary(session, refund_txns, set(active_account_ids), report_money)
    return {
        **report_money.metadata(),
        **fx_summary,
        "user_name": display_name,
        "family_members": family_members,
        "selected_user": user_filter or "全部",
        "period": period,
        "selected_month": f"{y}-{str(m).zfill(2)}",
        "period_dates": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "cashflow": sankey_data,
        "outflows": {
            "total": total_net_expense,
            "currency_symbol": report_money.symbol,
            "categories": categories_data,
            "by_account": accounts_outflow_data,
            "adjustments": adjustments,
        },
        "balance_sheet": balance_sheet_data,
        "merchants": {
            "treemap": treemap_data,
            "ranking": ranking_data,
        },
        "spending_calendar": {
            "start_date": calendar_start.strftime("%Y年%m月%d日"),
            "end_date": cal_end.strftime("%Y年%m月%d日"),
            "weeks": weeks,
            "period_dates": {"start": calendar_start.isoformat(), "end": end_date.isoformat()},
        },
        "money_in_out": {
            "period_label": f"{start_date.strftime('%Y年%m月%d日')} 至 {end_date.strftime('%Y年%m月%d日')}",
            "period_dates": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "month_label": end_date.strftime("%Y年%m月"),
            "balance": round(total_income_raw - total_net_expense + fx_summary['fx_gain'] - fx_summary['fx_loss'], 2),
            "income": round(total_income_raw, 2) if total_income_raw > 0 else total_net_income,
            "expenses": total_net_expense,
            "last_6_months": m_bars[-6:],
            "last_12_months": m_bars,
        },
        "investment": {
            "total": total_investment,
            "currency_symbol": report_money.symbol,
        },
    }

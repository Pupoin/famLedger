"""Historical report sections, computed independently of current-period KPIs."""
import calendar
import datetime
from datetime import date

from sqlmodel import select
from models import Transaction
from services.refund_money import refund_report_summary
from services.stats_engine import is_genuine_income, is_genuine_expense, is_genuine_refund
from services.balance_sheet import ledger_net_worth_history


def build_report_history(session, accounts, active_account_ids, all_acc_map, report_money, end_d, selected_month):
    # 5. 过去若干月真实收支明细
    history_months = []
    curr_m = end_d.replace(day=1)
    m_list = []
    for _ in range(6):
        m_list.append(curr_m)
        curr_m = (curr_m - datetime.timedelta(days=1)).replace(day=1)
    m_list.reverse()

    last_month = m_list[-1]
    after_history = (last_month.replace(year=last_month.year + 1, month=1) if last_month.month == 12
                     else last_month.replace(month=last_month.month + 1))
    history_stmt = select(Transaction).where(Transaction.account_id.in_(active_account_ids) if active_account_ids else False,
        Transaction.transacted_at >= m_list[0], Transaction.transacted_at < after_history,
        Transaction.excluded_from_stats == False)
    history_rows = report_money.transactions(session.exec(history_stmt).all())
    history_buckets = {}
    for row in history_rows:
        history_buckets.setdefault(row.transacted_at.replace(day=1), []).append(row)

    for hm in m_list:
        h_all = history_buckets.get(hm, [])

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

    # Reconstruct actual account balances; subtracting monthly income/spending
    # from today's balance loses openings, adjustments, FX and refund cash.
    cutoffs = [(h['month_label'], min(date.today(), end_d,
                date.fromisoformat(h['year_month'] + '-01').replace(
                    day=calendar.monthrange(int(h['year_month'][:4]), int(h['year_month'][5:]))[1])))
               for h in history_months]
    net_worth_trend = ledger_net_worth_history(session, accounts, report_money, cutoffs)

    return {
        "trends": {
            "monthly_breakdown": history_months,
            "averages": {
                "income": avg_income,
                "expense": avg_expense,
                "savings": avg_savings,
            },
        },
        "net_worth": {
            "trend": net_worth_trend,
            "trend_basis": "recorded_account_ledger",
            "trend_label": "账户净资产走势（不含个人借贷）",
        },
    }

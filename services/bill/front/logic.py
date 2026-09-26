import os
import json
import math
import re
import calendar
from functools import lru_cache
from datetime import date, datetime, timedelta
from decimal import Decimal
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Any
import psycopg
from psycopg.rows import dict_row

# --- Configuration & DB ---
@dataclass
class Config:
    pg_dsn: str

def load_standalone_config():
    # Attempt to load from environment or fallback
    dsn = os.getenv("POSTGRES_DSN", "postgresql://postgres:postgres@localhost:5432/personal_cost")
    return Config(pg_dsn=dsn)

def get_connection(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn)

def fetch_records_in_range(conn, start_dt, end_dt):
    sql = 'SELECT id, costtime AS "costTime", cost, account, behaviour, business, remain, source, remark, original_cost AS "originalCost", original_currency AS "originalCurrency" FROM "CMB_bill" WHERE costtime >= %s AND costtime < %s ORDER BY costtime ASC'
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (start_dt, end_dt))
        return list(cur.fetchall())

def fetch_latest_balance(conn, account="6061"):
    sql = 'SELECT remain FROM "CMB_bill" WHERE account = %s AND remain IS NOT NULL AND remain <> \'\' ORDER BY costtime DESC LIMIT 1'
    with conn.cursor() as cur:
        cur.execute(sql, (account,))
        row = cur.fetchone()
    return Decimal(str(row[0])) if row else Decimal("0")

# --- Analytics Logic ---
from backend.ingest.stats import FinanceStats as DashboardStats, build_stats

# --- Core Helper Logic ---
CATEGORY_RULES_FILE = Path("/app/data/category_rules.json")
USER_CONFIG_FILE = Path("/app/data/user_config.json")

def load_user_config():
    default_config = {
        "my_accounts": "6061|9085",
        "wife_accounts": "8567|7661"
    }
    if not USER_CONFIG_FILE.exists():
        return default_config
    try:
        with USER_CONFIG_FILE.open("r", encoding="utf-8") as f:
            return {**default_config, **json.load(f)}
    except:
        return default_config

def save_user_config(config):
    USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with USER_CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

@lru_cache(maxsize=1)
def _load_category_rules():
    if not CATEGORY_RULES_FILE.exists(): return []
    with CATEGORY_RULES_FILE.open("r", encoding="utf-8") as f:
        raw_rules = json.load(f)
    compiled_rules = []
    for item in raw_rules:
        category = str(item.get("category", "")).strip()
        emoji = str(item.get("emoji", "🧾")).strip() or "🧾"
        patterns = item.get("patterns", [])
        if not category or not isinstance(patterns, list): continue
        compiled_patterns = []
        for pattern in patterns:
            try: compiled_patterns.append(re.compile(str(pattern), re.IGNORECASE))
            except re.error: continue
        if compiled_patterns:
            compiled_rules.append({"category": category, "emoji": emoji, "patterns": compiled_patterns})
    return compiled_rules

def _clean_merchant_name(merchant: str) -> str:
    clean_name = merchant
    clean_name = re.sub(r'^[【\[\(]', '', clean_name)
    clean_name = re.sub(r'[】\]\)]$', '', clean_name)
    clean_name = clean_name.replace('】', '').replace('【', '')
    prefixes = ['支付宝', '财付通', '微信支付', '银联', '云闪付扫码', '云闪付', '网银在线', '京东支付', '美团支付', '美团', '抖音支付']
    while True:
        found = False
        for p in prefixes:
            if clean_name.startswith(p + '-'):
                clean_name = clean_name[len(p)+1:]
                found = True
        if not found: break
    clean_name = re.sub(r'^(消费|理财|转账|退款)-+', '', clean_name)
    return clean_name.strip()

def _category_of_business(merchant, compiled_rules):
    cleaned_merchant = _clean_merchant_name(merchant)
    target_to_match = cleaned_merchant if cleaned_merchant else merchant
    best_category = "其他"
    max_match_len = -1
    for rule in compiled_rules:
        category_name = str(rule['category'])
        for pattern in rule['patterns']:
            match = pattern.search(target_to_match)
            if match:
                match_len = len(match.group(0))
                if match_len > max_match_len:
                    max_match_len = match_len
                    best_category = category_name
    return best_category

def _emoji_of_category(category: str) -> str:
    for rule in _load_category_rules():
        if str(rule["category"]) == category: return str(rule.get("emoji", "🧾"))
    return "🧾"

def _spend_signed_series(df: pd.DataFrame) -> pd.Series:
    cost = pd.to_numeric(df.get("cost_float", 0), errors="coerce").fillna(0.0)
    behaviour = df.get("behaviour", "").astype(str)
    business = df.get("business", "").astype(str)
    
    # 1. 识别标记为“退”或“撤”的记录（通常为正数，代表资金回流）
    is_refund = behaviour.str.contains("退|撤", na=False)
    
    # 2. 识别溢缴款部分
    is_overpayment = business.str.contains("溢缴款领回", na=False)

    # 3. 核心逻辑：
    # - 非退款且小于 0 的金额：正常支出
    # - 所有带“退”字的金额：作为冲抵（如果是正数则减小支出绝对值，如果是负数则增加，符合账单逻辑）
    # - 排除溢缴款
    result = cost.where((~is_refund & (cost < 0)) | is_refund, 0.0)
    result = result.mask(is_overpayment, 0.0)
    
    return result

def _total_spend(df: pd.DataFrame) -> float:
    if df.empty: return 0.0
    return -(float(_spend_signed_series(df).sum()))

def _fmt(value: float) -> str: return f"{value:,.2f}"
def _round2(value: float) -> float: return round(float(value), 2)

def _build_hover_records_html(records: pd.DataFrame, *, max_rows: int = 20) -> str:
    if records.empty: return "暂无明细"
    sortable = records.copy()
    spend_amount = pd.to_numeric(sortable.get("spend_signed"), errors="coerce").fillna(0.0).abs()
    cost_amount = pd.to_numeric(sortable.get("cost_float"), errors="coerce").fillna(0.0).abs()
    sortable["hover_amount"] = spend_amount.where(spend_amount > 0, cost_amount)
    rows = sortable.sort_values("hover_amount", ascending=False).head(max_rows).sort_values("costTime", ascending=False) if max_rows > 0 else sortable.sort_values("costTime", ascending=False)
    lines = [f"{pd.to_datetime(row.get('costTime')).strftime('%m-%d %H:%M')} · {row.get('behaviour', '')} · ¥{_fmt(abs(float(row.get('hover_amount', 0.0))))} · {row.get('business', '') or '未命名商户'}" for _, row in rows.iterrows()]
    if len(records) > len(rows): lines.append(f"… 其余 {len(records) - len(rows)} 条")
    return "<br>".join(lines)

# --- Sankey Builder (GUARANTEED UNIQUE NODES) ---
def build_sankey_context(
    *,
    df: pd.DataFrame,
    sankey_category_labels: list[str]
) -> dict[str, Any]:
    account_series = df["accountName"].astype(str).str.strip()
    # Unique and sorted account values
    middle_nodes = sorted(list(set([v for v in account_series.unique().tolist() if v and str(v).lower() != "nan"])))
    if not middle_nodes: middle_nodes = ["其他账户"]
    if account_series.isna().any() or (account_series == "").any():
        if "其他账户" not in middle_nodes: middle_nodes.append("其他账户")

    sankey_outcome_df = df.loc[df["cost_float"] < 0].copy()
    right_category_totals = sankey_outcome_df.assign(category=sankey_outcome_df["category"].astype(str)).groupby("category")["spend_signed"].sum().abs().to_dict()
    
    # Critical Fix: Ensure right nodes are unique
    valid_right_nodes = sorted(list(set([c for c in sankey_category_labels if float(right_category_totals.get(c, 0.0)) > 0])))
    right_nodes = sorted(valid_right_nodes, key=lambda c: float(right_category_totals.get(c, 0.0)), reverse=True)

    source, target, value = [], [], []
    link_business, link_time, link_is_placeholder = [], [], []
    left_to_middle_amounts, middle_to_right_amounts = {}, {}

    income_rows = df.loc[df["cost_float"] > 0]
    left_income_rows = income_rows.copy() #.loc[income_rows["behaviour"].astype(str).str.contains("退|入|撤", na=False)].copy()
    left_income_rows["behaviour_name"] = left_income_rows["behaviour"].astype(str).str.strip()
    left_income_rows = left_income_rows.loc[left_income_rows["behaviour_name"] != ""]

    left_totals_raw = left_income_rows.groupby("behaviour_name")["cost_float"].apply(lambda s: float(s.astype(float).abs().sum())).to_dict()
    # Unique left nodes
    visible_left_nodes = sorted(list(set([n for n, a in left_totals_raw.items() if float(a) > 0])))
    left_nodes = visible_left_nodes + [""]

    left_key_map = {l: f"L::{l}" for l in left_nodes if l}
    middle_key_map = {l: f"M::{l}" for l in middle_nodes}
    right_key_map = {l: f"R::{l}" for l in right_nodes}
    placeholder_left_key = "L::__placeholder__"

    sankey_keys = [*[left_key_map[l] for l in left_nodes if l], placeholder_left_key, *[middle_key_map[l] for l in middle_nodes], *[right_key_map[l] for l in right_nodes]]
    idx = {key: i for i, key in enumerate(sankey_keys)}
    display_by_key = {**{key: label for label, key in left_key_map.items()}, placeholder_left_key: "", **{key: label for label, key in middle_key_map.items()}, **{key: label for label, key in right_key_map.items()}}

    left_records_map = {node: left_income_rows.loc[left_income_rows["behaviour_name"] == node] for node in visible_left_nodes}
    left_totals = {node: float(left_records_map.get(node, pd.DataFrame())["cost_float"].astype(float).abs().sum()) for node in visible_left_nodes}

    for _, row in income_rows.iterrows():
        beh = str(row.get("behaviour", "")).strip()
        beh_key = left_key_map.get(beh)
        if not beh_key: continue
        ctr = str(row.get("accountName", "")).strip() or "其他账户"
        ctr_key = middle_key_map.get(ctr, middle_key_map.get("其他账户"))
        source.append(idx[beh_key]); target.append(idx[ctr_key])
        amt = abs(float(row["cost_float"]))
        value.append(amt); left_to_middle_amounts[(beh_key, ctr_key)] = left_to_middle_amounts.get((beh_key, ctr_key), 0.0) + amt
        link_business.append(str(row.get("business", "") or "未命名商户"))
        link_time.append(pd.to_datetime(row.get("costTime")).strftime("%Y-%m-%d %H:%M:%S"))
        link_is_placeholder.append(False)

    for _, row in sankey_outcome_df.iterrows():
        ctr = str(row.get("accountName", "")).strip() or "其他账户"
        cat = str(row["category"])
        if cat not in right_key_map: continue
        ctr_key = middle_key_map.get(ctr, middle_key_map.get("其他账户"))
        right_key = right_key_map[cat]
        source.append(idx[ctr_key]); target.append(idx[right_key])
        amt = abs(float(row["spend_signed"]))
        value.append(amt); middle_to_right_amounts[(ctr_key, right_key)] = middle_to_right_amounts.get((ctr_key, right_key), 0.0) + amt
        link_business.append(str(row.get("business", "") or "未命名商户"))
        link_time.append(pd.to_datetime(row.get("costTime")).strftime("%Y-%m-%d %H:%M:%S"))
        link_is_placeholder.append(False)

    incoming_to_middle = {name: 0 for name in middle_nodes}
    for s_i, t_i in zip(source, target):
        sk, tk = sankey_keys[s_i], sankey_keys[t_i]
        if sk in left_key_map.values() and tk in middle_key_map.values():
            incoming_to_middle[display_by_key[tk]] += 1

    for acc_l, in_c in incoming_to_middle.items():
        if in_c == 0 and acc_l in middle_key_map:
            source.append(idx[placeholder_left_key]); target.append(idx[middle_key_map[acc_l]])
            value.append(1e-12); link_business.append(""); link_time.append(""); link_is_placeholder.append(True)

    right_records_map = {str(c): sankey_outcome_df.loc[sankey_outcome_df["category"].astype(str) == str(c)] for c in right_nodes}
    right_totals = {str(c): float(g.get("spend_signed", pd.Series(dtype=float)).astype(float).sum()) for c, g in right_records_map.items()}

    # Column Sums
    sum_left_total = sum(left_totals.values())
    sum_right_total = abs(sum(right_totals.values()))
    
    # Middle column sum: sum of total volume (in+out) through each account node
    sum_middle_total = 0.0
    mid_node_value_map = {}
    for disp in middle_nodes:
        # The node value in Sankey is the max of incoming or outgoing. 
        # Here we use total outflow handled + any incoming not immediately spent if we want to be exact, 
        # but the request is "sum of nodes in that column".
        v = abs(float(df[df["accountName"].astype(str).str.strip() == disp]["spend_signed"].sum()))
        mid_node_value_map[disp] = v
        sum_middle_total += v

    def _build_click_json(df_in, nodeLocation='right'):
        if df_in.empty: return {"records": []}
        df_p = df_in.copy()
        if "cost_float" in df_p.columns and nodeLocation == 'left': df_p["amount"] = df_p["cost_float"].astype(float)
        elif "spend_signed" in df_p.columns: df_p = df_p[df_p["spend_signed"] != 0].copy(); df_p["amount"] = df_p["spend_signed"]
        else: df_p["amount"] = pd.to_numeric(df_p.get("cost_float", 0), errors="coerce").fillna(0.0)
        
        # Filter out absolute zero amounts
        df_p = df_p[df_p["amount"] != 0.0].copy()
        if df_p.empty: return {"records": []}

        df_p['time'] = pd.to_datetime(df_p['costTime']).dt.strftime("%Y-%m-%d %H:%M").fillna("-")
        df_p['behaviour'] = df_p['behaviour'].fillna("").astype(str)
        df_p['business'] = df_p['business'].fillna("未命名商户").replace("", "未命名商户").astype(str)
        df_p['amount'] = df_p['amount'].fillna(0.0).astype(float)
        df_p['remark'] = df_p.get('remark', pd.Series(dtype=str)).fillna("").astype(str)
        df_p['id'] = df_p.get('id', pd.Series(dtype=int)).fillna(0).astype(int)
        return {"records": df_p[['id', 'time', 'behaviour', 'business', 'amount', 'remark']].to_dict(orient='records')}

    echarts_palette = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#6e7074', '#bfcbd9', '#d48265', '#749f83', '#ca8622', '#2f4554', '#61a0a8', '#c23531', '#7f7f7f']
    node_colors = {}
    for i, key in enumerate(sankey_keys):
        disp = display_by_key.get(key, "")
        if disp and disp not in node_colors: node_colors[disp] = echarts_palette[i % len(echarts_palette)]

    node_hover_details, node_click_data, node_total_map, node_side_map, node_percent_map = {}, {}, {}, {}, {}
    for key in sankey_keys:
        disp = display_by_key.get(key, "")
        if key in left_key_map.values():
            e = [(display_by_key.get(mk, mk), a) for (lk, mk), a in left_to_middle_amounts.items() if lk == key]
            node_hover_details[key] = f"去向中间节点占比<br>" + "<br>".join([f"{n}: {(a/max(sum(x[1] for x in e),1)*100):.1f}%" for n, a in sorted(e, key=lambda x:x[1], reverse=True)[:6]])
            node_click_data[key] = _build_click_json(left_records_map.get(disp, pd.DataFrame()), 'left')
            node_total_map[key] = float(left_totals.get(disp, 0.0))
            node_percent_map[key] = (node_total_map[key] / sum_left_total * 100) if sum_left_total > 0 else 0.0
            node_side_map[key] = "left"
        elif key in right_key_map.values():
            e = [(display_by_key.get(mk, mk), a) for (mk, rk), a in middle_to_right_amounts.items() if rk == key]
            node_hover_details[key] = f"来自中间节点占比<br>" + "<br>".join([f"{n}: {(a/max(sum(x[1] for x in e),1)*100):.1f}%" for n, a in sorted(e, key=lambda x:x[1], reverse=True)[:6]])
            node_click_data[key] = _build_click_json(right_records_map.get(disp, pd.DataFrame()))
            node_total_map[key] = float(right_totals.get(disp, 0.0))
            node_percent_map[key] = (abs(node_total_map[key]) / sum_right_total * 100) if sum_right_total > 0 else 0.0
            node_side_map[key] = "right"
        elif key in middle_key_map.values():
            fl = [(display_by_key.get(lk, lk), a) for (lk, mk), a in left_to_middle_amounts.items() if mk == key]
            tr = [(display_by_key.get(rk, rk), a) for (mk, rk), a in middle_to_right_amounts.items() if mk == key]
            node_hover_details[key] = f"来自左节点占比<br>" + "<br>".join([f"{n}: {(a/max(sum(x[1] for x in fl),1)*100):.1f}%" for n, a in sorted(fl, key=lambda x:x[1], reverse=True)[:3]]) + "<br><br>去向右节点占比<br>" + "<br>".join([f"{n}: {(a/max(sum(x[1] for x in tr),1)*100):.1f}%" for n, a in sorted(tr, key=lambda x:x[1], reverse=True)[:3]])
            mid_df = df[df["accountName"].astype(str).str.strip()==disp].copy()
            node_click_data[key] = _build_click_json(mid_df)
            net = mid_node_value_map.get(disp, 0.0)
            node_total_map[key] = net
            node_percent_map[key] = (net / sum_middle_total * 100) if sum_middle_total > 0 else 0.0
            node_side_map[key] = "middle"
        else: node_hover_details[key] = "暂无明细"; node_click_data[key] = {"records": []}; node_total_map[key] = 0.0; node_percent_map[key] = 0.0; node_side_map[key] = "middle"

    sankey_option = {
        "series": [{
            "type": "sankey", "layout": "none", "nodeAlign": "left", "nodeGap": 16, "draggable": False, "top": 40, "bottom": 50, "sort": "descending",
            "data": [{"name": k, "display": display_by_key.get(k, ""), "detail": node_hover_details.get(k, "暂无明细"), "click_html": node_click_data.get(k), "total": node_total_map.get(k), "side": node_side_map.get(k, "middle"), "percent": node_percent_map.get(k), "itemStyle": {"color": node_colors.get(display_by_key.get(k, ""), "#ccc")}} for k in sankey_keys],
            "links": [{"source": sankey_keys[si], "target": sankey_keys[ti], "value": float(v), "lineStyle": {"color": "transparent" if is_p else "source", "opacity": 0.2}, "business": biz, "cost_time": ct} for si, ti, v, biz, ct, is_p in zip(source, target, value, link_business, link_time, link_is_placeholder)],
        }]
    }
    return {"sankey_option": sankey_option, "sankey_chart_height": max(520, 120 + max(len(left_nodes), len(middle_nodes), len(right_nodes), 1) * 34)}

# --- Calendar Heatmap ---
def build_heatmap_data(df, start_dt, end_dt):
    outcome_df = df.loc[~df["behaviour"].astype(str).str.contains("入", na=False)].copy()
    outcome_df["day"] = outcome_df["costTime"].dt.strftime("%Y-%m-%d")
    daily_net = outcome_df.groupby("day")["spend_signed"].sum().to_dict()
    daily_detail = {day: _build_hover_records_html(group, max_rows=0) for day, group in outcome_df.groupby("day")}

    all_days = pd.date_range(start_dt.date(), (end_dt - timedelta(days=1)).date(), freq="D")
    max_daily_abs = max((abs(float(v)) for v in daily_net.values()), default=0.0)
    max_log_amount = math.log1p(max_daily_abs) if max_daily_abs > 0 else 0.0

    first_week_start = pd.Timestamp(start_dt.date()) - timedelta(days=start_dt.weekday())
    week_count = ((pd.Timestamp(end_dt.date()) - first_week_start).days // 7) + 1
    
    heat_values = []
    for day in all_days:
        week_idx = int((day - first_week_start).days // 7)
        weekday_idx = int(day.weekday())
        day_str = day.strftime("%Y-%m-%d")
        
        amount = float(daily_net.get(day_str, 0.0))
        sign = 1.0 if amount > 0 else (-1.0 if amount < 0 else 0.0)
        scaled = sign * (math.log1p(abs(amount)) / max_log_amount) if max_log_amount > 0 else 0.0
        
        detail = daily_detail.get(day_str, "暂无明细")
        amt_txt = f"{'+' if amount>0 else ''}{_fmt(amount)}"
        direction = "退款/入账" if amount > 0 else ("支出" if amount < 0 else "无变动")
        tooltip = f"日期: {day_str} · 净额: {amt_txt} ({direction})<br>{detail}"
        heat_values.append([week_idx, weekday_idx, float(scaled), tooltip, int(day.day)])

    month_starts = pd.date_range(start_dt.replace(day=1), end_dt, freq="MS")
    x_labels = [""] * week_count
    for ms in month_starts:
        pos = int((ms - first_week_start).days // 7)
        if 0 <= pos < week_count:
            x_labels[pos] = f"{ms.year}年\n{ms.month}月" if ms.month in [1, 4, 7, 10] or ms == month_starts[0] else f"{ms.month}月"

    return {"values": heat_values, "x_labels": x_labels}

# --- Consumption Trend ---
def build_trend_data(df, granularity="按日", axis_mode="自动（默认）"):
    if df.empty: return {"labels": [], "values": [], "use_log": False}
    
    trend_df = df.copy()
    trend_df["costTime"] = pd.to_datetime(trend_df["costTime"])
    
    if granularity == "按周":
        # W-MON means Week starting Monday
        trend_data = trend_df.resample('W-MON', on='costTime')["spend_signed"].sum().reset_index()
        trend_data["label"] = trend_data["costTime"].dt.strftime("%Y-%m-%d") + " (周)"
    elif granularity == "按月":
        trend_data = trend_df.resample('MS', on='costTime')["spend_signed"].sum().reset_index()
        trend_data["label"] = trend_data["costTime"].dt.strftime("%Y-%m")
    else:
        trend_data = trend_df.assign(day=trend_df["costTime"].dt.strftime("%Y-%m-%d")).groupby("day", as_index=False)["spend_signed"].sum()
        trend_data["label"] = trend_data["day"]

    trend_data["bar_value"] = trend_data["spend_signed"].astype(float)
    trend_data["outcome_float"] = trend_data["bar_value"].abs()
    
    negative_trend = trend_data.loc[trend_data["bar_value"] < 0, "bar_value"]
    auto_use_log_axis = False
    if len(negative_trend) > 2:
        min_val = float(negative_trend.min())
        others = negative_trend.drop(negative_trend.idxmin())
        others_mean = float(others.mean()) if len(others) > 0 else 0.0
        # If the largest spend is > 10x the mean of others, use log
        auto_use_log_axis = others_mean < 0 and min_val < (others_mean * 10)

    if axis_mode == "自动（默认）":
        use_log_axis = auto_use_log_axis
    else:
        use_log_axis = (axis_mode == "Log")

    values_json = []
    for _, row in trend_data.iterrows():
        v = float(row["outcome_float"])
        s = 1 if row["bar_value"] > 0 else -1
        c = "#dc2626" if row["bar_value"] < 0 else "#3b82f6"
        values_json.append({
            "value": _round2(v),
            "itemStyle": {"color": c},
            "sign": s
        })

    return {
        "labels": trend_data["label"].tolist(),
        "values": values_json,
        "use_log": use_log_axis,
        "granularity": granularity
    }

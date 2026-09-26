import os
import sys
import json
from pathlib import Path
from datetime import datetime, date, timedelta
import pandas as pd
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# Add project root to sys.path for backend imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logic import (
    load_standalone_config, get_connection, fetch_records_in_range, fetch_latest_balance, build_stats,
    build_sankey_context, build_heatmap_data, _load_category_rules, _category_of_business, _total_spend,
    _spend_signed_series, _emoji_of_category, _fmt, _round2, _build_hover_records_html, build_trend_data,
    CATEGORY_RULES_FILE, load_user_config, save_user_config
)
from backend.auth.graph_auth import initiate_device_code_login, complete_device_code_login
from backend.auth.state import load_auth_state
from backend.ingest.config import load_config

class DashboardEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, dict) and "__js_code__" in obj: return obj
        if isinstance(obj, (datetime, date)): return obj.isoformat()
        return super().default(obj)

app = FastAPI(title="CMB Bill Dashboard (Full Clone)")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_path = static_dir / "index.html"
    return index_path.read_text(encoding="utf-8") if index_path.exists() else "<h1>Not Found</h1>"

def _build_click_json_internal(df_in, nodeLocation='right'):
    if df_in.empty: return {"records": []}
    df_p = df_in.copy()
    # Ensure amount is absolute for display in table, but preserve original sign if needed? 
    # Usually users want to see the actual number.
    if "spend_signed" in df_p.columns:
        df_p["amount"] = df_p["spend_signed"]
    else:
        df_p["amount"] = df_p["cost_float"].astype(float)
    
    # Filter out 0.0 amounts
    df_p = df_p[df_p["amount"] != 0.0].copy()
    
    if df_p.empty: return {"records": []}

    df_p['time'] = pd.to_datetime(df_p['costTime']).dt.strftime("%Y-%m-%d %H:%M").fillna("-")
    df_p['behaviour'] = df_p['behaviour'].fillna("").astype(str)
    df_p['business'] = df_p['business'].fillna("未命名商户").replace("", "未命名商户").astype(str)
    df_p['amount'] = df_p['amount'].fillna(0.0).astype(float)
    df_p['remark'] = df_p.get('remark', pd.Series(dtype=str)).fillna("").astype(str)
    df_p['id'] = df_p.get('id', pd.Series(dtype=int)).fillna(0).astype(int)
    return {"records": df_p[['id', 'time', 'behaviour', 'business', 'amount', 'remark']].to_dict(orient='records')}

@app.get("/api/data_version")
def get_data_version():
    cfg = load_standalone_config()
    with get_connection(cfg.pg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*), COALESCE(MAX(id), 0) FROM "CMB_bill"')
            count, last_id = cur.fetchone()
    return {"version": f"{count}:{last_id}"}


@app.get("/api/dashboard")
async def get_dashboard_data(start: str, end: str, mode: str = "按月", trend_mode: str = "自动（默认）", trend_gran: str = "按日"):
    try:
        qs = datetime.strptime(start, "%Y-%m-%d")
        qe = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
    except: return JSONResponse({"error": "Invalid date"}, 400)

    cfg = load_standalone_config()
    try:
        with get_connection(cfg.pg_dsn) as conn:
            rows = fetch_records_in_range(conn, qs, qe)
            balance = fetch_latest_balance(conn)
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

    df = build_stats(rows, current_balance=balance, now=qe).detail_df.copy()
    if df.empty: return {"empty": True}

    df["cost_float"] = df["cost"].apply(float)
    df["behaviour"] = df["behaviour"].astype(str)
    df["spend_signed"] = _spend_signed_series(df)
    rules = _load_category_rules()
    df["category"] = df["business"].astype(str).apply(_category_of_business, compiled_rules=rules)
    df["pool"] = df["remain"].apply(lambda v: "借记卡" if pd.notna(v) and str(v).strip() != "" else "信用卡")
    df["accountName"] = df["pool"] + df["account"].astype(str)

    # Basic Metrics
    curr_out = _total_spend(df)
    credit_df, debit_df = df[df["pool"]=="信用卡"].copy(), df[df["pool"]=="借记卡"].copy()
    
    user_cfg = load_user_config()
    my_accounts = user_cfg.get("my_accounts", "6061|9085")
    wife_accounts = user_cfg.get("wife_accounts", "8567|7661")

    credit_sum = credit_df.groupby("accountName").agg(
        refund=("cost_float", lambda s: s[(s>0) & credit_df.loc[s.index, "behaviour"].astype(str).str.contains("退", na=False)].sum()),
        out=("cost_float", lambda s: _total_spend(credit_df.loc[s.index]))
    ).reset_index()
    debit_sum = debit_df.groupby("accountName").agg(
        in_val=("cost_float", lambda s: s[(s>0) & debit_df.loc[s.index, "behaviour"].astype(str).str.contains("入", na=False)].sum()),
        refund=("cost_float", lambda s: s[(s>0) & debit_df.loc[s.index, "behaviour"].astype(str).str.contains("退", na=False)].sum()),
        out=("cost_float", lambda s: _total_spend(debit_df.loc[s.index])),
        latestRemain=("costTime", lambda s: debit_df.loc[s.index].sort_values("costTime", ascending=False).iloc[0]["remain"] if not s.empty else "")
    ).reset_index()

    # CSV detail uses every database record in the selected interval and keeps
    # the original cost sign/value. Dashboard-only spend normalization must not
    # alter or filter exported ledger data.
    interval_records = df.sort_values("costTime", ascending=False)
    detail_table = [{
        "time": r["costTime"].strftime("%Y-%m-%d %H:%M:%S"), "account": str(r["account"]),
        "category": f"{_emoji_of_category(r['category'])} {r['category']}",
        "behaviour": str(r["behaviour"]), "business": str(r["business"]),
        "amount": float(r["cost"]), "source": str(r["source"])
    } for _, r in interval_records.iterrows()]

    # --- Refactored Nested Pie Logic ---
    neg_palette = ["#e11d48", "#f97316", "#fbbf24", "#be123c", "#7c2d12", "#9f1239", "#ea580c"]
    pos_palette = ["#1d4ed8", "#10b981", "#0891b2", "#4338ca", "#34d399", "#6d28d9", "#0ea5e9"]

    def build_nested_pie_data(grouped_series, full_df=None, groupby_col=None):
        inner, outer = [], []
        # Calculate totals for inner ring: Expenses vs Refunds
        neg_rows = grouped_series[grouped_series < 0]
        if not neg_rows.empty:
            neg_total = abs(float(neg_rows.sum()))
            inner.append({"name": "净支出", "value": _round2(neg_total), "itemStyle": {"color": "#be123c"}})
            for i, (name, val) in enumerate(neg_rows.sort_values().items()):
                node_data = {
                    "name": str(name), "value": _round2(abs(float(val))),
                    "itemStyle": {"color": neg_palette[i % len(neg_palette)], "borderColor": "#fff", "borderWidth": 1}
                }
                # Attach ALL records for this category/account (including refunds if any within this slice)
                if full_df is not None and groupby_col is not None:
                    # Filter original df by name and where it contributes to spend_signed
                    # Actually, if it's "Net Spend", we just show everything for that category
                    node_data["click_html"] = _build_click_json_internal(full_df[full_df[groupby_col].astype(str) == str(name)])
                outer.append(node_data)
        
        pos_rows = grouped_series[grouped_series > 0]
        if not pos_rows.empty:
            pos_total = float(pos_rows.sum())
            inner_data_pos = {"name": "净退款", "value": _round2(pos_total), "itemStyle": {"color": "#1e40af"}}
            inner.append(inner_data_pos)
            for i, (name, val) in enumerate(pos_rows.sort_values(ascending=False).items()):
                node_data = {
                    "name": str(name), "value": _round2(float(val)),
                    "itemStyle": {"color": pos_palette[i % len(pos_palette)], "borderColor": "#fff", "borderWidth": 1}
                }
                if full_df is not None and groupby_col is not None:
                    node_data["click_html"] = _build_click_json_internal(full_df[full_df[groupby_col].astype(str) == str(name)])
                outer.append(node_data)
        return inner, outer

    acc_grouped = df.groupby("accountName")["spend_signed"].sum()
    acc_inner, acc_outer = build_nested_pie_data(acc_grouped, full_df=df, groupby_col="accountName")

    cat_grouped = df.groupby("category")["spend_signed"].sum()
    cat_inner, cat_outer = build_nested_pie_data(cat_grouped, full_df=df, groupby_col="category")

    # Response Object
    content = {
        "metrics": {"total_out": _fmt(curr_out), "credit_out": _fmt(_total_spend(credit_df)), "debit_out": _fmt(_total_spend(debit_df)), "my_out": _fmt(_total_spend(df[df["accountName"].astype(str).str.contains(my_accounts)])), "wife_out": _fmt(_total_spend(df[df["accountName"].astype(str).str.contains(wife_accounts)]))},
        "charts": {
            "sankey": build_sankey_context(df=df, sankey_category_labels=[str(r["category"]) for r in rules]+["其他"]),
            "heatmap": build_heatmap_data(df, qs, qe),
            "acc_summary": {"credit": credit_sum.to_dict(orient="records"), "debit": debit_sum.to_dict(orient="records")},
            "acc_pie": {"inner": acc_inner, "outer": acc_outer},
            "cat_pie": {"inner": cat_inner, "outer": cat_outer},
            "trend": build_trend_data(df, granularity=trend_gran, axis_mode=trend_mode)
        },
        "filters": {
            "categories": sorted(df["category"].dropna().unique().tolist()),
            "accounts": sorted([str(a) for a in df["account"].unique() if a and str(a).lower() != 'nan'])
        },
        "feed": [{
            "id": int(r.get("id", 0)), "remark": str(r.get("remark", "")),
            "emoji": _emoji_of_category(r["category"]), "business": r["business"], "behaviour": r["behaviour"],
            "time_str": r["costTime"].strftime("%Y-%m-%d %H:%M:%S"), "account": r["account"], "category": r["category"],
            "amount": float(r["cost_float"]), "spend_signed": float(r["spend_signed"]),
            "date": r["costTime"].strftime("%Y-%m-%d")
        } for _, r in df.sort_values("costTime", ascending=False).iterrows()],
        "detail_table": detail_table
    }
    return JSONResponse(json.loads(json.dumps(content, cls=DashboardEncoder)))

@app.get("/api/config")
async def get_user_config():
    return load_user_config()

@app.post("/api/config")
async def save_user_config_api(request: Request):
    try:
        data = await request.json()
        save_user_config(data)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 400)

@app.get("/api/categories")
async def get_categories():
    if not CATEGORY_RULES_FILE.exists(): return []
    try:
        return json.loads(CATEGORY_RULES_FILE.read_text(encoding="utf-8"))
    except: return []

@app.post("/api/categories")
async def save_categories(request: Request):
    try:
        data = await request.json()
        CATEGORY_RULES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _load_category_rules.cache_clear()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 400)

class RemarkUpdate(BaseModel):
    remark: str

@app.post("/api/remark/{tx_id}")
async def update_remark(tx_id: int, payload: RemarkUpdate):
    cfg = load_standalone_config()
    try:
        with get_connection(cfg.pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE "CMB_bill" SET remark = %s WHERE id = %s', (payload.remark, tx_id))
            conn.commit()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

@app.get("/api/auth/status")
async def get_auth_status():
    return load_auth_state()

def _bg_auth_task(flow, cfg):
    try:
        complete_device_code_login(
            tenant_id=str(cfg.tenant_id),
            client_id=str(cfg.client_id),
            scopes=tuple(cfg.graph_scopes),
            token_cache_path=cfg.token_cache_path,
            flow=flow,
            timeout_seconds=int(flow.get("expires_in") or 900),
        )
    except Exception: pass

@app.post("/api/auth/initiate")
async def initiate_auth(background_tasks: BackgroundTasks):
    try:
        cfg = load_config()
        flow = initiate_device_code_login(
            tenant_id=cfg.tenant_id,
            client_id=cfg.client_id,
            scopes=cfg.graph_scopes,
            token_cache_path=cfg.token_cache_path,
        )
        background_tasks.add_task(_bg_auth_task, flow, cfg)
        return flow
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

class BillRecord(BaseModel):
    costtime: str
    cost: float
    account: str
    behaviour: str
    business: str
    remark: str = ""

@app.post("/api/records")
def api_create_record(record: BillRecord):
    cfg = load_config()
    conn = get_connection(cfg.pg_dsn)
    with conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO "CMB_bill" (costtime, cost, original_cost, original_currency, account, behaviour, business, remark, source, created_at)
                VALUES (%s, %s, %s, 'CNY', %s, %s, %s, %s, 'manual', now())
            ''', (record.costtime, record.cost, record.cost, record.account, record.behaviour, record.business, record.remark))
    return {"success": True}

@app.put("/api/records/{record_id}")
def api_update_record(record_id: int, record: BillRecord):
    cfg = load_config()
    conn = get_connection(cfg.pg_dsn)
    with conn:
        with conn.cursor() as cur:
            cur.execute('''
                UPDATE "CMB_bill" 
                SET costtime=%s, cost=%s, original_cost=%s, account=%s, behaviour=%s, business=%s, remark=%s
                WHERE id=%s
            ''', (record.costtime, record.cost, record.cost, record.account, record.behaviour, record.business, record.remark, record_id))
    return {"success": True}

@app.delete("/api/records/{record_id}")
def api_delete_record(record_id: int):
    cfg = load_config()
    conn = get_connection(cfg.pg_dsn)
    with conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "CMB_bill" WHERE id=%s', (record_id,))
    return {"success": True}

@app.get("/api/records_list")
def api_list_records(start: str, end: str):
    cfg = load_config()
    conn = get_connection(cfg.pg_dsn)
    with conn.cursor() as cur:
        cur.execute('''
            SELECT id, costtime, cost, account, behaviour, business, remark 
            FROM "CMB_bill" 
            WHERE costtime >= %s AND costtime <= %s
            ORDER BY costtime DESC
        ''', (start, end))
        rows = cur.fetchall()
    return {"records": [{"id": r[0], "costtime": str(r[1]), "cost": r[2], "account": r[3], "behaviour": r[4], "business": r[5], "remark": r[6] if r[6] else ""} for r in rows]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8502)

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.ingest.models import TransactionRecord

CMB_BILL_TABLE = "CMB_bill"

# Keep normalization in PostgreSQL so mail ingestion and manual edits use the
# same identity rule. NFKC folds full-width text; case/whitespace differences
# should not turn one merchant into multiple transactions.
ACCOUNT_IDENTITY_SQL = "btrim(coalesce(account, ''))"
MERCHANT_IDENTITY_SQL = (
    "regexp_replace(lower(regexp_replace(btrim(normalize(coalesce(business, ''), NFKC)), "
    "'[[:space:]]+', ' ', 'g')), '支付$', '')"
)
CURRENCY_IDENTITY_SQL = "upper(btrim(coalesce(original_currency, 'CNY')))"


def ensure_bill_table(conn: psycopg.Connection) -> str:
    """确保固定账单表存在并具备最新结构。"""
    table_name = CMB_BILL_TABLE
    
    # 1. 基础表结构（保持 created_at 等默认值）
    sql_base = f'''
    CREATE TABLE IF NOT EXISTS "{table_name}" (
        id BIGSERIAL PRIMARY KEY,
        costTime TIMESTAMP NOT NULL,
        cost DOUBLE PRECISION NOT NULL,
        account TEXT,
        behaviour TEXT,
        business TEXT,
        remain TEXT,
        source TEXT,
        remark TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    '''
    
    # 2. 增加原始金额和币种列
    sql_cols = f'''
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS original_cost DOUBLE PRECISION;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS original_currency TEXT;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS mail_body TEXT;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS sure_synced_at TIMESTAMPTZ;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS payer_name TEXT;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS payer_account_last4 TEXT;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS payee_name TEXT;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS payee_account_last4 TEXT;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS sure_transfer_status TEXT;
    ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS sure_transfer_checked_at TIMESTAMPTZ;
    '''
    
    # 3. 为旧数据填充默认值（重要：确保后续创建唯一索引不因 NULL 冲突）
    sql_fill = f'''
    UPDATE "{table_name}"
    SET original_cost = coalesce(original_cost, cost),
        original_currency = coalesce(original_currency, 'CNY')
    WHERE original_cost IS NULL OR original_currency IS NULL;
    '''

    with conn.cursor() as cur:
        cur.execute(sql_base)
        cur.execute(sql_cols)
        cur.execute(sql_fill)
        
        # 4. Create the safer identity before removing the legacy indexes. A
        # failed migration leaves the old uniqueness rule intact.
        cur.execute(f'''
            CREATE UNIQUE INDEX IF NOT EXISTS "{table_name}_identity_v3_idx"
            ON "{table_name}" (
                ({ACCOUNT_IDENTITY_SQL}),
                ({MERCHANT_IDENTITY_SQL}),
                costTime,
                original_cost,
                ({CURRENCY_IDENTITY_SQL})
            );
        ''')
        cur.execute(f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{table_name}_costtime_cost_key";')
        cur.execute(f'DROP INDEX IF EXISTS "{table_name}_identity_v2_idx";')
        cur.execute(f'DROP INDEX IF EXISTS "{table_name}_original_dedup_idx";')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS bill_ingest_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_successful_scan_at TIMESTAMPTZ
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS bill_emails (
                id BIGSERIAL PRIMARY KEY,
                graph_message_id TEXT NOT NULL UNIQUE,
                content_fingerprint TEXT NOT NULL UNIQUE,
                mail_kind TEXT NOT NULL,
                received_at TIMESTAMPTZ NOT NULL,
                message_payload JSONB NOT NULL,
                stored_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                processed_at TIMESTAMPTZ
            )
        ''')
        cur.execute('''
            CREATE INDEX IF NOT EXISTS bill_emails_pending_idx
            ON bill_emails (received_at, id) WHERE processed_at IS NULL
        ''')
    return table_name


def email_fingerprint(message: dict) -> str:
    """Also deduplicate copied mail whose Graph message ID changed."""
    identity = [
        (message.get("from") or {}).get("emailAddress", {}).get("address", "").casefold(),
        message.get("receivedDateTime", ""),
        message.get("subject", ""),
        (message.get("body") or {}).get("content", ""),
    ]
    raw = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def store_emails(conn: psycopg.Connection, mail_kind: str, messages: list[dict]) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for message in messages:
            received = datetime.fromisoformat(message["receivedDateTime"].replace("Z", "+00:00"))
            cur.execute('''
                INSERT INTO bill_emails
                    (graph_message_id, content_fingerprint, mail_kind, received_at, message_payload)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            ''', (message["id"], email_fingerprint(message), mail_kind,
                  received, Jsonb(message)))
            inserted += cur.rowcount
    return inserted


def fetch_unprocessed_emails(conn: psycopg.Connection) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {"credit_daily": [], "credit_recent": [], "debit": [], "other": []}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''
            SELECT id, mail_kind, message_payload FROM bill_emails
            WHERE processed_at IS NULL ORDER BY received_at, id
        ''')
        for row in cur:
            message = dict(row["message_payload"])
            message["_bill_email_id"] = row["id"]
            groups[row["mail_kind"]].append(message)
    return groups


def mark_emails_processed(conn: psycopg.Connection, email_ids: list[int]) -> None:
    if not email_ids:
        return
    with conn.cursor() as cur:
        cur.execute('''
            UPDATE bill_emails SET processed_at = NOW()
            WHERE id = ANY(%s) AND processed_at IS NULL
        ''', (email_ids,))


def last_successful_scan_at(conn: psycopg.Connection) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT last_successful_scan_at FROM bill_ingest_state WHERE id = 1")
        row = cur.fetchone()
    return row[0] if row else None


def save_successful_scan_at(conn: psycopg.Connection, scanned_at: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute('''
            INSERT INTO bill_ingest_state (id, last_successful_scan_at) VALUES (1, %s)
            ON CONFLICT (id) DO UPDATE SET last_successful_scan_at = EXCLUDED.last_successful_scan_at
        ''', (scanned_at,))


def fetch_pending_sure_rows(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''
            SELECT id, costtime, cost, account, behaviour, business, remain, source,
                   original_cost, original_currency, mail_body,
                   payer_name, payer_account_last4, payee_name, payee_account_last4
            FROM "CMB_bill"
            WHERE sure_synced_at IS NULL AND source <> 'manual' AND mail_body IS NOT NULL
            ORDER BY costtime, id
        ''')
        return list(cur.fetchall())


def mark_sure_synced(conn: psycopg.Connection, record_ids: list[int]) -> None:
    if not record_ids:
        return
    with conn.cursor() as cur:
        cur.execute('''
            UPDATE "CMB_bill" SET sure_synced_at = NOW()
            WHERE id = ANY(%s) AND sure_synced_at IS NULL
        ''', (record_ids,))


def backfill_transfer_parties(conn: psycopg.Connection) -> int:
    """Enrich previously imported bank notices from their stored full mail."""
    from backend.ingest.parser import html_to_text, parse_transfer_parties

    updated = 0
    with conn.cursor() as cur:
        cur.execute('''
            SELECT id, mail_body FROM "CMB_bill"
            WHERE behaviour = '转入' AND payer_account_last4 IS NULL
              AND mail_body IS NOT NULL AND mail_body LIKE '%付方%'
        ''')
        rows = cur.fetchall()
        for row_id, mail_body in rows:
            parties = parse_transfer_parties(html_to_text(mail_body))
            if not parties.get("payer_account_last4"):
                continue
            cur.execute('''
                UPDATE "CMB_bill" SET payer_name = %s, payer_account_last4 = %s,
                    payee_name = %s, payee_account_last4 = %s
                WHERE id = %s AND payer_account_last4 IS NULL
            ''', (parties.get("payer_name"), parties["payer_account_last4"],
                  parties.get("payee_name"), parties.get("payee_account_last4"), row_id))
            updated += cur.rowcount
    return updated


def fetch_pending_transfer_rows(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''
            SELECT id, costtime, cost, account, behaviour, business, remain, source,
                   original_cost, original_currency, payer_name, payer_account_last4,
                   payee_name, payee_account_last4
            FROM "CMB_bill"
            WHERE behaviour = '转入' AND cost > 0 AND payer_account_last4 IS NOT NULL
              AND sure_synced_at IS NOT NULL
              AND (sure_transfer_status IS NULL OR sure_transfer_status NOT IN ('linked', 'inferred'))
              AND (sure_transfer_checked_at IS NULL OR sure_transfer_checked_at < NOW() - INTERVAL '1 day')
            ORDER BY costtime, id
        ''')
        return list(cur.fetchall())


def mark_transfer_match_result(conn: psycopg.Connection, row_id: int, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute('''
            UPDATE "CMB_bill" SET sure_transfer_status = %s, sure_transfer_checked_at = NOW()
            WHERE id = %s
        ''', (status, row_id))


def insert_transaction_if_new(
    conn: psycopg.Connection,
    record: TransactionRecord,
    *,
    ensure_table: bool = True,
    auto_commit: bool = True,
    mail_body: str = "",
) -> bool:
    """插入交易记录；按账户、规范化商户、时间、原币金额和币种去重。"""
    table_name = ensure_bill_table(conn) if ensure_table else CMB_BILL_TABLE
    
    # 提取并转换 Decimal 到 float，处理 None
    orig_cost = float(record.original_cost) if record.original_cost is not None else float(record.cost)
    orig_curr = record.original_currency if record.original_currency else "CNY"

    sql = f'''
    INSERT INTO "{table_name}" (costTime, cost, account, behaviour, business, remain, source, original_cost, original_currency, mail_body,
                                payer_name, payer_account_last4, payee_name, payee_account_last4)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    '''
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record.cost_time,
                float(record.cost),
                record.account,
                record.behaviour,
                record.business,
                record.remain,
                record.source,
                orig_cost,
                orig_curr,
                mail_body,
                record.payer_name,
                record.payer_account_last4,
                record.payee_name,
                record.payee_account_last4,
            ),
        )
        inserted = cur.rowcount > 0
        if not inserted and mail_body:
            # Legacy rows may predate mail-body storage. Re-seeing the bank mail
            # enriches that row without creating another transaction.
            cur.execute(f'''
                UPDATE "{table_name}"
                SET mail_body = COALESCE(NULLIF(mail_body, ''), %s),
                    payer_name = COALESCE(payer_name, %s),
                    payer_account_last4 = COALESCE(payer_account_last4, %s),
                    payee_name = COALESCE(payee_name, %s),
                    payee_account_last4 = COALESCE(payee_account_last4, %s)
                WHERE ({ACCOUNT_IDENTITY_SQL}) = %s
                  AND ({MERCHANT_IDENTITY_SQL}) =
                      regexp_replace(lower(regexp_replace(btrim(normalize(%s, NFKC)),
                      '[[:space:]]+', ' ', 'g')), '支付$', '')
                  AND costtime = %s AND original_cost = %s
                  AND ({CURRENCY_IDENTITY_SQL}) = %s
                  AND ((mail_body IS NULL OR mail_body = '')
                       OR (payer_account_last4 IS NULL AND %s::text IS NOT NULL)
                       OR (payee_account_last4 IS NULL AND %s::text IS NOT NULL))
            ''', (mail_body, record.payer_name, record.payer_account_last4,
                  record.payee_name, record.payee_account_last4,
                  record.account.strip(), record.business,
                  record.cost_time, orig_cost, orig_curr.strip().upper(),
                  record.payer_account_last4, record.payee_account_last4))
    if auto_commit:
        conn.commit()
    return inserted


def fetch_records_in_range(conn: psycopg.Connection, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """按时间区间读取账单记录（左闭右开）。"""
    table_name = CMB_BILL_TABLE
    sql = f'''
    SELECT
        id AS "id",
        costtime AS "costTime",
        cost AS "cost",
        account AS "account",
        behaviour AS "behaviour",
        business AS "business",
        remain AS "remain",
        source AS "source",
        remark AS "remark",
        original_cost AS "originalCost",
        original_currency AS "originalCurrency"
    FROM "{table_name}"
    WHERE costtime >= %s AND costtime < %s
    ORDER BY costtime ASC;
    '''
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (start_dt, end_dt))
        return list(cur.fetchall())


def fetch_latest_balance(conn: psycopg.Connection, account: str = "6061") -> Decimal:
    """读取指定账户最近一条非空余额。"""
    table_name = CMB_BILL_TABLE
    sql = f'''
    SELECT remain
    FROM "{table_name}"
    WHERE account = %s AND remain IS NOT NULL AND remain <> ''
    ORDER BY costTime DESC
    LIMIT 1;
    '''
    with conn.cursor() as cur:
        cur.execute(sql, (account,))
        row = cur.fetchone()
    if not row:
        return Decimal("0")
    return Decimal(str(row[0]))


def get_connection(dsn: str) -> psycopg.Connection:
    """创建 PostgreSQL 连接，并注入基础连接健壮性参数。"""
    final_dsn = dsn

    # 在 Windows + Docker Desktop 场景下，127.0.0.1 更稳定。
    if "@localhost:" in final_dsn:
        final_dsn = final_dsn.replace("@localhost:", "@127.0.0.1:")

    # 避免连接异常时阻塞过久。
    if "connect_timeout=" not in final_dsn:
        sep = "&" if "?" in final_dsn else "?"
        final_dsn = f"{final_dsn}{sep}connect_timeout=5"

    return psycopg.connect(final_dsn)


def cleanup_utc_shifted_debit_duplicates(conn: psycopg.Connection) -> int:
    """清理借记卡历史数据中由 UTC/UTC+8 混写造成的 8 小时错位重复。

    规则：若两条记录满足
    1) 账号为 6061
    2) 金额、行为、商户、余额一致
    3) 时间恰好相差 8 小时
    则删除较早（错位）的一条。
    """
    table_name = CMB_BILL_TABLE
    sql = f'''
    DELETE FROM "{table_name}" AS wrong
    USING "{table_name}" AS right_row
    WHERE wrong.id <> right_row.id
      AND wrong.costTime + INTERVAL '8 hours' = right_row.costTime
      AND COALESCE(wrong.account, '') = '6061'
      AND COALESCE(right_row.account, '') = COALESCE(wrong.account, '')
      AND COALESCE(right_row.behaviour, '') = COALESCE(wrong.behaviour, '')
      AND COALESCE(right_row.business, '') = COALESCE(wrong.business, '')
      AND COALESCE(right_row.remain, '') = COALESCE(wrong.remain, '')
      AND COALESCE(wrong.source, '') IN ('', '借记卡账户变动通知')
      AND COALESCE(right_row.source, '') IN ('', '借记卡账户变动通知')
      AND right_row.cost = wrong.cost;
    '''
    with conn.cursor() as cur:
        cur.execute(sql)
        return max(cur.rowcount, 0)

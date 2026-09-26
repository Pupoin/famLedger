from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from backend.ingest.stats import build_stats
from backend.auth.graph_auth import acquire_graph_token
from backend.auth.state import set_auth_failed
from backend.ingest.config import load_config
from backend.ingest.db import (
    backfill_transfer_parties,
    cleanup_utc_shifted_debit_duplicates,
    ensure_bill_table,
    fetch_latest_balance,
    fetch_records_in_range,
    fetch_unprocessed_emails,
    get_connection,
    insert_transaction_if_new,
    last_successful_scan_at,
    mark_emails_processed,
    save_successful_scan_at,
    store_emails,
)
from backend.ingest.graph_client import GraphMailClient
from backend.ingest.models import DailyCreditSummary, TransactionRecord
from backend.ingest.sure_sync import sync_pending_from_db, sync_transfer_matches_from_db
from backend.ingest.mail_content import message_body_and_parse_text
from backend.notify import send_windows_notification
from backend.ingest.parser import (
    parse_credit_daily_message,
    parse_credit_recent_message,
    parse_debit_message,
)

logger = logging.getLogger(__name__)


def _parse_iso_datetime(value: str) -> datetime:
    """把 Graph 的 ISO 时间统一转为本地 UTC+8 的 naive datetime。"""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    utc8 = timezone(timedelta(hours=8))
    return parsed.astimezone(utc8).replace(tzinfo=None)


def _mail_kind(message: dict, folder: str) -> str:
    sender = ((message.get("from") or {}).get("emailAddress") or {}).get("address", "").casefold()
    subject = message.get("subject", "")
    if folder == "credit" and sender == "ccsvc@message.cmbchina.com":
        if "每日信用管家" in subject:
            return "credit_daily"
        if "近期消费明细" in subject:
            return "credit_recent"
    if folder == "debit" and sender == "95555@message.cmbchina.com" and "账户变动通知" in subject:
        return "debit"
    return "other"


def run() -> None:
    """任务主入口：抓取邮件、解析账单、入库、统计并产出通知与报表。"""
    cfg = load_config()
    logger.info("启动账单自动化任务")
    scan_started_at = datetime.now(timezone.utc)
    with get_connection(cfg.pg_dsn) as state_conn:
        ensure_bill_table(state_conn)
        previous_scan = last_successful_scan_at(state_conn)
    force_full_scan = os.getenv("BILL_FORCE_FULL_EMAIL_SCAN", "false").lower() in ("true", "1", "yes")
    since_at = previous_scan - timedelta(days=1) if previous_scan and not force_full_scan else None
    logger.info("邮件抓取起点: %s", since_at.isoformat() if since_at else "首次全量回看")
    logger.debug("运行配置: user_id=%s credit_folder=%s debit_folder=%s", cfg.user_id, cfg.credit_folder_name, cfg.debit_folder_name)

    try:
        token = acquire_graph_token(cfg.tenant_id, cfg.client_id, cfg.graph_scopes, cfg.token_cache_path)
        client = GraphMailClient(access_token=token, user_id=cfg.user_id)
    except Exception as exc:
        logger.exception("Graph 认证或客户端初始化失败")
        set_auth_failed(
            f"Graph 认证或客户端初始化失败: {exc}",
            verify_url="https://microsoft.com/devicelogin",
            client_id=cfg.client_id,
        )
        return

    try:
        credit_folder_id = client.get_folder_id_by_name(cfg.credit_folder_name)
        debit_folder_id = client.get_folder_id_by_name(cfg.debit_folder_name)
    except Exception as exc:
        logger.exception("邮件文件夹查找失败")
        raise RuntimeError(f"邮件文件夹查找失败: {exc}") from exc

    save_emails = os.getenv("SAVE_EMAILS", "false").lower() in ("true", "1", "yes")
    if save_emails:
        credit_messages = client.list_messages(
            folder_id=credit_folder_id, sender="", subject_keywords=[],
            lookback_days=cfg.lookback_days_credit, since_at=since_at, include_all=True,
        )
        debit_messages = client.list_messages(
            folder_id=debit_folder_id, sender="", subject_keywords=[],
            lookback_days=cfg.lookback_days_debit, since_at=since_at, include_all=True,
        )
        with get_connection(cfg.pg_dsn) as email_conn:
            new_emails = 0
            for folder, messages in (("credit", credit_messages), ("debit", debit_messages)):
                by_kind: dict[str, list[dict]] = {}
                for message in messages:
                    kind = _mail_kind(message, folder)
                    by_kind.setdefault(kind, []).append(message)
                for kind, grouped in by_kind.items():
                    new_emails += store_emails(email_conn, kind, grouped)
            save_successful_scan_at(email_conn, scan_started_at)
            pending_emails = fetch_unprocessed_emails(email_conn)
        credit_daily_msgs = pending_emails["credit_daily"]
        credit_recent_msgs = pending_emails["credit_recent"]
        debit_msgs = pending_emails["debit"]
        pending_email_ids = [msg["_bill_email_id"] for group in pending_emails.values() for msg in group]
        logger.info("邮件缓存新增 %s 封，待解析 %s 封", new_emails, len(pending_email_ids))
    else:
        credit_daily_msgs = client.list_messages(
            folder_id=credit_folder_id, sender="ccsvc@message.cmbchina.com",
            subject_keywords=["每日信用管家"], lookback_days=cfg.lookback_days_credit,
            since_at=since_at,
        )
        credit_recent_msgs = client.list_messages(
            folder_id=credit_folder_id, sender="ccsvc@message.cmbchina.com",
            subject_keywords=["近期消费明细"], lookback_days=cfg.lookback_days_credit,
            since_at=since_at,
        )
        debit_msgs = client.list_messages(
            folder_id=debit_folder_id, sender="95555@message.cmbchina.com",
            subject_keywords=["账户变动通知"], lookback_days=cfg.lookback_days_debit,
            since_at=since_at,
        )
        with get_connection(cfg.pg_dsn) as email_conn:
            pending_emails = fetch_unprocessed_emails(email_conn)
        credit_daily_msgs.extend(pending_emails["credit_daily"])
        credit_recent_msgs.extend(pending_emails["credit_recent"])
        debit_msgs.extend(pending_emails["debit"])
        pending_email_ids = [msg["_bill_email_id"] for group in pending_emails.values() for msg in group]

    all_records: list[TransactionRecord] = []
    mail_bodies: dict[int, str] = {}
    daily_summary: DailyCreditSummary | None = None
    daily_summary_received_at: datetime | None = None
    logger.debug(
        "邮件抓取结果: daily=%s recent=%s debit=%s",
        len(credit_daily_msgs),
        len(credit_recent_msgs),
        len(debit_msgs),
    )

    for msg in credit_daily_msgs:
        logger.debug("解析每日信用管家邮件: subject=%s received=%s", msg.get("subject"), msg.get("receivedDateTime"))
        body, parse_text = message_body_and_parse_text(msg)
        records, summary = parse_credit_daily_message(parse_text)
        all_records.extend(records)
        mail_bodies.update((id(record), body) for record in records)
        if summary:
            received_at_raw = msg.get("receivedDateTime")
            received_at = _parse_iso_datetime(received_at_raw) if received_at_raw else None
            if daily_summary is None:
                daily_summary = summary
                daily_summary_received_at = received_at
            elif received_at and (daily_summary_received_at is None or received_at > daily_summary_received_at):
                daily_summary = summary
                daily_summary_received_at = received_at

    if daily_summary and daily_summary_received_at:
        logger.debug("已选最新信用卡摘要: received=%s score=%s", daily_summary_received_at, daily_summary.score)

    for msg in credit_recent_msgs:
        logger.debug("解析近期消费明细邮件: subject=%s received=%s", msg.get("subject"), msg.get("receivedDateTime"))
        body, parse_text = message_body_and_parse_text(msg)
        records = parse_credit_recent_message(parse_text)
        all_records.extend(records)
        mail_bodies.update((id(record), body) for record in records)
    for msg in debit_msgs:
        logger.debug("解析借记卡通知邮件: subject=%s received=%s", msg.get("subject"), msg.get("receivedDateTime"))
        body, parse_text = message_body_and_parse_text(msg)
        received_time = _parse_iso_datetime(msg["receivedDateTime"])
        record = parse_debit_message(parse_text, received_time)
        if record:
            all_records.append(record)
            mail_bodies[id(record)] = body

    logger.debug("开始打印所有解析记录，共 %s 条", len(all_records))
    for index, record in enumerate(all_records, start=1):
        logger.debug(
            "解析记录[%s] costTime=%s cost=%s account=%s behaviour=%s business=%s remain=%s source=%s",
            index,
            record.cost_time,
            record.cost,
            record.account,
            record.behaviour,
            record.business,
            record.remain,
            record.source,
        )

    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)
    month_end = now

    inserted = 0
    db_t0 = time.perf_counter()
    logger.debug("进入数据库阶段")
    conn_t0 = time.perf_counter()
    conn = get_connection(cfg.pg_dsn)
    logger.debug("数据库连接建立耗时: %.3fs", time.perf_counter() - conn_t0)

    with conn:
        ensure_bill_table(conn)
        logger.debug("账单表检查完成: table=%s", "CMB_bill")

        cleaned = cleanup_utc_shifted_debit_duplicates(conn)
        if cleaned > 0:
            logger.info("清理历史 UTC 偏移重复记录: %s 条", cleaned)

        write_t0 = time.perf_counter()
        
        # 必须按时间正序排序！否则如果最新的邮件先被处理（退款先入库），此时去查旧的消费记录会查不到！
        all_records.sort(key=lambda r: r.cost_time)
        
        for record in all_records:
            try:
                # ====== 汇率差额对冲逻辑（解决跨境消费与退款由于汇率变动导致的人民币差额） ======
                if record.behaviour in ("消费撤销", "退款", "退货") and str(record.original_currency).upper() not in ("CNY", "", "NONE", "RMB", "￥", "¥", "NULL"):
                    try:
                        with conn.cursor() as cur:
                            cur.execute('''
                                SELECT cost, original_cost 
                                FROM "CMB_bill" 
                                WHERE account = %s 
                                  AND business = %s 
                                  AND behaviour = '消费'
                                  AND costtime <= %s
                                ORDER BY costtime DESC LIMIT 1
                            ''', (record.account, record.business, record.cost_time))
                            matched = cur.fetchone()
                            
                            if matched:
                                orig_cny_cost, orig_native_cost = matched
                                # 如果原币种的金额对得上
                                if abs(float(record.original_cost)) == abs(float(orig_native_cost)):
                                    old_cost = float(record.cost)
                                    # 强行继承原消费的人民币绝对值，并保留退款本身的符号
                                    sign = -1 if old_cost < 0 else 1
                                    record.cost = type(record.cost)(str(sign * abs(float(orig_cny_cost))))
                                    logger.debug("汇率差额对冲成功: 记录 %s 的人民币金额从 %s 被修正为 %s", record.business, old_cost, record.cost)
                    except Exception as match_exc:
                        logger.warning("跨境退款对消匹配查询失败: %s", match_exc)
                # =========================================================================

                if insert_transaction_if_new(conn, record, ensure_table=False, auto_commit=False,
                                             mail_body=mail_bodies[id(record)]):
                    inserted += 1
                    logger.debug("新增入库成功: costTime=%s cost=%s source=%s", record.cost_time, record.cost, record.source)
                else:
                    logger.debug("重复记录已跳过: costTime=%s cost=%s source=%s", record.cost_time, record.cost, record.source)
            except Exception:
                logger.exception("写入失败，已跳过记录: %s", record)
                raise
        mark_emails_processed(conn, pending_email_ids)
        if not save_emails:
            save_successful_scan_at(conn, scan_started_at)
        conn.commit()
        logger.debug("数据库写入阶段耗时: %.3fs", time.perf_counter() - write_t0)

        read_t0 = time.perf_counter()
        month_rows = fetch_records_in_range(conn, month_start, month_end)

        prev_month_end = month_start
        prev_month_start = datetime(prev_month_end.year, prev_month_end.month, 1) - timedelta(days=1)
        prev_month_start = datetime(prev_month_start.year, prev_month_start.month, 1)
        prev_month_rows = fetch_records_in_range(conn, prev_month_start, prev_month_end)
        current_balance = fetch_latest_balance(conn)
        logger.debug("数据库读取阶段耗时: %.3fs", time.perf_counter() - read_t0)
    logger.debug("数据库总阶段耗时: %.3fs", time.perf_counter() - db_t0)

    # Sure receives only committed Bill rows; failed rows remain pending.
    with get_connection(cfg.pg_dsn) as sync_conn:
        enriched = backfill_transfer_parties(sync_conn)
        if enriched:
            sync_conn.commit()
            logger.info("历史转入邮件补充付方信息: %s 条", enriched)
        sync_pending_from_db(sync_conn)
        sync_transfer_matches_from_db(sync_conn)

    stats = build_stats(month_rows, current_balance=current_balance, now=now)
    send_windows_notification(stats, cfg.one_drive_icon)

    logger.info("共解析记录: %s，新增入库: %s", len(all_records), inserted)
    logger.info(
        "本月统计(1号至当前): 借记卡 入=%.2f 出=%.2f | 信用卡 入=%.2f 出=%.2f | 合计 入=%.2f 出=%.2f",
        stats.month_debit_income,
        abs(float(stats.month_debit_outcome)),
        stats.month_credit_income,
        abs(float(stats.month_credit_outcome)),
        stats.month_income,
        abs(float(stats.month_outcome)),
    )
    if daily_summary:
        logger.info(
            "信用卡已用额度估算: %.2f，积分余额: %.0f",
            daily_summary.used_credit_limit,
            daily_summary.score,
        )


if __name__ == "__main__":
    run()

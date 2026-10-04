"""FamLedger REST API Sync Client for raw email storage and transaction ingestion."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

import requests

from backend.ingest.models import TransactionRecord
from backend.ingest.mail_content import message_body_and_parse_text
from backend.ingest.parser import (
    parse_credit_daily_message,
    parse_credit_recent_message,
    parse_debit_message,
)

logger = logging.getLogger(__name__)
CHINA_TZ = timezone(timedelta(hours=8))
SOURCE = "bill-cmb-email"


def occurred_at(record: TransactionRecord) -> datetime:
    """Return transaction time in UTC+8."""
    return record.cost_time.replace(tzinfo=CHINA_TZ)


def normalized_merchant(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value or "").strip().casefold().split())
    return normalized.removesuffix("支付")


def normalized_amount(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def external_id(record: TransactionRecord) -> str:
    parts = [
        record.account.strip(),
        normalized_merchant(record.business),
        occurred_at(record).isoformat(timespec="seconds"),
        normalized_amount(record.original_cost if record.original_cost is not None else record.cost),
        (record.original_currency or "CNY").strip().upper(),
    ]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class FamLedgerClient:
    def __init__(self, base_url: str | None = None, api_token: str | None = None):
        self.base_url = (base_url or os.getenv("FAMLEDGER_API_URL", "http://famledger:8000")).rstrip("/")
        self.api_token = api_token or os.getenv("FAMLEDGER_API_TOKEN", "")
        self.session = requests.Session()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_token:
            headers["X-Api-Key"] = self.api_token
        self.session.headers.update(headers)

    def request(self, method: str, path: str, *, payload: dict | None = None, params: dict | None = None) -> dict:
        url = f"{self.base_url}/api/{path.lstrip('/')}" if not path.startswith("/api/") else f"{self.base_url}{path}"
        resp = self.session.request(method, url, json=payload, params=params, timeout=30)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.error("FamLedger API %s %s 失败 [%s]: %s", method, url, resp.status_code, resp.text)
            raise RuntimeError(f"FamLedger API {method} {url} error: {resp.status_code} {resp.text}") from exc
        return resp.json()

    def push_transaction(
        self,
        record: TransactionRecord,
        *,
        mail_body: str = "",
    ) -> dict:
        """将解析出的交易明细通过 API 发送至 FamLedger（精炼规范）。"""
        is_refund = record.behaviour in ("退款", "退货", "消费撤销")
        is_cc_payment = "信用卡还款" in (record.business or "") or "信用卡还款" in (record.behaviour or "")

        tags = []
        if is_cc_payment:
            txn_type = "transfer"
            tags.append("信用卡还款")
        elif is_refund:
            txn_type = "refund"
        elif "转账" in (record.behaviour or "") or "转账" in (record.business or ""):
            txn_type = "transfer"
        else:
            txn_type = "expense" if record.cost < 0 else "income"

        payload = {
            "account": f"招商银行:{record.account.strip()}",
            "narration": record.business,
            "amount": str(abs(record.original_cost if record.original_cost is not None else record.cost)),
            "currency": (record.original_currency or "CNY") if record.original_cost is not None else "CNY",
            "occurred_at": occurred_at(record).isoformat(timespec="seconds"),
            "transaction_type": txn_type,
            "tags": tags,
            "external_id": external_id(record),
            "notes": mail_body[:2000] if mail_body else "",
            "extra": {
                **({"direction": "inflow" if record.cost >= 0 else "outflow"} if txn_type == "transfer" else {}),
                "counterparty": {
                    "payer_name": record.payer_name,
                    "payer_account_last4": record.payer_account_last4,
                    "payee_name": record.payee_name,
                    "payee_account_last4": record.payee_account_last4,
                }
            },
        }
        return self.request("POST", "/api/v1/transactions", payload=payload)


def sync_emails_and_parse_to_famledger(
    client: FamLedgerClient,
    messages_by_kind: dict[str, list[dict]],
) -> tuple[int, int]:
    """
    处理邮件批次：直接进行账单解析并调用 API 录入交易流水。
    返回 (处理邮件数, 新增交易流水数)。
    """
    processed_count = 0
    pushed_count = 0

    for mail_kind, messages in messages_by_kind.items():
        for msg in messages:
            processed_count += 1
            body, parse_text = message_body_and_parse_text(msg)

            # 解析邮件账单并推送到 FamLedger 交易流水
            records: list[TransactionRecord] = []
            if mail_kind == "credit_daily":
                recs, _ = parse_credit_daily_message(parse_text)
                records.extend(recs)
            elif mail_kind == "credit_recent":
                recs = parse_credit_recent_message(parse_text)
                records.extend(recs)
            elif mail_kind == "debit":
                received_time = datetime.fromisoformat(msg["receivedDateTime"].replace("Z", "+00:00"))
                rec = parse_debit_message(parse_text, received_time)
                if rec:
                    records.append(rec)

            # 按流水时间排序后通过 API 推送
            records.sort(key=lambda r: r.cost_time)
            for rec in records:
                try:
                    push_res = client.push_transaction(rec, mail_body=body)
                    if push_res.get("status") == "pending_fx":
                        logger.info("交易已保存待换汇，尚未入账: %s", rec.cost_time)
                    elif push_res.get("status") == "canceled":
                        logger.info("该来源记录已取消入账: %s", rec.cost_time)
                    elif push_res.get("status") != "duplicate" and not push_res.get("duplicate") :
                        pushed_count += 1
                        logger.info("交易明细已通过 API 推送入库: %s %s %s", rec.cost_time, rec.business, rec.cost)
                    else:
                        logger.debug("交易已存在(幂等去重): %s", rec.business)
                except Exception as push_exc:
                    logger.error("推送交易明细至 FamLedger 失败: %s", push_exc)

    return processed_count, pushed_count

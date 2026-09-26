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

    def store_email(self, message: dict, mail_kind: str, raw_text: str = "") -> dict:
        """保存原始邮件到 FamLedger 数据库。"""
        sender = ((message.get("from") or {}).get("emailAddress") or {}).get("address", "")
        received_raw = message.get("receivedDateTime")
        if received_raw:
            received_at = received_raw
        else:
            received_at = datetime.now(timezone.utc).isoformat()

        body = (message.get("body") or {}).get("content", "")
        payload = {
            "message_id": message["id"],
            "mail_kind": mail_kind,
            "subject": message.get("subject", ""),
            "sender": sender,
            "received_at": received_at,
            "raw_html": body,
            "raw_text": raw_text,
            "raw_payload": message,
        }
        return self.request("POST", "/api/v1/imports/emails", payload=payload)

    def push_transaction(
        self,
        record: TransactionRecord,
        *,
        raw_email_id: str | None = None,
        mail_body: str = "",
    ) -> dict:
        """将解析出的交易明细通过 API 发送至 FamLedger。"""
        nature = "refund" if record.behaviour in ("退款", "退货", "消费撤销") else ("expense" if record.cost < 0 else "income")
        payload = {
            "account_identifier": record.account,
            "transacted_at": record.cost_time.date().isoformat(),
            "occurred_at": occurred_at(record).isoformat(timespec="seconds"),
            "amount": str(abs(record.cost)),
            "currency": record.original_currency or "CNY",
            "name": record.business,
            "merchant_name": record.business,
            "transaction_type": nature,
            "nature": nature,
            "external_id": external_id(record),
            "raw_email_id": raw_email_id,
            "notes": mail_body[:2000] if mail_body else "",
            "counterparty": {
                "payer_name": record.payer_name,
                "payer_account_last4": record.payer_account_last4,
                "payee_name": record.payee_name,
                "payee_account_last4": record.payee_account_last4,
            },
        }
        return self.request("POST", "/api/v1/transactions", payload=payload)


def sync_emails_and_parse_to_famledger(
    client: FamLedgerClient,
    messages_by_kind: dict[str, list[dict]],
) -> tuple[int, int]:
    """
    处理邮件批次：
    1. 首先将原始邮件存档到 FamLedger（POST /api/v1/imports/emails）
    2. 如果为新邮件（is_new=True），则进行账单解析并调用 API 录入交易流水。
    返回 (新邮件入库数, 新增交易流水数)。
    """
    stored_count = 0
    pushed_count = 0

    for mail_kind, messages in messages_by_kind.items():
        for msg in messages:
            body, parse_text = message_body_and_parse_text(msg)
            try:
                res = client.store_email(msg, mail_kind, raw_text=parse_text)
            except Exception as exc:
                logger.warning("存档原始邮件失败，跳过解析: subject=%s err=%s", msg.get("subject"), exc)
                continue

            email_id = res.get("id")
            is_new = res.get("is_new", False)
            if is_new:
                stored_count += 1
                logger.info("捕获新邮件并成功存档: id=%s subject=%s", email_id, msg.get("subject"))

                # 仅对新邮件执行解析并 API 推送
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
                        push_res = client.push_transaction(rec, raw_email_id=email_id, mail_body=body)
                        if push_res.get("status") != "duplicate":
                            pushed_count += 1
                            logger.info("交易明细已通过 API 推送入库: %s %s %s", rec.cost_time, rec.business, rec.cost)
                        else:
                            logger.debug("交易已存在(幂等去重): %s", rec.business)
                    except Exception as push_exc:
                        logger.error("推送交易明细至 FamLedger 失败: %s", push_exc)

    return stored_count, pushed_count

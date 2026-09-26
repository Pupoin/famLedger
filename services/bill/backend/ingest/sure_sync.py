"""Push this run's parsed mail transactions to Sure without reading bill rows."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import requests

from backend.ingest.models import TransactionRecord

logger = logging.getLogger(__name__)
CHINA_TZ = timezone(timedelta(hours=8))
SOURCE = "bill-cmb-email"
RULES_PATH = Path("/app/data/category_rules.json")


def occurred_at(record: TransactionRecord) -> datetime:
    """Return the bank statement's exact transaction time (CSV is UTC+8)."""
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


def amount_cents(value: Decimal) -> int:
    return int((abs(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def plain_category_name(value: str) -> str:
    # Sure categories commonly include a leading emoji, while bill rules do not.
    return re.sub(r"^[^\w\u4e00-\u9fff]+", "", value or "").strip().casefold()


def category_merchant(value: str) -> str:
    """Mirror bill's dashboard rule input without changing identity names."""
    name = value.strip().strip("【】[]()")
    prefixes = ("支付宝", "财付通", "微信支付", "银联", "云闪付扫码", "云闪付",
                "网银在线", "京东支付", "美团支付", "美团", "抖音支付")
    while True:
        prefix = next((item for item in prefixes if name.startswith(item + "-")), None)
        if prefix is None:
            break
        name = name[len(prefix) + 1:]
    return re.sub(r"^(消费|理财|转账|退款)-+", "", name).strip() or value


class SureSyncError(RuntimeError):
    pass


class SureClient:
    def __init__(self, base_url: str, api_key: str, *, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/") + "/"
        self.session = session or requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Accept": "application/json"})
        self._accounts: list[dict] | None = None
        self._categories: list[dict] | None = None
        self._day_cache: dict[tuple[str, str], list[dict]] = {}

    def request(self, method: str, path: str, *, params: dict | None = None, payload: dict | None = None, include_status: bool = False):
        response = self.session.request(
            method, self.base_url + path.lstrip("/"), params=params, json=payload, timeout=20
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise SureSyncError(f"Sure {method} {path}: HTTP {response.status_code}") from exc
        data = response.json()
        return (data, response.status_code) if include_status else data

    def pages(self, path: str, key: str, *, params: dict | None = None) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            data = self.request("GET", path, params={**(params or {}), "page": page, "per_page": 100})
            items.extend(data.get(key, []))
            pagination = data.get("pagination", {})
            if page >= int(pagination.get("total_pages", 1)):
                return items
            page += 1

    def account_for(self, name: str, institution: str) -> dict | None:
        if self._accounts is None:
            self._accounts = self.pages("accounts", "accounts")
        matches = [
            account for account in self._accounts
            if account.get("name", "").strip() == name.strip()
            and account.get("institution_name", "").strip() == institution.strip()
        ]
        if len(matches) != 1:
            logger.warning("Sure 账户匹配数=%s，停止推送: 金融机构=%s 账户=%s", len(matches), institution, name)
            return None
        return matches[0]

    def day_transactions(self, account_id: str, day: str) -> list[dict]:
        key = (account_id, day)
        if key not in self._day_cache:
            self._day_cache[key] = self.pages(
                "transactions", "transactions",
                params={"account_id": account_id, "start_date": day, "end_date": day},
            )
        return self._day_cache[key]

    def existing_transaction(self, account_id: str, record: TransactionRecord) -> str:
        day = record.cost_time.date().isoformat()
        transactions = self.day_transactions(account_id, day)
        fingerprint = external_id(record)
        exact_id = [item for item in transactions if item.get("external_id") == fingerprint and item.get("source") == SOURCE]
        if len(exact_id) == 1:
            return "duplicate"
        if len(exact_id) > 1:
            return "ambiguous"

        target_time = occurred_at(record)
        target_cents = amount_cents(record.cost)
        merchant = normalized_merchant(record.business)
        historical = []
        for item in transactions:
            try:
                occurred = datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00"))
                if occurred.tzinfo is None:
                    continue
                same_time = occurred.astimezone(CHINA_TZ) == target_time
                same_amount = int(item["amount_cents"]) == target_cents
                same_merchant = normalized_merchant(item.get("name", "")) == merchant
                same_direction = (item.get("classification") in ("income", "refund")) if record.behaviour in ("退款", "退货", "消费撤销") else item.get("classification") == ("expense" if record.cost < 0 else "income")
                if same_time and same_amount and same_merchant and same_direction:
                    historical.append(item)
            except (KeyError, TypeError, ValueError):
                continue
        if len(historical) == 1:
            return "duplicate"
        if len(historical) > 1:
            return "ambiguous"
        return "new"

    def category_for(self, name: str, parent_name: str | None = None) -> str:
        if self._categories is None:
            self._categories = self.pages("categories", "categories")
        parent_id = self.category_for(parent_name) if parent_name else None
        matches = [
            category for category in self._categories
            if plain_category_name(category.get("name", "")) == plain_category_name(name)
            and (category.get("parent") or {}).get("id") == parent_id
        ]
        if len(matches) > 1:
            raise SureSyncError(f"Sure 分类匹配不唯一: {parent_name or ''}/{name}")
        if matches:
            return matches[0]["id"]
        payload = {"category": {"name": name}}
        if parent_id:
            payload["category"]["parent_id"] = parent_id
        category = self.request("POST", "categories", payload=payload)
        self._categories.append(category)
        return category["id"]

    def push(self, account_id: str, record: TransactionRecord, *, category_id: str | None, mail_body: str, institution: str) -> str:
        status = self.existing_transaction(account_id, record)
        if status != "new":
            return status
        card_payee = None
        if record.behaviour == "还款" and record.payee_account_last4:
            candidate = self.account_for(record.payee_account_last4, institution)
            if candidate and candidate.get("account_type") == "credit_card":
                card_payee = candidate
        payload = {"transaction": {
            "account_id": account_id,
            "occurred_at": occurred_at(record).isoformat(timespec="seconds"),
            "amount": str(abs(record.cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "nature": "refund" if record.behaviour in ("退款", "退货", "消费撤销") else ("expense" if record.cost < 0 else "income"),
            "kind": "refund" if record.behaviour in ("退款", "退货", "消费撤销") else ("cc_payment" if card_payee else "standard"),
            "currency": "CNY",
            "name": record.business,
            "category_id": category_id,
            "notes": mail_body,
            "source": SOURCE,
            "external_id": external_id(record),
        }}
        counterparty = {
            "payer_name": record.payer_name,
            "payer_account_last4": record.payer_account_last4 or (record.account if card_payee else None),
            "payee_name": record.payee_name,
            "payee_account_last4": record.payee_account_last4 or (record.account if record.cost > 0 else None),
            "payee_account_id": card_payee["id"] if card_payee else None,
        }
        if any(value is not None for value in counterparty.values()):
            payload["transaction"]["counterparty"] = {key: value for key, value in counterparty.items() if value is not None}
        created, http_status = self.request("POST", "transactions", payload=payload, include_status=True)
        # The API returns 200 for an idempotent hit; either way, keep the
        # current run's cache in sync so duplicate emails do not POST again.
        self._day_cache[(account_id, record.cost_time.date().isoformat())].append(created)
        return "created" if http_status == 201 else "duplicate"

    def existing_entry_for(self, account_id: str, record: TransactionRecord) -> dict | None:
        items = self.day_transactions(account_id, record.cost_time.date().isoformat())
        exact = [item for item in items if item.get("external_id") == external_id(record) and item.get("source") == SOURCE]
        if len(exact) == 1:
            return exact[0]
        if exact:
            return None
        target_cents = amount_cents(record.cost)
        target_time = occurred_at(record)
        historical = []
        for item in items:
            try:
                item_time = datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00"))
                if (item_time.astimezone(CHINA_TZ) == target_time
                    and int(item["amount_cents"]) == target_cents
                    and normalized_merchant(item.get("name", "")) == normalized_merchant(record.business)):
                    historical.append(item)
            except (KeyError, TypeError, ValueError):
                continue
        return historical[0] if len(historical) == 1 else None

    def match_bank_transfer(self, record: TransactionRecord, institution: str, *, dry_run: bool = False) -> str:
        """Classify a verified bank inflow; link a real outflow when available."""
        if not record.payer_account_last4 or record.behaviour != "转入" or record.cost <= 0:
            return "not_applicable"
        recipient = self.account_for(record.account, institution)
        if recipient is None:
            return "unmatched_account"
        incoming = self.existing_entry_for(recipient["id"], record)
        if incoming is None:
            return "missing_inflow"
        payer = self.account_for(record.payer_account_last4, institution)
        if payer is None or payer["id"] == recipient["id"]:
            return "unmatched_account"
        party = {"payer_name": record.payer_name,
                 "payer_account_last4": record.payer_account_last4,
                 "payer_account_id": payer["id"],
                 "payee_account_last4": record.account}
        party = {key: value for key, value in party.items() if value is not None}
        if incoming.get("transfer"):
            return "linked"
        candidates = []
        possible_outflows = []
        for offset in (-1, 0, 1):
            day = (record.cost_time.date() + timedelta(days=offset)).isoformat()
            for item in self.day_transactions(payer["id"], day):
                if (item.get("classification") == "expense"
                    and not item.get("transfer")
                    and item.get("kind") != "refund"
                    and int(item.get("amount_cents", -1)) == amount_cents(record.cost)):
                    possible_outflows.append(item)
                    if item.get("kind") == "standard" and re.search(r"转账|汇款|转至|转出", item.get("name", "")):
                        candidates.append(item)
        unique = {item["id"]: item for item in candidates}
        if len(unique) > 1 or (not unique and possible_outflows):
            return "ambiguous"
        if not unique:
            if dry_run:
                return "would_infer"
            if incoming.get("counterparty") != party:
                self.request("PATCH", f"transactions/{incoming['id']}", payload={"transaction": {"counterparty": party}})
            self.request("POST", "transfers", payload={"transfer": {
                "source_account_id": payer["id"],
                "inflow_transaction_id": incoming["id"],
            }})
            return "inferred"
        outgoing = next(iter(unique.values()))
        if dry_run:
            return "would_link"
        if incoming.get("counterparty") != party:
            self.request("PATCH", f"transactions/{incoming['id']}", payload={"transaction": {"counterparty": party}})
        self.request("POST", "transfers", payload={"transfer": {
            "outflow_transaction_id": outgoing["id"],
            "inflow_transaction_id": incoming["id"],
        }})
        return "linked"


def load_rules(path: Path = RULES_PATH) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def classify(record: TransactionRecord, rules: list[dict]) -> tuple[str, str | None]:
    best: tuple[str, str | None] = ("其他", None)
    longest = -1
    merchant = category_merchant(record.business)
    for rule in rules:
        for pattern in rule.get("patterns", []):
            try:
                match = re.search(pattern, merchant, flags=re.IGNORECASE)
            except re.error:
                continue
            if match and len(match.group()) > longest:
                best = (rule["category"], rule.get("parent"))
                longest = len(match.group())
    return best


def sync_records(records: list[tuple[TransactionRecord, str]], *, client: SureClient, institution: str, rules: list[dict], dry_run: bool = False) -> dict[str, int]:
    counts = {"created": 0, "would_create": 0, "duplicate": 0, "ambiguous": 0, "unmatched_account": 0, "failed": 0}
    for record, mail_body in records:
        try:
            account = client.account_for(record.account, institution)
            if account is None:
                counts["unmatched_account"] += 1
                continue
            # Resolve category only when a new transaction needs writing.
            status = client.existing_transaction(account["id"], record)
            if status != "new":
                counts[status] += 1
                if status == "ambiguous":
                    logger.warning("Sure 历史流水匹配不唯一，未推送: account=%s time=%s merchant=%s", record.account, record.cost_time, record.business)
                continue
            if dry_run:
                counts["would_create"] += 1
                logger.info("Sure 预演待新增: account=%s time=%s amount=%s merchant=%s", record.account, record.cost_time, record.cost, record.business)
                continue
            if record.behaviour in ("退款", "退货", "消费撤销") or (record.behaviour == "还款" and record.payee_account_last4):
                category_id = None  # Refunds inherit their expense category; card repayments are not spending.
            else:
                category, parent = classify(record, rules)
                category_id = client.category_for(category, parent)
            counts[client.push(account["id"], record, category_id=category_id, mail_body=mail_body, institution=institution)] += 1
        except (requests.RequestException, SureSyncError, KeyError, ValueError) as exc:
            counts["failed"] += 1
            logger.error("Sure 推送失败，未重试: account=%s time=%s merchant=%s error=%s", record.account, record.cost_time, record.business, exc)
    return counts


def sync_if_enabled(records: list[tuple[TransactionRecord, str]]) -> None:
    if os.getenv("SURE_SYNC_ENABLED", "false").lower() not in ("true", "1", "yes"):
        return
    api_key = os.getenv("SURE_API_KEY", "").strip()
    if not api_key:
        logger.error("Sure 推送已启用但 SURE_API_KEY 未设置，跳过本轮")
        return
    if not records:
        return
    client = SureClient(os.getenv("SURE_API_URL", "http://sure-web:3000/api/v1"), api_key)
    try:
        rules = load_rules()
        counts = sync_records(
            records, client=client, institution=os.getenv("SURE_INSTITUTION_NAME", "中国招商银行"),
            rules=rules, dry_run=os.getenv("SURE_SYNC_DRY_RUN", "false").lower() in ("true", "1", "yes"),
        )
        logger.info("Sure 推送本轮结果: %s", counts)
    except (OSError, ValueError, requests.RequestException, SureSyncError) as exc:
        logger.error("Sure 推送本轮中止，未重试: %s", exc)


def sync_pending_from_db(conn) -> dict[str, int]:
    """Send committed Bill rows to Sure and acknowledge successful/idempotent rows."""
    from backend.ingest.db import fetch_pending_sure_rows, mark_sure_synced

    counts = {"created": 0, "duplicate": 0, "ambiguous": 0,
              "unmatched_account": 0, "failed": 0, "would_create": 0}
    if os.getenv("SURE_SYNC_ENABLED", "false").lower() not in ("true", "1", "yes"):
        return counts
    api_key = os.getenv("SURE_API_KEY", "").strip()
    if not api_key:
        logger.error("Sure 推送已启用但 SURE_API_KEY 未设置")
        return counts

    pending = fetch_pending_sure_rows(conn)
    if not pending:
        return counts
    dry_run = os.getenv("SURE_SYNC_DRY_RUN", "false").lower() in ("true", "1", "yes")
    client = SureClient(os.getenv("SURE_API_URL", "http://sure-web:3000/api/v1"), api_key)
    rules = load_rules()
    acknowledged: list[int] = []
    for row in pending:
        record = TransactionRecord(
            cost_time=row["costtime"], cost=Decimal(str(row["cost"])),
            account=row["account"], behaviour=row["behaviour"],
            business=row["business"], remain=row["remain"] or "",
            source=row["source"],
            original_cost=Decimal(str(row["original_cost"])) if row["original_cost"] is not None else None,
            original_currency=row["original_currency"],
            payer_name=row["payer_name"], payer_account_last4=row["payer_account_last4"],
            payee_name=row["payee_name"], payee_account_last4=row["payee_account_last4"],
        )
        result = sync_records(
            [(record, row["mail_body"] or "")], client=client,
            institution=os.getenv("SURE_INSTITUTION_NAME", "中国招商银行"),
            rules=rules, dry_run=dry_run,
        )
        for key, count in result.items():
            counts[key] += count
        if result["created"] or result["duplicate"]:
            acknowledged.append(row["id"])
        if len(acknowledged) >= 100:
            mark_sure_synced(conn, acknowledged)
            conn.commit()
            acknowledged.clear()
    if acknowledged:
        mark_sure_synced(conn, acknowledged)
        conn.commit()
    logger.info("Sure 数据库待同步处理结果: %s", counts)
    return counts


def sync_transfer_matches_from_db(conn, *, dry_run: bool = False) -> dict[str, int]:
    from backend.ingest.db import fetch_pending_transfer_rows, mark_transfer_match_result

    counts: dict[str, int] = {}
    if os.getenv("SURE_SYNC_ENABLED", "false").lower() not in ("true", "1", "yes"):
        return counts
    if not dry_run and os.getenv("SURE_SYNC_DRY_RUN", "false").lower() in ("true", "1", "yes"):
        return counts
    api_key = os.getenv("SURE_API_KEY", "").strip()
    if not api_key:
        return counts
    client = SureClient(os.getenv("SURE_API_URL", "http://sure-web:3000/api/v1"), api_key)
    institution = os.getenv("SURE_INSTITUTION_NAME", "中国招商银行")
    for row in fetch_pending_transfer_rows(conn):
        record = TransactionRecord(
            cost_time=row["costtime"], cost=Decimal(str(row["cost"])),
            account=row["account"], behaviour=row["behaviour"], business=row["business"],
            remain=row["remain"] or "", source=row["source"],
            original_cost=Decimal(str(row["original_cost"])) if row["original_cost"] is not None else None,
            original_currency=row["original_currency"],
            payer_name=row["payer_name"], payer_account_last4=row["payer_account_last4"],
            payee_name=row["payee_name"], payee_account_last4=row["payee_account_last4"],
        )
        try:
            status = client.match_bank_transfer(record, institution, dry_run=dry_run)
        except (requests.RequestException, SureSyncError, KeyError, ValueError) as exc:
            status = "failed"
            logger.warning("Sure 转账匹配失败: bill_id=%s error=%s", row["id"], exc)
        if not dry_run:
            mark_transfer_match_result(conn, row["id"], status)
            conn.commit()
        counts[status] = counts.get(status, 0) + 1
    if counts:
        logger.info("Sure 转账匹配结果: %s", counts)
    return counts

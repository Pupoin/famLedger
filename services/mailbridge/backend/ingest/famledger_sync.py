"""Post original-currency transactions to famLedger with stable external IDs."""
import hashlib
import json
import logging
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests

from backend.ingest.parser import parse_credit_daily_message, parse_credit_recent_message, parse_debit_message
from backend.ingest.parser import message_body_and_parse_text
from backend.ingest.account_matching import account_candidates, matching_account, message_bank

CHINA_TZ = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)


def occurred_at(record):
    value = record.cost_time
    return value.replace(tzinfo=CHINA_TZ) if value.tzinfo is None else value.astimezone(CHINA_TZ)


def external_id(record):
    merchant = " ".join(unicodedata.normalize("NFKC", record.business).strip().casefold().split()).removesuffix("支付")
    parts = [record.account.strip(), merchant, occurred_at(record).isoformat(timespec="seconds"),
             format(record.cost.normalize(), "f") if record.cost else "0", record.original_currency.strip().upper()]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def financial_kind(record):
    """Classify the bank action, with explicit exceptions for funds movements."""
    if record.behaviour in ("退款", "退货", "消费撤销"):
        return "refund"
    reclaim = record.behaviour == "溢缴款领回" or record.business.strip() == "溢缴款领回"
    repayment = record.behaviour == "还款" or (
        "信用卡还款" in record.business and not any(word in record.business for word in ("手续费", "利息")))
    # Wallet transfer payments need the user's decision about their purpose.
    # Preserve the existing transfer classification for ambiguous bank notices.
    wallet_transfer = (record.behaviour == "支付" and "转账" in record.business
                       and any(word in record.business for word in ("财付通", "支付宝"))
                       and not any(word in record.business for word in ("手续费", "利息")))
    if reclaim or repayment or wallet_transfer or record.behaviour in ("转入", "转至", "转出", "汇款", "取现"):
        return "transfer"
    return "expense" if record.cost < 0 else "income"


class DeliveryBlocked(RuntimeError):
    """Target is unavailable, throttled or rejects the configured credential."""


def post_failure_reason(status):
    """Actionable diagnostics without echoing credentials or mail/response bodies."""
    reasons = {
        400: "交易请求被拒绝，请检查交易类型、金额及关联账户",
        401: "API Key 无效、已过期或已撤销；请配置当前 famLedger 用户的有效 Key",
        403: "凭证或账户写入权限不足；请检查 Key 所属用户及账户共享权限",
        404: "POST 接口或关联账户不存在；请检查 FAMLEDGER_API_URL 和账户配置",
        409: "账户标识或转账匹配存在冲突；请检查 external_identifier 是否重复，并核对同账户、同金额的转账及通知时间",
        422: "交易字段校验失败；请检查账户标识、金额、币种和日期",
        429: "famLedger 请求频率受限，将在下一轮重试",
    }
    if status in reasons:
        return reasons[status]
    if 300 <= status < 400:
        return "目标接口返回重定向；请直接配置正确的 famLedger 后端地址"
    if status >= 500:
        return "famLedger 后端异常；请检查 famledger-app 错误日志"
    return "famLedger 返回非成功状态，请检查目标服务"


class FamLedgerClient:
    def __init__(self, base_url, api_token):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Configure a valid FAMLEDGER_API_URL without embedded credentials")
        if not api_token:
            raise ValueError("Configure FAMLEDGER_API_TOKEN before posting")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_token, "Accept": "application/json"})
        self._accounts = None

    def _transfer_accounts(self, record):
        if (not record.counterparty_bank_name or financial_kind(record) != 'transfer'
                or record.behaviour not in ('转入', '转至', '转出', '汇款', '还款')):
            return None
        tail = record.payer_account_last4 if record.cost > 0 else record.payee_account_last4
        if not tail:
            return None
        if self._accounts is None:
            try:
                response = self.session.get(self.base_url + '/api/v1/accounts', timeout=(10, 30), allow_redirects=False)
            except (requests.Timeout, requests.ConnectionError) as error:
                raise DeliveryBlocked('famLedger account lookup unavailable; 账户查询失败，缓存邮件保留待重试') from error
            if not 200 <= response.status_code < 300:
                raise DeliveryBlocked(f'famLedger account lookup failed (HTTP {response.status_code}): {post_failure_reason(response.status_code)}')
            result = response.json()
            self._accounts = result if isinstance(result, list) else result.get('accounts', result.get('items')) if isinstance(result, dict) else None
            if not isinstance(self._accounts, list):
                raise DeliveryBlocked('Unexpected famLedger account response; 账户查询结果无效，缓存邮件保留待重试')
        primary = matching_account(self._accounts, record.bank_name, record.account, account_type=record.account_type)
        primary_candidates = account_candidates(self._accounts, record.bank_name, record.account, include_unavailable=True)
        if not primary and not primary_candidates and record.original_currency.upper() == 'CNY':
            primary = {'identifier': f"{record.bank_name}{'信用卡' if record.account_type == 'credit_card' else '借记卡'}:{record.account}",
                       'currency': 'CNY', 'can_edit': True, 'can_receive_transfer': True}
        candidates = account_candidates(self._accounts, record.counterparty_bank_name, tail, include_unavailable=True)
        peer = candidates[0] if len(candidates) == 1 else None
        if not candidates:
            if (primary and primary.get('is_active') is not False and not primary.get('relationship_only')
                    and primary.get('currency') == record.original_currency.upper()
                    and (primary.get('can_receive_transfer') is True if record.cost > 0 else primary.get('can_edit') is True)):
                # Resolve/create inside the ledger transaction, never with a
                # separate POST that could leave an account after a failed import.
                return primary, {'identifier': f'{record.counterparty_bank_name}:{tail}'}
        if peer and (peer.get('is_active') is False or peer.get('relationship_only')):
            logger.warning('Bank transfer counterpart is unavailable; preserving the single bank-reported leg without creating a duplicate account')
            return None
        source, destination = (peer, primary) if record.cost > 0 else (primary, peer)
        if (not source or not destination or (source.get('id') and source.get('id') == destination.get('id'))
                or source.get('can_edit') is not True
                or not (destination.get('can_receive_transfer') is True or destination.get('can_edit') is True)
                or source.get('currency') != destination.get('currency')
                or record.original_currency.upper() != source.get('currency')):
            if source and source.get('can_edit') is not True:
                logger.warning('Bank transfer source is read-only; outgoing posting is prohibited; preserving the single bank-reported leg without creating a duplicate account')
            else:
                logger.warning('Bank transfer counterpart is ambiguous or incompatible; preserving the single bank-reported leg without creating a duplicate account')
            return None
        return primary, peer

    def push_transaction(self, record, *, mail_body=""):
        kind = financial_kind(record)
        reclaim = record.behaviour == "溢缴款领回" or record.business.strip() == "溢缴款领回"
        repayment = kind == "transfer" and (record.behaviour == "还款" or "信用卡还款" in record.business)
        bank = record.bank_name + ("信用卡" if record.account_type == "credit_card" else "借记卡")
        payload = {
            "account": f"{bank}:{record.account.strip()}", "narration": record.business,
            "amount": str(abs(record.cost)), "currency": record.original_currency.upper(),
            "occurred_at": occurred_at(record).isoformat(timespec="seconds"),
            "transaction_type": kind, "external_id": external_id(record),
            "tags": ["溢缴款领回"] if reclaim else ["信用卡还款"] if repayment else [], "notes": mail_body[:2000],
            "extra": {**({"direction": "inflow" if record.cost >= 0 else "outflow"} if kind == "transfer" else {}),
                      "import_source": "mailbridge", "bank_action": record.behaviour,
                      "bank_name": record.bank_name, "account_last4": record.account,
                      "counterparty_bank_name": record.counterparty_bank_name,
                      "counterparty": {key: getattr(record, key) for key in
                                       ("payer_name", "payer_account_last4", "payee_name", "payee_account_last4")}},
        }
        matched = self._transfer_accounts(record)
        if matched:
            primary, peer = matched
            payload['account'] = primary.get('id') or primary['identifier']
            side = 'from' if record.cost > 0 else 'to'
            if 'identifier' in peer:
                payload['extra'][f'{side}_account_identifier'] = peer['identifier']
            else:
                payload['extra'][f'{side}_account_id'] = peer['id']
        try:
            response = self.session.post(self.base_url + "/api/v1/transactions", json=payload, timeout=(10, 30), allow_redirects=False)
        except requests.Timeout as error:
            raise DeliveryBlocked("famLedger request timed out; 请求超时，请检查目标服务和网络；缓存邮件保留待重试") from error
        except requests.ConnectionError as error:
            raise DeliveryBlocked("famLedger is unreachable; 无法连接目标服务，请检查 FAMLEDGER_API_URL、容器网络和服务状态；缓存邮件保留待重试") from error
        if response.status_code < 200 or response.status_code >= 300:
            # Do not log headers, credentials, mail bodies or full response bodies.
            error_type = DeliveryBlocked if response.status_code in (401, 403, 429) or response.status_code >= 500 else RuntimeError
            raise error_type(f"famLedger POST failed (HTTP {response.status_code}): {post_failure_reason(response.status_code)}")
        result = response.json()
        if not isinstance(result, dict) or result.get("status") not in ("created", "duplicate", "pending_fx", "canceled"):
            raise RuntimeError("Unexpected famLedger transaction response; cached email retained for retry")
        if matched and result['status'] != 'canceled':
            confirmed = result.get('transfer_context_accepted') and (result['status'] == 'pending_fx' or result.get('transfer_id'))
            if not confirmed:
                raise DeliveryBlocked('famLedger did not confirm the complete transfer; 请更新目标 famLedger 后端或人工核对现有转账配对；缓存邮件保留待重试')
        if matched and any('identifier' in account for account in matched):
            # A later notice in the same batch must see the account just created.
            self._accounts = None
        return result


def sync_emails_and_parse_to_famledger(client, messages_by_kind, *, since=None, until=None):
    records = []
    processed = 0
    for kind, messages in messages_by_kind.items():
        for msg in messages:
            body, text = message_body_and_parse_text(msg)
            if kind == "credit_daily":
                parsed = parse_credit_daily_message(text)
                if not parsed and ("明细如下" in text or "尾号" in text):
                    raise ValueError("Credit daily statement could not be parsed; cached email retained for retry")
            elif kind == "credit_recent":
                parsed = parse_credit_recent_message(text)
                if not parsed:
                    raise ValueError("Credit recent statement could not be parsed; cached email retained for retry")
            elif kind == "debit":
                received = datetime.fromisoformat(msg["receivedDateTime"].replace("Z", "+00:00"))
                received = received.astimezone(CHINA_TZ).replace(tzinfo=None)
                record = parse_debit_message(text, received, bank_name=message_bank(msg))
                if record is None:
                    raise ValueError("Bank debit notice could not be parsed; cached email retained for retry")
                parsed = [record]
            else:
                continue
            processed += 1
            records.extend((record, body) for record in parsed if record.cost
                           and (since is None or occurred_at(record) >= since)
                           and (until is None or occurred_at(record) <= until))
    records.sort(key=lambda item: occurred_at(item[0]))
    created = 0
    for record, body in records:
        result = client.push_transaction(record, mail_body=body)
        created += result["status"] == "created"
    return processed, created

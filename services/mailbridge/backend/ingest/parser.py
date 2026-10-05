from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from decimal import Decimal

from backend.ingest.models import TransactionRecord

logger = logging.getLogger(__name__)


DEBIT_OUT_BEHAVIOURS = {"支付", "转至", "还款", "消费", "汇款", "支出", "扣款"}
DEBIT_IN_BEHAVIOURS = {"退款", "转入", "入账", "收款", "溢缴款领回"}
DEBIT_BEHAVIOUR_DETECT_ORDER = ("退款", "转入", "汇款", "入账", "转至", "支付", "还款", "消费", "支出", "扣款", "收款")
CREDIT_BEHAVIOURS = "消费撤销|溢缴款领回|退款|转入|转至|转出|汇款|支付|还款|入账|消费|退货|取现|手续费|利息"
CREDIT_CURRENCY = r"[A-Z]{3}|人民币|[￥¥]"


def html_to_text(content: str) -> str:
    decoded = html.unescape(content or "")
    text = re.sub(r"<[^>]+>", "", decoded)
    return text.replace("\xa0", " ")


def normalize_currency(currency: str) -> str:
    curr = str(currency or "CNY").upper().strip()
    if curr in ("￥", "¥", "RMB", "人民币"):
        return "CNY"
    return curr


def normalize_amount(raw_amount: str) -> Decimal:
    cleaned = re.sub(r"[A-Z]{3}|[￥¥,]", "", raw_amount).strip()
    amount = Decimal(cleaned)
    if not amount.is_finite():
        raise ValueError("Invalid transaction amount")
    return amount


def normalize_credit_amount_by_behaviour(amount: Decimal) -> Decimal:
    # Credit-card statement amounts use the opposite sign of asset cash flow.
    return -amount


def parse_credit_daily_message(body: str) -> list[TransactionRecord]:
    text = html_to_text(body)
    records: list[TransactionRecord] = []
    logger.debug("开始解析每日信用管家邮件，正文长度=%s", len(text))

    main_text = re.sub(r"截至昨日最后一笔交易[\s\S]*?积分余额", "", text)
    date_match = re.search(
        r"(?P<date>\d{4}/\d{2}/\d{2})\s*(?:您的消费明细如下|消费人民币[￥¥]?[\d,.]+\s*明细如下)[:：]?",
        main_text,
    )
    if not date_match:
        return records

    day_string = date_match.group("date")
    detail_text = main_text[date_match.end():].strip()
    detail_text = re.split(r"\s+(?:人民币|[A-Z]{3})消费[:：]", detail_text, maxsplit=1)[0].strip()

    # 优先按“交易块”顺序解析，兼容正文被压成一行的情况。
    # 交易块格式：18:59:01 CNY 194.00 尾号7661 消费 抖音支付-xxx
    entry_pattern = re.compile(
        r"(?P<time>\d{2}:\d{2}:\d{2})\s*"
        rf"(?P<currency>{CREDIT_CURRENCY})\s*"
        r"(?P<money>[-,\d.]+)\s*"
        r"尾号(?P<account>\d+)\s*"
        rf"(?P<behaviour>{CREDIT_BEHAVIOURS})\s*"
        r"(?P<business>.*?)"
        rf"(?=(?:\s*\d{{2}}:\d{{2}}:\d{{2}}\s*(?:{CREDIT_CURRENCY}))|$)",
        re.S,
    )

    for match in entry_pattern.finditer(detail_text):
        time_string = match.group("time")
        amount_string = match.group("money")
        currency = normalize_currency(match.group("currency"))
        account = match.group("account")
        behaviour = match.group("behaviour")
        business = match.group("business").strip()

        cost_time = datetime.strptime(f"{day_string} {time_string}", "%Y/%m/%d %H:%M:%S")
        
        
        records.append(
            TransactionRecord(
                cost_time=cost_time,
                cost=normalize_credit_amount_by_behaviour(
                    normalize_amount(amount_string)
                ),
                account=account,
                behaviour=behaviour,
                business=business,
                account_type="credit_card",
                original_currency=currency,
            )
        )

    expected_rows = len(re.findall(
        rf"\d{{2}}:\d{{2}}:\d{{2}}\s*(?:{CREDIT_CURRENCY})\s*[-,\d.]+\s*尾号\d+",
        detail_text,
    ))
    if records and len(records) != expected_rows:
        raise ValueError("Credit daily statement contains unrecognized transaction rows; cached email retained for retry")
    if records:
        logger.debug("每日信用管家交易块解析完成: row_count=%s", len(records))
        return records

    # 备选方案：按行解析
    times: list[datetime] = []
    amounts: list[Decimal] = []
    currencies: list[str] = []
    accounts: list[str] = []
    behaviours: list[str] = []
    businesses: list[str] = []

    for line in main_text.splitlines():
        line = line.strip()
        if not line:
            continue

        time_match = re.match(r"^(?P<time>\d{2}:\d{2}:\d{2})$", line)
        if time_match:
            times.append(datetime.strptime(f"{day_string} {time_match.group('time')}", "%Y/%m/%d %H:%M:%S"))
            continue

        money_match = re.search(r"(?P<currency>[A-Z]{3}|[￥¥])\s*(?P<money>[-,\d.]+)", line)
        if money_match:
            currency = money_match.group("currency")
            currencies.append(currency)
            amounts.append(normalize_amount(money_match.group("money")))
            continue

        account_match = re.match(r"^尾号(?P<info>.+)$", line)
        if account_match:
            parts = account_match.group("info").split()
            if len(parts) >= 3:
                accounts.append(parts[0])
                behaviours.append(parts[1])
                businesses.append(" ".join(parts[2:]))

    row_count = min(len(times), len(amounts), len(accounts), len(behaviours), len(businesses))
    for index in range(row_count):
        curr_time = times[index]
        curr_amount = amounts[index]
        curr_currency = normalize_currency(currencies[index]) if index < len(currencies) else "CNY"
        curr_behaviour = behaviours[index]
        records.append(
            TransactionRecord(
                cost_time=curr_time,
                cost=normalize_credit_amount_by_behaviour(
                    curr_amount
                ),
                account=accounts[index],
                behaviour=curr_behaviour,
                business=businesses[index],
                account_type="credit_card",
                original_currency=curr_currency,
            )
        )

    logger.debug("每日信用管家解析完成: row_count=%s", len(records))

    return records


def parse_credit_recent_message(body: str) -> list[TransactionRecord]:
    records: list[TransactionRecord] = []
    logger.debug("开始解析近期消费明细邮件，正文长度=%s", len(body or ""))
    # 更加宽松的正则，支持商户名包含空格（只要后面紧跟 行为 和 金额）
    line_regex = re.compile(
        r"^(?P<account>\d+)\s+(?P<date>\d{4}/\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<currency>\S+)\s+(?P<business>.+?)\s+(?P<behaviour>\S+)\s+(?P<money>[-,\d.]+)$"
    )

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("."):
            continue
        match = line_regex.match(line)
        if not match:
            continue

        cost_time = datetime.strptime(
            f"{match.group('date')} {match.group('time')}", "%Y/%m/%d %H:%M:%S"
        )
        # 提取原始数值和币种
        raw_money_str = match.group("money")
        currency = normalize_currency(match.group("currency"))

        records.append(
            TransactionRecord(
                cost_time=cost_time,
                account=match.group("account"),
                behaviour=match.group("behaviour"),
                cost=normalize_credit_amount_by_behaviour(
                    normalize_amount(raw_money_str)
                ),
                business=match.group("business"),
                account_type="credit_card",
                original_currency=currency,
            )
        )
    logger.debug("近期消费明细解析完成: row_count=%s", len(records))
    return records


def detect_debit_behaviour(content: str) -> str:
    # The bank action closest to the amount wins over words in merchant names.
    matches = [(content.rfind(category), category) for category in DEBIT_BEHAVIOUR_DETECT_ORDER]
    position, category = max(matches)
    return category if position >= 0 else "其他"


def parse_transfer_parties(content: str) -> dict[str, str]:
    """Extract parties from CMB debit notices without guessing account ownership."""
    parties: dict[str, str] = {}
    for label, key in (("付方", "payer"), ("收方", "payee")):
        match = re.search(rf"{label}\s*[:：]?\s*(?P<name>[^，,；;\n（）()]{{0,80}}?)\s*[（(]\s*(?P<last4>\d{{4}})\s*[）)]", content)
        if not match:
            match = re.search(
                rf"{label}\s*[:：]?\s*(?P<name>[^，,；;\n（）()]{{1,80}})[，,]\s*"
                rf"(?:账号|账户)(?:尾号|尾数|末四位)\s*[:：]?\s*(?P<last4>\d{{4}})",
                content,
            )
        if match:
            parties[f"{key}_name"] = match.group("name").strip()
            parties[f"{key}_account_last4"] = match.group("last4")
    return parties


def parse_debit_message(body: str, received_time: datetime) -> TransactionRecord | None:
    content = html_to_text(body)
    parties = parse_transfer_parties(content)
    # Card tails before the currency are identifiers, never transaction amounts.
    # Match this bank template first so the general notice pattern cannot read
    # "向尾号为9249...还款人民币13.00" as a ¥9,249 inflow.
    card_repayment = re.search(
        r"(?:您的[^\d]+|您账户)(?P<account>\d+)于(?P<date>\d{2}月\d{2}日)"
        r"(?P<time>\d{2}:\d{2})?[，,\s]*"
        r"(?P<merchant>向尾号为(?P<card_tail>\d{4})的信用卡还款)"
        r"人民币(?P<amount>[\d,]+(?:\.\d+)?)元?.*?余额(?P<balance>[\d,]+(?:\.\d+)?)",
        content,
        flags=re.S,
    )
    pattern = re.compile(
        r"(?:您的[^\d]+|您账户)(?P<account>\d+)于(?P<date>\d{2}月\d{2}日)(?P<time>\d{2}:\d{2})?[，,\s]*在?(?P<merchant>.*?)(?:支付|消费|支出|转账)?(?:人民币|CNY|￥|[A-Z]{3})?(?P<amount>[\d,]+(?:\.\d+)?)元?.*?余额(?P<balance>[\d,]+(?:\.\d+)?)",
        flags=re.S,
    )
    match = card_repayment or pattern.search(content)
    explicit_behaviour = None
    if not match:
        # Some incoming notices omit the account balance entirely.
        match = re.search(
            r"您账户(?P<account>\d+)于\d{2}月\d{2}日(?:\d{2}:\d{2})?"
            r"[，,\s]*(?P<merchant>(?:收到)?(?:本行|他行)?(?:卡)?(?:实时)?转入)"
            r"人民币(?P<amount>[\d,]+(?:\.\d+)?)",
            content,
        )
        if match:
            explicit_behaviour = "转入"
    if not match:
        match = re.search(
            r"您账户(?P<account>\d+)于\d{2}月\d{2}日(?:\d{2}:\d{2})?"
            r"[，,\s]*(?P<merchant>转账汇款|汇款|转出|转至)"
            r"人民币(?P<amount>[\d,]+(?:\.\d+)?)",
            content,
        )
        if match:
            explicit_behaviour = "汇款"
            payee = re.search(r"收款人[:：]\s*([^，,\r\n]+)", content[match.end():])
            if payee:
                parties["payee_name"] = payee.group(1).strip()
    if not match:
        match = re.search(
            r"您账户(?P<account>\d+)定制的(?P<merchant>自动转账)执行成功"
            r"[（(]收款人(?P<payee>[^，,]+)[，,]\s*收款账号(?P<payee_account>\d+)"
            r"[，,]\s*金额(?:人民币)?(?P<amount>[\d,]+(?:\.\d+)?)元?[）)]",
            content,
        )
        if match:
            explicit_behaviour = "转至"
            parties["payee_name"] = match.group("payee").strip()
            parties["payee_account_last4"] = match.group("payee_account")[-4:]
    if not match:
        match = re.search(
            r"招商银行(?P<merchant>支付鼓励金)已于\d{2}月\d{2}日\d{2}:\d{2}"
            r"成功入账至您的招商银行储蓄卡(?P<account>\d+)[，,]\s*"
            r"人民币(?P<amount>[\d,]+(?:\.\d+)?)元[，,]\s*"
            r"余额(?P<balance>[\d,]+(?:\.\d+)?)元?",
            content,
        )
        if match:
            explicit_behaviour = "入账"
    if not match:
        logger.error("借记卡通知未命中正则")
        return None

    # The payer and free-text remark may contain words such as "退款".  Only
    # the bank's transaction phrase before the amount determines direction.
    behaviour = explicit_behaviour or detect_debit_behaviour(content[:match.start("amount")])
    if re.match(r"\s*溢缴款领回入账通知[，,]", content):
        behaviour = "溢缴款领回"
    if behaviour == "收款" and any(word in content[match.end("amount"):] for word in
                                   ("微信零钱提现", "支付宝提现", "支付宝转账", "一网通账户提现")):
        behaviour = "转入"
    if card_repayment:
        parties["payee_account_last4"] = card_repayment.group("card_tail")

    amount = normalize_amount(match.group("amount"))
    if behaviour in DEBIT_OUT_BEHAVIOURS:
        amount = -amount
    elif behaviour in DEBIT_IN_BEHAVIOURS:
        amount = amount
    else:
        raise ValueError("Unrecognized bank transaction direction")
    
    record = TransactionRecord(
        cost_time=received_time,
        cost=amount,
        account=match.group("account"),
        behaviour=behaviour,
        business=match.group("merchant").strip(),
        original_currency="CNY",
        **parties,
    )
    return record



def message_body_and_parse_text(msg: dict) -> tuple[str, str]:
    """Return readable body text for famLedger notes and parser text with preview fallback."""
    raw_body = (msg.get("body") or {}).get("content") or ""
    readable_html = re.sub(r"<br\s*/?>", "\n", raw_body, flags=re.IGNORECASE)
    body_text = html_to_text(readable_html) if raw_body else ""
    # Table cells must stay separate: stripping tags merged card/date/currency
    # and silently produced zero rows for every recent-credit HTML statement.
    parser_html = re.sub(r"</(?:td|th)\s*>", "\t", readable_html, flags=re.IGNORECASE)
    parser_html = re.sub(r"</tr\s*>", "\n", parser_html, flags=re.IGNORECASE)
    parser_text = html_to_text(parser_html) if raw_body else ""
    return body_text, parser_text or msg.get("bodyPreview", "")

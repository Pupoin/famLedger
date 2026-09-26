from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from backend.ingest.currency_utils import convert_to_cny
from backend.ingest.models import DailyCreditSummary, TransactionRecord

logger = logging.getLogger(__name__)


CREDIT_ACCOUNTS = {"9085", "7661"}
DEBIT_ACCOUNTS = {"6061"}
DEBIT_OUT_BEHAVIOURS = {"支付", "转至", "还款", "消费", "汇款"}
DEBIT_IN_BEHAVIOURS = {"退款", "转入", "入账"}
DEBIT_BEHAVIOUR_DETECT_ORDER = ("退款", "转入", "汇款", "入账", "转至", "支付", "还款")


def html_to_text(content: str) -> str:
    decoded = html.unescape(content or "")
    text = re.sub(r"<[^>]+>", "", decoded)
    return text.replace("\xa0", " ")


def _extract_remain_and_score(section_text: str) -> tuple[Decimal, Decimal] | None:
    normalized = re.sub(r"\s+", " ", section_text).strip()
    pattern = re.compile(
        r"[￥¥]\s*(?P<remain>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\D+(?P<score>(?:\d{1,3}(?:,\d{3})+|\d+))(?!\d)"
    )
    match = pattern.search(normalized)
    if not match:
        return None
    remain_money = normalize_amount(match.group("remain"))
    score = normalize_amount(match.group("score"))
    return remain_money, score


def normalize_currency(currency: str) -> str:
    curr = str(currency or "CNY").upper().strip()
    if curr in ("￥", "¥", "RMB"):
        return "CNY"
    return curr


def normalize_amount(raw_amount: str, currency: str = "CNY", date: datetime | None = None) -> Decimal:
    # 移除常见的币种前缀/符号和千分位
    cleaned = re.sub(r"[A-Z]{3}|[￥¥,]", "", raw_amount).strip()
    try:
        amount = Decimal(cleaned)
        if date and currency:
            return convert_to_cny(amount, currency, date)
        return amount
    except Exception:
        logger.error("金额转换失败: raw=%s, cleaned=%s", raw_amount, cleaned)
        return Decimal("0")


def normalize_credit_amount_by_behaviour(amount: Decimal, behaviour: str) -> Decimal:
    # if behaviour in ("消费", "支付"):
    #     return -abs(amount)
    # if behaviour in ("退货", "退款"):
    #     return abs(amount)
    # else:
    #     logger.warning("遇到未知的信用卡交易行为 '%s'，默认按正数处理金额: %s", behaviour, amount)
    return -amount


def parse_credit_daily_message(body: str) -> tuple[list[TransactionRecord], DailyCreditSummary | None]:
    text = html_to_text(body)
    records: list[TransactionRecord] = []
    logger.debug("开始解析每日信用管家邮件，正文长度=%s", len(text))
    logger.debug("每日信用管家邮件正文预览: %s", text.strip())

    remain_money = Decimal("0")
    score = Decimal("0")

    # 复刻原脚本提取额度/积分逻辑。
    # 先截取“您的额度和积分信息如下：...可用额度”之间的文本，再提取 ￥额度 和 积分。
    credit_section_match = re.search(r"您的额度和积分信息如下：(?P<section>[\s\S]*?)可用额度", text)
    if credit_section_match:
        section = credit_section_match.group("section")
        extracted = _extract_remain_and_score(section)
        if extracted:
            remain_money, score = extracted
            logger.debug("提取额度/积分成功: remain=%s score=%s", remain_money, score)
        else:
            logger.debug("未命中额度/积分正则: section=%s", section)

    main_text = re.sub(r"截至昨日最后一笔交易[\s\S]*?积分余额", "", text)
    date_match = re.search(r"(?P<date>\d{4}/\d{2}/\d{2})\s*您的消费明细如下[:：]?", main_text)
    if not date_match:
        logger.debug("未命中消费明细日期段，返回仅摘要信息")
        summary = DailyCreditSummary(used_credit_limit=Decimal("60000") - remain_money, score=score)
        return records, summary

    day_string = date_match.group("date")
    detail_text = main_text[date_match.end():].strip()

    # 优先按“交易块”顺序解析，兼容正文被压成一行的情况。
    # 交易块格式：18:59:01 CNY 194.00 尾号7661 消费 抖音支付-xxx
    entry_pattern = re.compile(
        r"(?P<time>\d{2}:\d{2}:\d{2})\s*"
        r"(?P<currency>[A-Z]{3}|[￥¥])\s*"
        r"(?P<money>[-,\d.]+)\s*"
        r"尾号(?P<account>\d+)\s*"
        r"(?P<behaviour>退款|转入|转至|汇款|支付|还款|入账|消费撤销|消费|退货)\s*"
        r"(?P<business>.*?)"
        r"(?=(?:\s+\d{2}:\d{2}:\d{2}\s*(?:[A-Z]{3}|[￥¥]))|$)"
    )

    for match in entry_pattern.finditer(detail_text):
        time_string = match.group("time")
        amount_string = match.group("money")
        currency = normalize_currency(match.group("currency"))
        account = match.group("account")
        behaviour = match.group("behaviour")
        business = match.group("business").strip()

        cost_time = datetime.strptime(f"{day_string} {time_string}", "%Y/%m/%d %H:%M:%S")
        
        # 提取原始数值
        cleaned_money = Decimal(re.sub(r"[A-Z]{3}|[￥¥,]", "", amount_string).strip())
        
        records.append(
            TransactionRecord(
                cost_time=cost_time,
                cost=normalize_credit_amount_by_behaviour(
                    normalize_amount(amount_string, currency, cost_time), behaviour
                ),
                account=account,
                behaviour=behaviour,
                business=business,
                remain="",
                source="每日信用管家",
                original_cost=normalize_credit_amount_by_behaviour(cleaned_money, behaviour),
                original_currency=currency,
            )
        )
        logger.debug(
            "命中交易块: time=%s money=%s currency=%s account=%s behaviour=%s business=%s",
            time_string,
            amount_string,
            currency,
            account,
            behaviour,
            business,
        )

    if records:
        logger.debug("每日信用管家交易块解析完成: row_count=%s", len(records))
        summary = DailyCreditSummary(used_credit_limit=Decimal("60000") - remain_money, score=score)
        return records, summary

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
            logger.debug("命中时间行: %s", line)
            continue

        money_match = re.search(r"(?P<currency>[A-Z]{3}|[￥¥])\s*(?P<money>[-,\d.]+)", line)
        if money_match:
            currency = money_match.group("currency")
            currencies.append(currency)
            amounts.append(normalize_amount(money_match.group("money")))
            logger.debug("命中金额行: %s", line)
            continue

        account_match = re.match(r"^尾号(?P<info>.+)$", line)
        if account_match:
            parts = account_match.group("info").split()
            if len(parts) >= 3:
                accounts.append(parts[0])
                behaviours.append(parts[1])
                businesses.append(" ".join(parts[2:]))
                logger.debug("命中尾号行: account=%s behaviour=%s business=%s", parts[0], parts[1], " ".join(parts[2:]))

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
                    convert_to_cny(curr_amount, curr_currency, curr_time), curr_behaviour
                ),
                account=accounts[index],
                behaviour=curr_behaviour,
                business=businesses[index],
                remain="",
                source="每日信用管家",
                original_cost=normalize_credit_amount_by_behaviour(curr_amount, curr_behaviour),
                original_currency=curr_currency,
            )
        )

    logger.debug("每日信用管家解析完成: row_count=%s", len(records))

    summary = DailyCreditSummary(used_credit_limit=Decimal("60000") - remain_money, score=score)
    return records, summary


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
            logger.debug("近期消费明细未匹配行: %s", line)
            continue

        cost_time = datetime.strptime(
            f"{match.group('date')} {match.group('time')}", "%Y/%m/%d %H:%M:%S"
        )
        # 提取原始数值和币种
        raw_money_str = match.group("money")
        currency = normalize_currency(match.group("currency"))
        cleaned_money = Decimal(re.sub(r"[A-Z]{3}|[￥¥,]", "", raw_money_str).strip())

        records.append(
            TransactionRecord(
                cost_time=cost_time,
                account=match.group("account"),
                behaviour=match.group("behaviour"),
                cost=normalize_credit_amount_by_behaviour(
                    normalize_amount(raw_money_str, currency, cost_time), 
                    match.group("behaviour")
                ),
                business=match.group("business"),
                remain="",
                source="近期消费明细",
                original_cost=normalize_credit_amount_by_behaviour(cleaned_money, match.group("behaviour")),
                original_currency=currency,
            )
        )
        logger.debug(
            "近期消费明细命中: account=%s time=%s behaviour=%s money=%s",
            match.group("account"),
            f"{match.group('date')} {match.group('time')}",
            match.group("behaviour"),
            match.group("money"),
        )
    logger.debug("近期消费明细解析完成: row_count=%s", len(records))
    return records


def detect_debit_behaviour(content: str) -> str:
    for category in DEBIT_BEHAVIOUR_DETECT_ORDER:
        if category in content:
            return category
    return "其他"


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
    logger.debug("开始解析借记卡通知: content=%s received_time=%s", content, received_time)
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
    if not match:
        logger.error("借记卡通知未命中正则")
        return None

    # The payer and free-text remark may contain words such as "退款".  Only
    # the bank's transaction phrase before the amount determines direction.
    behaviour = detect_debit_behaviour(content[:match.start("amount")])
    if card_repayment:
        parties["payee_account_last4"] = card_repayment.group("card_tail")

    amount = normalize_amount(match.group("amount"), "CNY", received_time)
    if behaviour in DEBIT_OUT_BEHAVIOURS:
        amount = -amount
    elif behaviour in DEBIT_IN_BEHAVIOURS:
        amount = amount
    else:
        logger.warning("遇到未知的借记卡交易行为 '%s'，默认按正数处理金额: %s", behaviour, amount)
    
    record = TransactionRecord(
        cost_time=received_time,
        cost=amount,
        account=match.group("account"),
        behaviour=behaviour,
        business=match.group("merchant").strip(),
        remain=str(normalize_amount(match.group("balance"), "CNY", received_time)),
        source="借记卡账户变动通知",
        original_cost=amount,
        original_currency="CNY",
        **parties,
    )
    logger.debug(
        "借记卡通知解析成功: account=%s behaviour=%s business=%s cost=%s remain=%s",
        record.account,
        record.behaviour,
        record.business,
        record.cost,
        record.remain,
    )
    return record


def parse_credit_messages(messages: Iterable[dict], subject_keyword: str) -> tuple[list[TransactionRecord], DailyCreditSummary | None]:
    all_records: list[TransactionRecord] = []
    latest_summary: DailyCreditSummary | None = None

    for msg in messages:
        body = (msg.get("body") or {}).get("content") or msg.get("bodyPreview", "")
        subject = msg.get("subject", "")
        if subject_keyword in subject:
            if "每日信用管家" in subject_keyword:
                records, summary = parse_credit_daily_message(body)
                all_records.extend(records)
                latest_summary = summary or latest_summary
            elif "近期消费明细" in subject_keyword:
                all_records.extend(parse_credit_recent_message(body))

    return all_records, latest_summary

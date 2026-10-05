from decimal import Decimal
from backend.ingest.parser import parse_credit_daily_message, parse_credit_recent_message


def test_foreign_daily_preserves_original_currency_and_amount():
    records = parse_credit_daily_message("2024/05/15 您的消费明细如下： 12:00:00 SGD 10.00 尾号7661 消费 AMAZON SG 13:00:00 CNY 100.00 尾号7661 消费 京东支付")
    assert len(records) == 2
    assert records[0].cost == Decimal("-10.00")
    assert records[0].original_currency == "SGD"
    assert records[1].cost == Decimal("-100.00")


def test_foreign_recent_preserves_original_currency_and_amount():
    records = parse_credit_recent_message("7661 2024/05/15 12:00:00 SGD AMAZON SG 消费 10.00")
    assert records[0].cost == Decimal("-10.00")
    assert records[0].original_currency == "SGD"
    assert records[0].account_type == "credit_card"

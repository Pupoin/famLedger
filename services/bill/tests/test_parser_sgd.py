from unittest.mock import patch
from decimal import Decimal
from backend.ingest.parser import parse_credit_daily_message, parse_credit_recent_message

def rates(day, currency):
    assert day == "2024-05-15"
    return {"USD": "0.74"} if currency == "SGD" else {"CNY": "7.2"}


@patch("backend.ingest.currency_utils.get_exchange_rates", side_effect=rates)
def test_sgd_daily(mock_rates):
    body = """
    截至昨日最后一笔交易，您的额度和积分信息如下： ￥44,603.77   972   可用额度   积分余额
    2024/05/15 您的消费明细如下：
    12:00:00 SGD 10.00 尾号7661 消费 AMAZON SG
    13:00:00 CNY 100.00 尾号7661 消费 京东支付
    """
    records, summary = parse_credit_daily_message(body)
    assert len(records) == 2
    assert records[0].cost == Decimal("-53.28")
    assert records[0].original_cost == Decimal("-10.00")
    assert records[0].original_currency == "SGD"
    assert records[0].business == "AMAZON SG"
    assert records[1].cost == Decimal("-100.00")
    assert records[1].business == "京东支付"

@patch("backend.ingest.currency_utils.get_exchange_rates", side_effect=rates)
def test_sgd_recent(mock_rates):
    body = "7661    2024/05/15      12:00:00        SGD     AMAZON SG       消费    10.00"
    records = parse_credit_recent_message(body)
    assert len(records) == 1
    assert records[0].cost == Decimal("-53.28")
    assert records[0].original_cost == Decimal("-10.00")
    assert records[0].original_currency == "SGD"
    assert records[0].business == "AMAZON SG"
    assert records[0].account == "7661"

if __name__ == "__main__":
    test_sgd_daily()
    test_sgd_recent()
    print("SGD parsing tests passed!")

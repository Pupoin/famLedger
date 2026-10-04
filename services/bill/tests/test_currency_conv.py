import unittest
from unittest.mock import patch
from datetime import datetime
from decimal import Decimal
from backend.ingest.parser import parse_credit_daily_message

class TestCurrencyConversion(unittest.TestCase):
    @patch("backend.ingest.currency_utils.get_exchange_rates")
    def test_sgd_to_cny_conversion(self, mock_rates):
        # 模拟 2024-05-15 的汇率
        mock_rates.side_effect = lambda day, currency: (
            {"USD": 0.74146} if currency == "SGD" else {"CNY": 7.2205}
        )
        
        body = """
        2024/05/15 您的消费明细如下：
        12:00:00 SGD 100.00 尾号7661 消费 AMAZON SG
        """
        records, _ = parse_credit_daily_message(body)
        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(float(records[0].cost), -535.37, places=2)
        self.assertEqual(records[0].original_cost, Decimal("-100.00"))
        self.assertEqual(records[0].original_currency, "SGD")

    @patch("backend.ingest.currency_utils.get_exchange_rates")
    def test_usd_to_cny_conversion(self, mock_rates):
        mock_rates.return_value = {"CNY": 7.2205}
        
        body = """
        2024/05/15 您的消费明细如下：
        14:00:00 USD 50.00 尾号7661 消费 OPENAI
        """
        records, _ = parse_credit_daily_message(body)
        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(float(records[0].cost), -361.025, places=2)

if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch
from datetime import datetime
from decimal import Decimal
from backend.ingest.currency_utils import convert_to_cny

class TestStrictCurrencyConversion(unittest.TestCase):
    @patch("backend.ingest.currency_utils.get_exchange_rates")
    def test_strict_sgd_usd_cny_path(self, mock_rates):
        # 模拟 2024-05-15 的汇率
        # 第一步：SGD -> USD
        # 第二步：USD -> CNY
        
        def side_effect(date, from_curr):
            if from_curr == "SGD":
                return {"USD": 0.74146}
            if from_curr == "USD":
                return {"CNY": 7.2205}
            return None
        
        mock_rates.side_effect = side_effect
        
        amount = Decimal("100.00")
        date = datetime(2024, 5, 15)
        
        result_cny = convert_to_cny(amount, "SGD", date)
        
        # 预计算：100 SGD * 0.74146 = 74.146 USD
        # 74.146 USD * 7.2205 = 535.3712...
        expected = Decimal("100.00") * Decimal("0.74146") * Decimal("7.2205")
        
        self.assertAlmostEqual(float(result_cny), float(expected), places=2)
        # 确保调用了两次 API (分别针对 SGD 和 USD)
        self.assertEqual(mock_rates.call_count, 2)

if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime
from decimal import Decimal

from backend.dashboard.analytics import build_stats


class AnalyticsTests(unittest.TestCase):
    def test_build_stats_accepts_lowercase_costtime(self) -> None:
        rows = [
            {
                "costtime": datetime(2026, 3, 7, 9, 0, 0),
                "cost": -20.0,
                "account": "6061",
                "behaviour": "支付",
                "business": "测试商户",
                "remain": "100.00",
                "source": "借记卡账户变动通知",
            }
        ]
        stats = build_stats(rows, Decimal("100.00"), datetime(2026, 3, 7, 12, 0, 0))
        self.assertEqual(stats.today_spending, Decimal("-20.0"))
        self.assertIn("costTime", stats.detail_df.columns)

    def test_build_stats_month_to_now_and_split_card_totals(self) -> None:
        now = datetime(2026, 3, 7, 12, 0, 0)
        rows = [
            {
                "costTime": datetime(2026, 3, 1, 0, 30, 0),
                "cost": -100.0,
                "account": "6061",
                "behaviour": "支付",
                "business": "借记卡消费",
                "remain": "900.00",
                "source": "借记卡账户变动通知",
            },
            {
                "costTime": datetime(2026, 3, 1, 1, 0, 0),
                "cost": 300.0,
                "account": "6061",
                "behaviour": "转入",
                "business": "借记卡入账",
                "remain": "1200.00",
                "source": "借记卡账户变动通知",
            },
            {
                "costTime": datetime(2026, 3, 2, 8, 0, 0),
                "cost": 500.0,
                "account": "9085",
                "behaviour": "消费",
                "business": "信用卡消费",
                "remain": "",
                "source": "每日信用管家",
            },
            {
                "costTime": datetime(2026, 3, 2, 9, 0, 0),
                "cost": -20.0,
                "account": "9085",
                "behaviour": "退货",
                "business": "信用卡退货",
                "remain": "",
                "source": "每日信用管家",
            },
            {
                "costTime": datetime(2026, 3, 31, 23, 0, 0),
                "cost": -999.0,
                "account": "6061",
                "behaviour": "支付",
                "business": "未来记录",
                "remain": "1.00",
                "source": "借记卡账户变动通知",
            },
        ]
        stats = build_stats(rows, Decimal("1200.00"), now)
        self.assertEqual(stats.month_debit_income, Decimal("300.0"))
        self.assertEqual(stats.month_debit_outcome, Decimal("-100.0"))
        self.assertEqual(stats.month_credit_income, Decimal("500.0"))
        self.assertEqual(stats.month_credit_outcome, Decimal("-20.0"))
        self.assertEqual(stats.month_income, Decimal("800.0"))
        self.assertEqual(stats.month_outcome, Decimal("-120.0"))


if __name__ == "__main__":
    unittest.main()

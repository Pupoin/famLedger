import unittest
from datetime import datetime
from decimal import Decimal

from backend.ingest.parser import parse_credit_daily_message, parse_credit_recent_message, parse_debit_message


class ParserTests(unittest.TestCase):
    def test_credit_daily_single_line_details_parse_in_order(self) -> None:
        body = (
            "截至昨日最后一笔交易，您的额度和积分信息如下： ￥44,603.77   972   可用额度   积分余额 "
            "2026/02/15 您的消费明细如下： "
            "18:59:01 CNY 194.00 尾号7661 消费 抖音支付-抖音生活服务/所见所得 "
            "19:03:52 CNY -194.00 尾号7661 退货 抖音支付-抖音生活服务/所见所得 "
            "19:04:09 CNY 188.00 尾号7661 消费 抖音支付-抖音生活服务/所见所得"
        )
        rows = parse_credit_daily_message(body)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].cost_time, datetime(2026, 2, 15, 18, 59, 1))
        self.assertEqual(rows[0].cost, Decimal("-194.00"))
        self.assertEqual(rows[0].account, "7661")
        self.assertEqual(rows[0].behaviour, "消费")
        self.assertEqual(rows[0].business, "抖音支付-抖音生活服务/所见所得")
        self.assertEqual(rows[1].cost, Decimal("194.00"))
        self.assertEqual(rows[1].behaviour, "退货")

    def test_credit_recent(self) -> None:
        body = """
9085    2026/03/06      17:49:52        CNY     财付通-中山大学 消费    16.00
9085    2026/03/06      09:10:22        CNY     美团外卖 支付    28.50
        """.strip()
        rows = parse_credit_recent_message(body)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].account, "9085")
        self.assertEqual(rows[0].cost, Decimal("-16.00"))

    def test_debit_parse(self) -> None:
        body = "您的账户6061于03月06日12:22在地铁闸机支付人民币8.00元，余额1,234.88"
        row = parse_debit_message(body, datetime(2026, 3, 6, 12, 23, 0))
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.account, "6061")
        self.assertEqual(row.cost, Decimal("-8.00"))

    def test_debit_transfer_parties(self) -> None:
        body = "您账户7931于08月22日收到本行转入人民币500.00，余额543.78，付方张三（9459），备注：转账"
        row = parse_debit_message(body, datetime(2026, 8, 22, 10, 20, 30))
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual((row.account, row.cost, row.behaviour), ("7931", Decimal("500.00"), "转入"))
        self.assertEqual((row.payer_name, row.payer_account_last4), ("张三", "9459"))
        self.assertIsNone(row.payee_account_last4)

    def test_debit_transfer_payer_with_account_tail_label(self) -> None:
        body = "您账户2238于08月06日收到本行转入人民币1500.00，余额1500.04，付方袁朝阳，账号尾号0362，备注：面核二类户账户充值"
        row = parse_debit_message(body, datetime(2026, 8, 6, 17, 32, 6))
        assert row is not None
        self.assertEqual((row.account, row.cost, row.behaviour), ("2238", Decimal("1500.00"), "转入"))
        self.assertEqual((row.payer_name, row.payer_account_last4), ("袁朝阳", "0362"))

    def test_card_repayment_tail_is_not_mistaken_for_amount(self) -> None:
        body = "您账户6061于09月07日21:55向尾号为9249的信用卡还款人民币13.00元，余额317.64元，收款人袁朝阳，请以收款人实际入账为准。"
        row = parse_debit_message(body, datetime(2025, 9, 7, 21, 55, 56))
        assert row is not None
        self.assertEqual((row.account, row.cost, row.behaviour), ("6061", Decimal("-13.00"), "还款"))
        self.assertEqual(row.business, "向尾号为9249的信用卡还款")
        self.assertEqual(row.payee_account_last4, "9249")

    def test_transfer_remark_does_not_change_transaction_direction(self) -> None:
        body = "您账户7931于08月22日收到本行转入人民币500.00，余额543.78，付方张三（9459），备注：退款约定"
        row = parse_debit_message(body, datetime(2026, 8, 22, 10, 20, 30))
        assert row is not None
        self.assertEqual(row.behaviour, "转入")
        self.assertEqual(row.cost, Decimal("500.00"))


if __name__ == "__main__":
    unittest.main()

from datetime import datetime
from decimal import Decimal
import pytest

from backend.ingest.parser import parse_debit_message


def test_incoming_notice_without_balance_does_not_invent_zero_balance():
    record = parse_debit_message(
        "您账户1234于10月03日他行实时转入人民币1200.50，付方测试用户",
        datetime(2026, 10, 3, 12),
    )
    assert record.account == "1234"
    assert record.behaviour == "转入"
    assert record.cost == Decimal("1200.50")


def test_successful_automatic_transfer_is_an_outflow_not_recipient_account_amount():
    record = parse_debit_message(
        "您账户1234定制的自动转账执行成功（收款人测试用户，收款账号9876，金额207.08），请登录招商银行App查询详情。",
        datetime(2026, 10, 3, 12),
    )
    assert record.account == "1234"
    assert record.behaviour == "转至"
    assert record.cost == Decimal("-207.08")
    assert record.payee_account_last4 == "9876"


def test_incentive_credit_is_income_despite_payment_word_in_merchant():
    record = parse_debit_message(
        "招商银行支付鼓励金已于10月03日12:35成功入账至您的招商银行储蓄卡1234，人民币0.88元，余额1000.88元",
        datetime(2026, 10, 3, 12, 35),
    )
    assert record.account == "1234"
    assert record.behaviour == "入账"
    assert record.business == "支付鼓励金"
    assert record.cost == Decimal("0.88")


def test_failed_automatic_transfer_does_not_create_transaction():
    assert parse_debit_message(
        "您账户1234定制的自动转账执行失败（收款人测试用户，收款账号9876，金额207.08）",
        datetime(2026, 10, 3, 12),
    ) is None


def test_debit_consumption_expenditure_and_deduction_notices_are_outflows():
    for behaviour in ("消费", "支出", "扣款"):
        record = parse_debit_message(
            f"您账户1234于10月03日12:35在测试商户{behaviour}人民币2.99元，余额1000.88元",
            datetime(2026, 10, 3, 12, 35),
        )
        assert record.behaviour == behaviour
        assert record.cost == Decimal("-2.99")


@pytest.mark.parametrize('body,behaviour,amount', [
    ('您账户0362于10月11日收到本行卡转入人民币20.00，付方测试甲，账号尾号0553，备注：一网通账户提现', '转入', '20.00'),
    ('您账户0362于10月12日00:13转账汇款人民币3.20，收款人：测试甲，请以收款人实际入账为准', '汇款', '-3.20'),
    ('您账户3888于01月20日23:50收款97.36元，余额632.10，备注：财付通-测试甲-', '收款', '97.36'),
    ('您账户3888于05月12日09:40收款169.60元，余额186.19，备注：支付宝-测试甲-测试甲支付宝转账', '转入', '169.60'),
    ('您账户7931于06月24日09:51收款440.08元，余额840.00，备注：财付通-测试乙-微信零钱提现', '转入', '440.08'),
    ('您账户7931于07月06日10:40收款151.92元，余额794.46，备注：财付通-测试乙-微信零钱提现', '转入', '151.92'),
    ('您账户7931于07月07日22:09收款69.00元，余额507.37，备注：财付通-测试乙-微信零钱提现', '转入', '69.00'),
])
def test_previously_failed_debit_templates(body, behaviour, amount):
    record = parse_debit_message(body, datetime(2026, 10, 4, 12))
    assert record.behaviour == behaviour
    assert record.cost == Decimal(amount)


def test_overpayment_reclaim_receipt_is_a_funds_movement():
    record = parse_debit_message(
        '溢缴款领回入账通知，您账户6061于05月08日10:21入账金额人民币1.28，余额847.56',
        datetime(2025, 5, 8, 10, 21, 8),
    )
    assert record.behaviour == '溢缴款领回'
    assert record.cost == Decimal('1.28')
    assert record.business == '入账金额'  # Preserve the external ID of existing imports.


def test_merchant_refund_word_does_not_reverse_payment_direction():
    record = parse_debit_message(
        '您账户1234于10月03日12:35在退款服务商店支付人民币2.99元，余额1000.88元',
        datetime(2026, 10, 3, 12, 35),
    )
    assert record.behaviour == '支付'
    assert record.cost == Decimal('-2.99')

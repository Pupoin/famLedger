from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from backend.ingest.famledger_sync import FamLedgerClient, external_id, sync_emails_and_parse_to_famledger
from backend.ingest.models import TransactionRecord


def record(**changes):
    values = dict(cost_time=datetime(2026, 10, 3, 12), cost=Decimal("-10.00"), account="1234",
                  business="AMAZON", behaviour="消费", original_currency="USD", account_type="credit_card")
    return TransactionRecord(**{**values, **changes})


def client(status="created", http_status=201):
    obj = FamLedgerClient("http://ledger:8000", "test-user-key")
    response = Mock(status_code=http_status)
    response.json.return_value = {"status": status}
    obj.session.post = Mock(return_value=response)
    return obj


def test_post_uses_personal_key_original_money_type_and_stable_external_id():
    obj = client()
    obj.push_transaction(record())
    call = obj.session.post.call_args
    payload = call.kwargs["json"]
    assert call.args[0] == "http://ledger:8000/api/v1/transactions"
    assert obj.session.headers["X-Api-Key"] == "test-user-key"
    assert payload["amount"] == "10.00"
    assert payload["currency"] == "USD"
    assert payload["transaction_type"] == "expense"
    assert payload["account"] == "招商银行信用卡:1234"
    assert payload["occurred_at"] == "2026-10-03T12:00:00+08:00"
    assert payload["external_id"] == external_id(record())
    assert external_id(record(cost=Decimal("-10"))) == payload["external_id"]
    assert call.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("behaviour,business,amount,kind,direction", [
    ("转入", "收到他行转入", "30", "transfer", "inflow"),
    ("转至", "自动转账", "-30", "transfer", "outflow"),
    ("还款", "信用卡还款", "-30", "transfer", "outflow"),
    ("退货", "退款", "30", "refund", None),
    ("入账", "工资", "30", "income", None),
    ("消费", "溢缴款领回", "-30", "transfer", "outflow"),
    ("溢缴款领回", "入账金额", "30", "transfer", "inflow"),
    ("取现", "掌上预借现金（转账）", "-30", "transfer", "outflow"),
    ("消费", "溢缴款领回手续费", "-1", "expense", None),
    ("消费", "信用卡还款手续费", "-1", "expense", None),
    ("消费", "信用卡利息", "-1", "expense", None),
    ("支付", "财付通-微信转账快捷", "-30", "transfer", "outflow"),
    ("消费", "转账用品商店", "-30", "expense", None),
])
def test_financial_direction(behaviour, business, amount, kind, direction):
    obj = client()
    obj.push_transaction(record(behaviour=behaviour, business=business, cost=Decimal(amount)))
    payload = obj.session.post.call_args.kwargs["json"]
    assert payload["transaction_type"] == kind
    assert payload["extra"].get("direction") == direction


def test_overpayment_reclassification_preserves_external_id_and_amount():
    before = record(behaviour='入账', business='入账金额', cost=Decimal('1.28'), account_type='checking')
    after = record(behaviour='溢缴款领回', business='入账金额', cost=Decimal('1.28'), account_type='checking')
    assert external_id(before) == external_id(after)
    obj = client()
    obj.push_transaction(after)
    payload = obj.session.post.call_args.kwargs['json']
    assert payload['transaction_type'] == 'transfer'
    assert payload['tags'] == ['溢缴款领回']
    assert payload['amount'] == '1.28'


@pytest.mark.parametrize("status", ["duplicate", "pending_fx", "canceled"])
def test_acknowledged_duplicate_or_pending_is_not_a_retry_failure(status):
    assert client(status).push_transaction(record())["status"] == status


@pytest.mark.parametrize("status", [401, 429, 500, 302])
def test_http_errors_and_redirects_fail_the_batch(status):
    with pytest.raises(RuntimeError):
        client(http_status=status).push_transaction(record())


def test_error_response_does_not_disclose_response_body_or_api_key():
    obj = client(http_status=401)
    obj.session.post.return_value.text = "secret-response-body"
    with pytest.raises(RuntimeError) as error:
        obj.push_transaction(record())
    assert "test-user-key" not in str(error.value)
    assert "secret-response-body" not in str(error.value)


def test_graph_utc_timestamp_is_converted_without_relabeling_the_time():
    msg = {"receivedDateTime": "2026-10-02T23:30:00Z", "body": {"content":
           "您账户1234于10月03日07:30银联扣款人民币2.99元，余额100.00元"}}
    obj = client()
    sync_emails_and_parse_to_famledger(obj, {"debit": [msg]})
    payload = obj.session.post.call_args.kwargs["json"]
    assert payload["occurred_at"] == "2026-10-03T07:30:00+08:00"
    assert datetime.fromisoformat(payload["occurred_at"]).astimezone(timezone.utc).hour == 23


def test_failed_post_is_not_swallowed():
    obj = client(http_status=500)
    msg = {"body": {"content": "2026/10/03 您的消费明细如下：12:00:00 CNY 10.00 尾号1234 消费 测试商户"}}
    with pytest.raises(RuntimeError):
        sync_emails_and_parse_to_famledger(obj, {"credit_daily": [msg]})


def test_missing_token_is_rejected_before_any_request():
    with pytest.raises(ValueError):
        FamLedgerClient("http://ledger:8000", "")


@pytest.mark.parametrize('error,reason', [(__import__('requests').ConnectionError('offline'), 'unreachable'),
                                        (__import__('requests').Timeout('slow'), 'timed out')])
def test_connection_failures_block_target_without_disclosing_secrets(error, reason):
    from backend.ingest.famledger_sync import DeliveryBlocked
    obj = client()
    obj.session.post.side_effect = error
    with pytest.raises(DeliveryBlocked, match=reason):
        obj.push_transaction(record())


@pytest.mark.parametrize('status,reason', [(401, 'API Key'), (403, '写入权限不足'),
                                         (409, 'external_identifier'), (422, '字段校验失败'),
                                         (429, '频率受限'), (500, '后端异常'), (302, '重定向')])
def test_http_failure_gives_status_and_actionable_reason_without_sensitive_body(status, reason):
    obj = client(http_status=status)
    obj.session.post.return_value.text = 'private mail body test-user-key'
    with pytest.raises(RuntimeError) as error:
        obj.push_transaction(record())
    assert f'HTTP {status}' in str(error.value)
    assert reason in str(error.value)
    assert 'private mail body' not in str(error.value)
    assert 'test-user-key' not in str(error.value)

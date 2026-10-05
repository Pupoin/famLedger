from decimal import Decimal

import pytest

from backend.ingest.famledger_sync import external_id, sync_emails_and_parse_to_famledger
from backend.ingest.parser import parse_credit_daily_message
from test_famledger_sync import client


def test_old_daily_statement_with_chinese_currency_and_adjacent_rows():
    body = ('2021/02/25 消费人民币￥21.86\t\n明细如下：'
            '17:20:24人民币 0.88尾号9085 消费 测试商户'
            '17:21:17人民币 20.98尾号9085 消费 测试商户\n人民币消费：')
    rows = parse_credit_daily_message(body)
    assert len(rows) == 2
    assert [row.cost for row in rows] == [Decimal('-0.88'), Decimal('-20.98')]
    assert [row.business for row in rows] == ['测试商户', '测试商户']
    assert all(row.original_currency == 'CNY' for row in rows)


def test_credit_cash_advance_is_parsed_alongside_consumption():
    msg = {'body': {'content': '2022/12/27 您的消费明细如下： '
                   '10:40:45 CNY 10000 尾号9085 取现 掌上预借现金（转账） '
                   '22:35:53 CNY 19.90 尾号9085 消费 测试商户'}}
    obj = client()
    assert sync_emails_and_parse_to_famledger(obj, {'credit_daily': [msg]}) == (1, 2)
    payloads = [call.kwargs['json'] for call in obj.session.post.call_args_list]
    assert [p['transaction_type'] for p in payloads] == ['transfer', 'expense']
    assert [p['amount'] for p in payloads] == ['10000', '19.90']


def test_recent_html_cells_preserve_rows_fields_and_refunds():
    msg = {'body': {'content': '<table>'
                   '<tr><td>9085</td><td>2023/08/24</td><td>12:32:38</td><td>CNY</td>'
                   '<td>测试商户</td><td>退货</td><td>-13.06</td></tr>'
                   '<tr><td>9085</td><td>2023/08/24</td><td>12:34:47</td><td>CNY</td>'
                   '<td>测试商户</td><td>消费</td><td>17.94</td></tr></table>'}}
    obj = client()
    assert sync_emails_and_parse_to_famledger(obj, {'credit_recent': [msg]}) == (1, 2)
    payloads = [call.kwargs['json'] for call in obj.session.post.call_args_list]
    assert [p['transaction_type'] for p in payloads] == ['refund', 'expense']
    assert [p['amount'] for p in payloads] == ['13.06', '17.94']
    assert all(p['account'] == '招商银行信用卡:9085' for p in payloads)
    assert payloads[0]['occurred_at'] == '2023-08-24T12:32:38+08:00'


def test_daily_table_whitespace_does_not_change_existing_transaction_ids():
    plain = parse_credit_daily_message('2026/10/03 您的消费明细如下：12:00:00 CNY 10.00 尾号1234 消费 测试商户')[0]
    spaced = parse_credit_daily_message('2026/10/03 您的消费明细如下：\n12:00:00\tCNY\t10.00\t尾号1234\t消费\t测试商户\n')[0]
    assert external_id(plain) == external_id(spaced)


def test_unknown_daily_action_is_retained_as_failure_instead_of_silently_skipping_row():
    with pytest.raises(ValueError, match='unrecognized transaction rows'):
        parse_credit_daily_message('2026/10/03 您的消费明细如下：'
                                   '12:00:00 CNY 10.00 尾号1234 未知交易 测试商户 '
                                   '13:00:00 CNY 20.00 尾号1234 消费 测试商户')


def test_unrecognized_recent_statement_is_not_acknowledged_as_sent():
    obj = client()
    with pytest.raises(ValueError, match='could not be parsed'):
        sync_emails_and_parse_to_famledger(obj, {'credit_recent': [{'body': {'content': '未知格式'}}]})
    obj.session.post.assert_not_called()

from datetime import datetime
from unittest.mock import Mock

import pytest

from backend.ingest.account_matching import matching_account, message_bank
from backend.ingest.famledger_sync import DeliveryBlocked, FamLedgerClient, external_id, sync_emails_and_parse_to_famledger
from backend.ingest.parser import parse_debit_message


BODY = '您账户7931于10月16日收到本行转入人民币500.00，余额566.03，付方测试用户（9459），备注：转账'


def accounts():
    return [
        {'id': 'destination', 'name': '收款账户别名', 'account_type': 'checking', 'currency': 'CNY',
         'external_identifier': '招商银行借记卡:7931', 'institution_name': '', 'can_edit': True, 'can_receive_transfer': True},
        {'id': 'source', 'name': '与付方姓名不同的账户名', 'account_type': 'savings', 'currency': 'CNY',
         'external_identifier': '招商银行借记卡:9459', 'institution_name': '', 'can_edit': True, 'can_receive_transfer': True},
    ]


def client(rows=None):
    obj = FamLedgerClient('http://ledger:8000', 'test-key')
    result = Mock(status_code=200)
    result.json.return_value = {'accounts': accounts() if rows is None else rows}
    obj.session.get = Mock(return_value=result)
    response = Mock(status_code=200)
    response.json.return_value = {'status': 'created', 'transfer_id': 'confirmed-pair', 'transfer_context_accepted': True}
    obj.session.post = Mock(return_value=response)
    return obj


def message(**changes):
    return {'subject': '账户变动通知', 'from': {'emailAddress': {'address': '95555@message.cmbchina.com'}},
            'body': {'content': BODY}, 'receivedDateTime': '2026-10-16T04:20:30Z', **changes}


@pytest.mark.parametrize('metadata', [
    {'from': {'emailAddress': {'address': '95555@message.cmbchina.com'}}},
    {'sender': {'emailAddress': {'address': '95555@message.cmbchina.com'}}},
    {'subject': '招商银行账户变动通知'}, {'title': '招商银行账户变动通知'},
])
def test_bank_is_inferred_from_sender_or_title(metadata):
    assert message_bank(metadata) == '招商银行'


def test_conflicting_or_unidentified_bank_does_not_guess_counterparty_bank():
    assert message_bank({}) is None
    assert message_bank(message(subject='中国工商银行账户变动通知')) is None
    assert message_bank({'from': {'emailAddress': {'address': '95555@message.cmbchina.com.attacker.invalid'}}}) is None
    record = parse_debit_message(BODY, datetime(2026, 10, 16, 12))
    assert record.counterparty_bank_name is None


def test_same_bank_payer_uses_bank_and_tail_not_person_name():
    obj = client()
    assert sync_emails_and_parse_to_famledger(obj, {'debit': [message()]}) == (1, 1)
    payload = obj.session.post.call_args.kwargs['json']
    assert payload['account'] == 'destination'
    assert payload['extra']['from_account_id'] == 'source'
    assert payload['extra']['direction'] == 'inflow'
    assert payload['extra']['bank_name'] == payload['extra']['counterparty_bank_name'] == '招商银行'
    assert payload['amount'] == '500.00' and payload['transaction_type'] == 'transfer'
    parsed = parse_debit_message(BODY, datetime(2026, 10, 16, 12, 20, 30), bank_name='招商银行')
    assert payload['external_id'] == external_id(parsed)
    assert obj.session.get.call_args.args[0] == 'http://ledger:8000/api/v1/accounts'
    assert obj.session.get.call_args.kwargs['allow_redirects'] is False


@pytest.mark.parametrize('changes', ['ambiguous', 'readonly_source', 'inactive', 'different_currency'])
def test_uncertain_or_unauthorized_counterpart_keeps_the_original_single_incoming_leg(changes):
    rows = accounts()
    if changes == 'ambiguous':
        rows.append({**rows[1], 'id': 'another-source'})
    elif changes == 'readonly_source':
        rows[1]['can_edit'] = False
    elif changes == 'inactive':
        rows[1]['is_active'] = False
    else:
        rows[1]['currency'] = 'USD'
    obj = client(rows)
    sync_emails_and_parse_to_famledger(obj, {'debit': [message()]})
    payload = obj.session.post.call_args.kwargs['json']
    assert payload['account'] == '招商银行借记卡:7931'
    assert 'from_account_id' not in payload['extra']
    assert 'from_account_identifier' not in payload['extra']
    assert payload['transaction_type'] == 'transfer' and payload['extra']['direction'] == 'inflow'


@pytest.mark.parametrize('available', ['primary_only', 'other_bank_peer', 'neither', 'peer_only'])
def test_absent_accounts_are_resolved_atomically_by_the_ledger_and_not_by_separate_account_posts(available):
    rows = accounts()
    if available == 'primary_only':
        rows = rows[:1]
    elif available == 'other_bank_peer':
        rows[1]['external_identifier'] = '中国工商银行借记卡:9459'
    elif available == 'neither':
        rows = []
    else:
        rows = rows[1:]
    obj = client(rows)
    sync_emails_and_parse_to_famledger(obj, {'debit': [message()]})
    payload = obj.session.post.call_args.kwargs['json']
    assert payload['account'] == ('招商银行借记卡:7931' if available in ('neither', 'peer_only') else 'destination')
    if available == 'peer_only':
        assert payload['extra']['from_account_id'] == 'source'
    else:
        assert payload['extra']['from_account_identifier'] == '招商银行:9459'
    assert obj.session.post.call_count == 1
    assert obj.session.post.call_args.args[0].endswith('/api/v1/transactions')
    assert obj._accounts is None


def test_unknown_outgoing_recipient_can_be_created_but_readonly_source_cannot_send():
    body = '您账户9459于10月16日本行转至人民币500.00，余额1500.00，收方测试用户（7931），备注：转账'
    rows = accounts()[1:]
    obj = client(rows)
    sync_emails_and_parse_to_famledger(obj, {'debit': [message(body={'content': body})]})
    assert obj.session.post.call_args.kwargs['json']['extra']['to_account_identifier'] == '招商银行:7931'
    rows[0]['can_edit'] = False
    obj = client(rows)
    sync_emails_and_parse_to_famledger(obj, {'debit': [message(body={'content': body})]})
    assert 'to_account_identifier' not in obj.session.post.call_args.kwargs['json']['extra']


def test_known_readonly_source_is_not_cloned_and_logs_why_pairing_was_skipped(caplog):
    rows = accounts()
    rows[1].update(name='招商银行 9459', external_identifier=None, institution_name='招商银行', account_type='cash', can_edit=False)
    obj = client(rows)
    sync_emails_and_parse_to_famledger(obj, {'debit': [message()]})
    payload = obj.session.post.call_args.kwargs['json']
    assert 'from_account_id' not in payload['extra'] and 'from_account_identifier' not in payload['extra']
    assert 'source is read-only' in caplog.text
    assert obj.session.post.call_count == 1


def test_readonly_destination_is_receivable_and_account_lookup_is_reused():
    rows = accounts(); rows[0]['can_edit'] = False
    obj = client(rows)
    sync_emails_and_parse_to_famledger(obj, {'debit': [message(), message()]})
    assert obj.session.get.call_count == 1
    assert obj.session.post.call_args.kwargs['json']['extra']['from_account_id'] == 'source'


@pytest.mark.parametrize('body', [BODY.replace('本行', '他行'), BODY.replace('本行', '') + '，备注：本行转账'])
def test_other_bank_or_remark_text_cannot_supply_same_bank_evidence(body):
    obj = client()
    sync_emails_and_parse_to_famledger(obj, {'debit': [message(body={'content': body})]})
    obj.session.get.assert_not_called()
    assert 'from_account_id' not in obj.session.post.call_args.kwargs['json']['extra']


def test_outgoing_notice_can_identify_the_payee_without_reversing_direction():
    body = '您账户9459于10月16日本行转至人民币500.00，余额1500.00，收方测试用户（7931），备注：转账'
    obj = client()
    sync_emails_and_parse_to_famledger(obj, {'debit': [message(body={'content': body})]})
    payload = obj.session.post.call_args.kwargs['json']
    assert payload['account'] == 'source'
    assert payload['extra']['to_account_id'] == 'destination'
    assert payload['extra']['direction'] == 'outflow'


def test_explicit_identifier_is_authoritative_and_full_card_numbers_keep_leading_zero_tails():
    rows = accounts()
    rows[1]['external_identifier'] = '招商银行借记卡:6225880000000362'
    assert matching_account(rows, '招商银行', '0362')['id'] == 'source'
    rows[1]['external_identifier'] = '0362'; rows[1]['institution_name'] = '招商银行'
    assert matching_account(rows, '招商银行', '0362')['id'] == 'source'
    rows[1]['external_identifier'] = '中国工商银行:0362'
    assert matching_account(rows, '招商银行', '0362') is None


def test_configured_identifier_precedes_suffix_only_identifiers_and_unconfigured_names():
    rows = accounts()
    rows += [{**rows[1], 'id': 'bare', 'external_identifier': '9459', 'institution_name': '招商银行'},
             {**rows[1], 'id': 'alias', 'external_identifier': '', 'name': '招商银行 9459'}]
    assert matching_account(rows, '招商银行', '9459')['id'] == 'source'
    rows.append({**rows[1], 'id': 'duplicate-identifier'})
    assert matching_account(rows, '招商银行', '9459') is None


@pytest.mark.parametrize('status', [401, 403, 429, 500])
def test_account_lookup_failure_stays_queued_without_logging_key_or_mail(status):
    obj = client()
    obj.session.get.return_value.status_code = status
    obj.session.get.return_value.text = 'test-key private-mail-body'
    with pytest.raises(DeliveryBlocked) as error:
        sync_emails_and_parse_to_famledger(obj, {'debit': [message()]})
    assert str(status) in str(error.value)
    assert 'test-key' not in str(error.value) and 'private-mail-body' not in str(error.value)
    obj.session.post.assert_not_called()


@pytest.mark.parametrize('status', ['created', 'duplicate', 'pending_fx'])
def test_older_server_cannot_acknowledge_an_ignored_transfer_counterpart(status):
    obj = client()
    obj.session.post.return_value.json.return_value = {'status': status}
    with pytest.raises(DeliveryBlocked, match='更新目标 famLedger'):
        sync_emails_and_parse_to_famledger(obj, {'debit': [message()]})

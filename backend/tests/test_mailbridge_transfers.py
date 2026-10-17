"""An incoming bank notice must complete one transfer, never duplicate money."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlmodel import select

from models import Account, AccountShare, Family, Transaction, Transfer, User
from test_transaction_edit_and_delete import accounts, balance, readonly_destination


def notice(accounts, *, incoming=True, linked=True, identifier=None, seconds=0):
    own, peer = (accounts[1], accounts[0]) if incoming else (accounts[0], accounts[1])
    extra = {'import_source': 'mailbridge', 'bank_action': '转入' if incoming else '转至',
             'direction': 'inflow' if incoming else 'outflow', 'bank_name': '招商银行',
             'account_last4': '7931' if incoming else '9459', 'counterparty_bank_name': '招商银行',
             'counterparty': {'payer_account_last4' if incoming else 'payee_account_last4': '9459' if incoming else '7931'}}
    if linked:
        extra['from_account_id' if incoming else 'to_account_id'] = str(peer.id)
    return {'account': str(own.id), 'narration': '收到本行转入' if incoming else '本行转至',
            'amount': '500', 'currency': 'CNY', 'transaction_type': 'transfer',
            'external_id': identifier or f'bank-notice:{uuid4()}',
            'occurred_at': (datetime(2026, 10, 16, 4, 20, 30, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat(),
            'extra': extra}


def push(client, payload):
    return client.post('/api/v1/transactions', json=payload)


def assert_balances(db, accounts, *, count=2, debit=-500, credit=500):
    db.expire_all()
    assert balance(db, accounts[0]) == debit
    assert balance(db, accounts[1]) == credit
    assert len(db.exec(select(Transaction)).all()) == count


def test_incoming_notice_atomically_creates_correct_outgoing_and_incoming_legs(auth_client_a, db, accounts):
    payload = notice(accounts)
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert response.json()['transfer_context_accepted'] is True
    pair = db.exec(select(Transfer)).one()
    out, incoming = db.get(Transaction, pair.outflow_transaction_id), db.get(Transaction, pair.inflow_transaction_id)
    assert out.account_id == accounts[0].id and incoming.account_id == accounts[1].id
    assert str(incoming.id) == response.json()['id'] and incoming.external_id == payload['external_id']
    assert out.extra['direction'] == 'outflow' and out.extra['mailbridge_generated_peer'] is True
    assert incoming.extra['direction'] == 'inflow'
    assert out.original_amount == incoming.original_amount == 500
    assert out.original_currency == incoming.original_currency == 'CNY'
    assert_balances(db, accounts)
    retry = push(auth_client_a, payload)
    assert retry.status_code == 200 and retry.json()['status'] == 'duplicate'
    assert_balances(db, accounts)


@pytest.mark.parametrize('incoming_first', [True, False])
def test_opposite_bank_notice_claims_generated_leg_in_either_arrival_order(auth_client_a, db, accounts, incoming_first):
    first = notice(accounts, incoming=incoming_first)
    assert push(auth_client_a, first).status_code == 200
    ids = {row.id for row in db.exec(select(Transaction)).all()}
    second = notice(accounts, incoming=not incoming_first, seconds=30)
    response = push(auth_client_a, second)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'duplicate'
    assert_balances(db, accounts)
    assert {row.id for row in db.exec(select(Transaction)).all()} == ids
    assert len(db.exec(select(Transfer)).all()) == 1
    assert {row.external_id for row in db.exec(select(Transaction)).all()} == {first['external_id'], second['external_id']}
    assert push(auth_client_a, second).json()['status'] == 'duplicate'
    assert_balances(db, accounts)


@pytest.mark.parametrize('existing_incoming', [False, True])
def test_existing_single_bank_leg_is_reused_instead_of_debited_twice(auth_client_a, db, accounts, existing_incoming):
    first = notice(accounts, incoming=existing_incoming, linked=False)
    response = push(auth_client_a, first)
    assert response.status_code == 200
    first_id = UUID(response.json()['id'])
    response = push(auth_client_a, notice(accounts, incoming=not existing_incoming, seconds=30))
    assert response.status_code == 200, response.text
    assert_balances(db, accounts)
    assert db.get(Transaction, first_id).transfer_id is not None
    assert len(db.exec(select(Transfer)).all()) == 1


def test_replay_can_complete_an_old_incoming_leg_without_overwriting_its_labels(auth_client_a, db, accounts):
    payload = notice(accounts, linked=False)
    row_id = push(auth_client_a, payload).json()['id']
    assert auth_client_a.patch(f'/api/v1/transactions/{row_id}', json={'narration': 'User label'}).status_code == 200
    payload['extra']['from_account_id'] = str(accounts[0].id)
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'duplicate'
    assert_balances(db, accounts)
    assert db.get(Transaction, UUID(row_id)).narration == 'User label'
    assert push(auth_client_a, payload).json()['status'] == 'duplicate'
    assert_balances(db, accounts)


@pytest.mark.parametrize('change', [{'amount': '750'}, {'transaction_type': 'income'}])
def test_replay_does_not_complete_or_overwrite_a_financially_edited_old_notice(auth_client_a, db, accounts, change):
    payload = notice(accounts, linked=False)
    row_id = push(auth_client_a, payload).json()['id']
    assert auth_client_a.patch(f'/api/v1/transactions/{row_id}', json=change).status_code == 200
    payload['extra']['from_account_id'] = str(accounts[0].id)
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'duplicate'
    db.expire_all()
    assert db.get(Transaction, UUID(row_id)).transfer_id is None
    assert_balances(db, accounts, count=1, debit=0, credit=750 if 'amount' in change else 500)


def test_readonly_shared_destination_can_receive_a_complete_incoming_transfer(auth_client_a, db, accounts):
    readonly_destination(db, accounts[1])
    response = push(auth_client_a, notice(accounts))
    assert response.status_code == 200, response.text
    assert_balances(db, accounts)


@pytest.mark.parametrize('failure', ['readonly_source', 'private_source', 'cross_family', 'inactive', 'same_account', 'invalid_id', 'wrong_direction', 'non_transfer'])
def test_incoming_transfer_cannot_debit_an_unauthorized_or_invalid_source(auth_client_a, db, accounts, failure):
    payload = notice(accounts)
    if failure in {'readonly_source', 'private_source'}:
        bob = db.exec(select(User).where(User.username == 'bob')).one()
        alice = db.exec(select(User).where(User.username == 'alice')).one()
        accounts[0].owner_id = bob.id
        if failure == 'readonly_source':
            db.add(AccountShare(account_id=accounts[0].id, user_id=alice.id, permission='read_only'))
    elif failure == 'cross_family':
        family = Family(name='Another tenant'); db.add(family); db.flush(); accounts[0].family_id = family.id
    elif failure == 'inactive':
        accounts[0].is_active = False
    elif failure == 'same_account':
        payload['extra']['from_account_id'] = str(accounts[1].id)
    elif failure == 'invalid_id':
        payload['extra']['from_account_id'] = 'invalid'
    elif failure == 'wrong_direction':
        payload['extra']['direction'] = 'outflow'
    else:
        payload['transaction_type'] = 'income'
    db.add(accounts[0]); db.commit()
    response = push(auth_client_a, payload)
    assert response.status_code in {400, 403, 422}, response.text
    assert db.exec(select(Transaction)).all() == []
    assert db.exec(select(Transfer)).all() == []


def test_two_unpaired_opposite_candidates_remain_unmodified_for_manual_review(auth_client_a, db, accounts):
    for seconds in (0, 30):
        assert push(auth_client_a, notice(accounts, incoming=False, linked=False, seconds=seconds)).status_code == 200
    response = push(auth_client_a, notice(accounts, seconds=15))
    assert response.status_code == 409, response.text
    assert_balances(db, accounts, count=2, debit=-1000, credit=0)
    assert db.exec(select(Transfer)).all() == []


def test_two_generated_candidates_are_not_arbitrarily_claimed(auth_client_a, db, accounts):
    for seconds in (0, 30):
        assert push(auth_client_a, notice(accounts, seconds=seconds)).status_code == 200
    response = push(auth_client_a, notice(accounts, incoming=False, seconds=15))
    assert response.status_code == 409, response.text
    assert_balances(db, accounts, count=4, debit=-1000, credit=1000)
    assert len(db.exec(select(Transfer)).all()) == 2


def test_delayed_opposite_notice_does_not_create_a_second_transfer(auth_client_a, db, accounts):
    assert push(auth_client_a, notice(accounts)).status_code == 200
    response = push(auth_client_a, notice(accounts, incoming=False, seconds=900))
    assert response.status_code == 409, response.text
    assert_balances(db, accounts)
    assert len(db.exec(select(Transfer)).all()) == 1


def test_rule_cannot_turn_a_readonly_incoming_transfer_into_an_expense(auth_client_a, db, accounts, monkeypatch):
    from routes.v1_transactions import RulePipeline
    readonly_destination(db, accounts[1])
    monkeypatch.setattr(RulePipeline, 'process_transaction', lambda self, row, **kwargs: setattr(row, 'transaction_type', 'expense'))
    response = push(auth_client_a, notice(accounts))
    assert response.status_code == 400, response.text
    assert_balances(db, accounts, count=0, debit=0, credit=0)


@pytest.mark.parametrize('replay', [False, True])
def test_missing_peer_exchange_rate_never_leaves_a_partial_pair(auth_client_a, db, accounts, monkeypatch, replay):
    from services import transfer_ingest
    from services.booking_money import PendingExchangeRate
    payload = notice(accounts, linked=not replay)
    if replay:
        assert push(auth_client_a, payload).status_code == 200
        payload['extra']['from_account_id'] = str(accounts[0].id)
    def unavailable(*args, **kwargs):
        raise PendingExchangeRate('rate unavailable')
    monkeypatch.setattr(transfer_ingest, 'prepare_booking', unavailable)
    response = push(auth_client_a, payload)
    if replay:
        assert response.status_code == 503, response.text
        assert_balances(db, accounts, count=1, debit=0, credit=500)
    else:
        assert response.status_code == 200 and response.json()['status'] == 'pending_fx', response.text
        assert_balances(db, accounts, count=0, debit=0, credit=0)
    assert db.exec(select(Transfer)).all() == []


def test_real_mailbridge_payload_completes_the_bank_transfer(auth_client_a, db, accounts):
    import json
    from pathlib import Path
    import subprocess
    import sys
    for row, tail in zip(accounts[:2], ['9459', '7931']):
        row.external_identifier = f'招商银行借记卡:{tail}'
        db.add(row)
    db.commit()
    available = auth_client_a.get('/api/v1/accounts').json()
    message = {'subject': '账户变动通知', 'from': {'emailAddress': {'address': '95555@message.cmbchina.com'}},
               'receivedDateTime': '2026-10-16T04:20:30Z', 'body': {'content':
                   '您账户7931于10月16日收到本行转入人民币500.00，余额566.03，付方测试用户（9459），备注：转账'}}
    # Mailbridge intentionally has its own `backend` package and runs separately.
    script = """
import json, sys
from types import SimpleNamespace
sys.path.insert(0, 'services/mailbridge')
from backend.ingest.famledger_sync import FamLedgerClient, sync_emails_and_parse_to_famledger
data = json.load(sys.stdin)
client = FamLedgerClient('http://ledger:8000', 'test-integration-key')
client.session.get = lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: data['accounts'])
def post(*args, **kwargs):
    print(json.dumps(kwargs['json']))
    return SimpleNamespace(status_code=200, json=lambda: {'status': 'created', 'transfer_id': 'test-pair', 'transfer_context_accepted': True})
client.session.post = post
sync_emails_and_parse_to_famledger(client, {'debit': [data['message']]})
"""
    parsed = subprocess.run([sys.executable, '-c', script], input=json.dumps({'accounts': available, 'message': message}),
                            capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parents[2])
    payload = json.loads(parsed.stdout)
    assert payload['account'] == str(accounts[1].id)
    assert payload['extra']['from_account_id'] == str(accounts[0].id)
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert_balances(db, accounts)


def test_replay_does_not_confirm_or_replace_a_different_existing_counterpart(auth_client_a, db, accounts):
    payload = notice(accounts)
    assert push(auth_client_a, payload).status_code == 200
    payload['extra']['from_account_id'] = str(accounts[2].id)
    response = push(auth_client_a, payload)
    assert response.status_code == 200 and response.json()['status'] == 'duplicate'
    assert response.json()['transfer_context_accepted'] is False
    assert_balances(db, accounts)
    assert balance(db, accounts[2]) == 0


@pytest.mark.parametrize('incoming', [True, False])
@pytest.mark.parametrize('currency', ['CNY', 'USD'])
def test_missing_counterparty_account_and_both_legs_are_created_atomically(auth_client_a, db, accounts, incoming, currency):
    primary = accounts[1] if incoming else accounts[0]
    primary.currency = currency
    db.add(primary); db.commit()
    before = len(db.exec(select(Account)).all())
    payload = notice(accounts, incoming=incoming, linked=False)
    payload['currency'] = currency
    side = 'from' if incoming else 'to'
    payload['extra'][f'{side}_account_identifier'] = '招商银行:0362'
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert response.json()['transfer_context_accepted'] is True
    peer = db.exec(select(Account).where(Account.external_identifier == '招商银行:0362')).one()
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    assert peer.owner_id == alice.id and peer.family_id == primary.family_id
    assert peer.name == '招商银行 0362' and peer.institution_name == '招商银行'
    assert peer.currency == currency and peer.account_type == 'checking'
    assert len(db.exec(select(Account)).all()) == before + 1
    assert balance(db, primary) == (500 if incoming else -500)
    assert balance(db, peer) == (-500 if incoming else 500)
    assert len(db.exec(select(Transaction)).all()) == 2
    assert len(db.exec(select(Transfer)).all()) == 1
    # Once both accounts are known, repeated messages use UUIDs and stay idempotent.
    payload['extra'].pop(f'{side}_account_identifier')
    payload['extra'][f'{side}_account_id'] = str(peer.id)
    retry = push(auth_client_a, payload)
    assert retry.status_code == 200 and retry.json()['status'] == 'duplicate'
    assert len(db.exec(select(Transaction)).all()) == 2
    assert len(db.exec(select(Account)).all()) == before + 1


def test_both_missing_accounts_are_created_once_with_one_complete_transfer(auth_client_a, db, accounts):
    before = len(db.exec(select(Account)).all())
    payload = notice(accounts, linked=False)
    payload['account'] = '招商银行借记卡:7931'
    payload['extra']['from_account_identifier'] = '招商银行:9459'
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert response.json()['transfer_context_accepted'] is True
    assert len(db.exec(select(Account)).all()) == before + 2
    assert len(db.exec(select(Transaction)).all()) == 2
    assert len(db.exec(select(Transfer)).all()) == 1


@pytest.mark.parametrize('incoming', [True, False])
@pytest.mark.parametrize('identifier', [None, '招商银行借记卡:0362', '招商银行信用卡:6225888800000362'])
def test_identifier_can_resolve_existing_accounts_without_creating_duplicates(auth_client_a, db, accounts, incoming, identifier):
    peer = accounts[0] if incoming else accounts[1]
    peer.name = '招商银行 0362'; peer.institution_name = '招商银行'
    peer.account_type = 'cash'
    peer.external_identifier = identifier
    db.add(peer); db.commit()
    before = len(db.exec(select(Account)).all())
    payload = notice(accounts, incoming=incoming, linked=False)
    payload['extra']['from_account_identifier' if incoming else 'to_account_identifier'] = '招商银行:0362'
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert len(db.exec(select(Account)).all()) == before
    assert_balances(db, accounts)


@pytest.mark.parametrize('failure', ['readonly_source', 'readonly_qualified_source', 'private_source', 'inactive', 'ambiguous', 'invalid', 'both_selectors'])
def test_missing_account_resolution_does_not_bypass_existing_permissions_or_ambiguity(auth_client_a, db, accounts, failure):
    peer = accounts[0]
    peer.name = '招商银行 0362'; peer.institution_name = '招商银行'
    if failure in ('readonly_source', 'readonly_qualified_source', 'private_source'):
        bob = db.exec(select(User).where(User.username == 'bob')).one()
        alice = db.exec(select(User).where(User.username == 'alice')).one()
        peer.owner_id = bob.id
        if failure.startswith('readonly'):
            db.add(AccountShare(account_id=peer.id, user_id=alice.id, permission='read_only'))
            if failure == 'readonly_qualified_source':
                peer.external_identifier = '招商银行借记卡:0362'
    elif failure == 'inactive':
        peer.is_active = False
    elif failure == 'ambiguous':
        accounts[2].name = peer.name; accounts[2].institution_name = peer.institution_name
        db.add(accounts[2])
    db.add(peer); db.commit()
    before = len(db.exec(select(Account)).all())
    payload = notice(accounts, linked=False)
    payload['extra']['from_account_identifier'] = '招商银行:0362' if failure != 'invalid' else '../0362'
    if failure == 'both_selectors':
        payload['extra']['to_account_id'] = str(accounts[2].id)
    response = push(auth_client_a, payload)
    assert response.status_code in (400, 403, 409, 422), response.text
    assert len(db.exec(select(Account)).all()) == before
    assert db.exec(select(Transaction)).all() == []


def test_new_account_is_rolled_back_when_rule_rejects_complete_transfer(auth_client_a, db, accounts, monkeypatch):
    from routes import v1_transactions
    def change_type(self, txn, **kwargs):
        txn.transaction_type = 'expense'
    monkeypatch.setattr(v1_transactions.RulePipeline, 'process_transaction', change_type)
    before = len(db.exec(select(Account)).all())
    payload = notice(accounts, linked=False)
    payload['extra']['from_account_identifier'] = '招商银行:0362'
    response = push(auth_client_a, payload)
    assert response.status_code == 400, response.text
    assert len(db.exec(select(Account)).all()) == before
    assert db.exec(select(Transaction)).all() == []


def test_replay_can_create_missing_source_for_an_unchanged_single_incoming_leg(auth_client_a, db, accounts):
    payload = notice(accounts, linked=False)
    row_id = push(auth_client_a, payload).json()['id']
    payload['extra']['from_account_identifier'] = '招商银行:0362'
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'duplicate' and response.json()['id'] == row_id
    assert response.json()['transfer_context_accepted'] is True
    assert len(db.exec(select(Transaction)).all()) == 2


def test_edited_duplicate_does_not_create_an_unused_counterparty_account(auth_client_a, db, accounts):
    payload = notice(accounts, linked=False)
    row_id = push(auth_client_a, payload).json()['id']
    assert auth_client_a.patch(f'/api/v1/transactions/{row_id}', json={'amount': '750'}).status_code == 200
    before = len(db.exec(select(Account)).all())
    payload['extra']['from_account_identifier'] = '招商银行:0362'
    response = push(auth_client_a, payload)
    assert response.status_code == 409, response.text
    assert len(db.exec(select(Account)).all()) == before
    assert len(db.exec(select(Transaction)).all()) == 1


@pytest.mark.parametrize('incoming_first', [True, False])
def test_mail_replay_never_recreates_a_manually_deleted_transfer_leg(auth_client_a, db, accounts, incoming_first):
    payload = notice(accounts, incoming=incoming_first)
    assert push(auth_client_a, payload).status_code == 200
    pair = db.exec(select(Transfer)).one()
    outgoing_id, pair_id = pair.outflow_transaction_id, pair.id
    response = auth_client_a.delete(f'/api/v1/transactions/{outgoing_id}', params={
        'scope': 'single', 'expected_transfer_id': str(pair_id)})
    assert response.status_code == 200, response.text
    assert_balances(db, accounts, count=1, debit=0, credit=500)
    response = push(auth_client_a, payload if incoming_first else notice(accounts))
    if incoming_first:
        assert response.status_code == 200 and response.json()['transfer_context_accepted'] is False
    else:
        assert response.status_code == 409, response.text
    assert_balances(db, accounts, count=1, debit=0, credit=500)
    assert db.exec(select(Transfer)).all() == []


def test_a_deleted_peer_does_not_block_a_new_transfer_from_a_different_account(auth_client_a, db, accounts):
    assert push(auth_client_a, notice(accounts, incoming=False)).status_code == 200
    pair = db.exec(select(Transfer)).one()
    assert auth_client_a.delete(f'/api/v1/transactions/{pair.outflow_transaction_id}', params={
        'scope': 'single', 'expected_transfer_id': str(pair.id)}).status_code == 200
    payload = notice(accounts)
    payload['extra']['from_account_id'] = str(accounts[2].id)
    payload['extra']['counterparty']['payer_account_last4'] = '1122'
    response = push(auth_client_a, payload)
    assert response.status_code == 200, response.text
    assert_balances(db, accounts, count=3, debit=0, credit=1000)
    assert balance(db, accounts[2]) == -500

"""Unpaired bank notices may identify an account without changing its money."""
import pytest
from sqlmodel import select

from models import Account, AccountShare, Family, Transaction, Transfer, User
from test_transaction_edit_and_delete import accounts, activity, balance


def bank_notice(db, accounts, incoming=True):
    for account, tail in zip(accounts[:2], ['9459', '7931']):
        account.name = f'招商银行 {tail}'
        account.institution_name = '招商银行'
        account.external_identifier = f'招商银行借记卡:{tail}'
        db.add(account)
    primary, peer = (accounts[1], accounts[0]) if incoming else (accounts[0], accounts[1])
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    peer.owner_id = bob.id
    db.add(peer)
    share = AccountShare(account_id=peer.id, user_id=alice.id, permission='read_only')
    db.add(share); db.commit()
    row = activity(db, primary, 'transfer', 500, extra={
        'import_source': 'mailbridge', 'direction': 'inflow' if incoming else 'outflow',
        'bank_name': '招商银行', 'counterparty_bank_name': '招商银行',
        'counterparty': {'payer_account_last4' if incoming else 'payee_account_last4': '9459' if incoming else '7931'},
    })
    return row, primary, peer, share


def views(client, row):
    detail_response = client.get(f'/api/v1/transactions/{row.id}')
    listing_response = client.get('/api/v1/transactions', params={'account_id': str(row.account_id)})
    assert detail_response.status_code == 200, detail_response.text
    assert listing_response.status_code == 200, listing_response.text
    listing = next(item for item in listing_response.json()['items'] if item['id'] == str(row.id))
    return detail_response.json(), listing


@pytest.mark.parametrize('incoming', [True, False])
def test_readonly_counterpart_and_owner_are_visible_without_posting_its_leg(auth_client_a, db, accounts, incoming):
    row, primary, peer, _ = bank_notice(db, accounts, incoming)
    before = (balance(db, primary), balance(db, peer), primary.balance_version, peer.balance_version)
    detail, listing = views(auth_client_a, row)
    for result in (detail, listing):
        identity = result['transfer_counterparty']
        assert identity['account_id'] == str(peer.id)
        assert identity['account_name'] == peer.name
        assert identity['owner_name'] == 'Bob' and identity['is_owner'] is False
        assert identity['owner_id'] == str(peer.owner_id)
    assert detail['paired_transfer'] is None
    assert listing['transfer_id'] is None and listing['transfer_is_outflow'] is not incoming
    assert listing['transfer_peer_account'] == peer.name
    assert listing['transfer_peer_owner_name'] == 'Bob' and listing['transfer_peer_is_owner'] is False
    assert (balance(db, primary), balance(db, peer), primary.balance_version, peer.balance_version) == before
    assert len(db.exec(select(Transaction)).all()) == 1
    assert db.exec(select(Transfer)).all() == []


@pytest.mark.parametrize('failure', ['unshared', 'revoked', 'cross_family', 'different_bank', 'conflicting_identifier', 'ambiguous', 'missing', 'inactive', 'no_bank', 'only_person_name'])
def test_counterpart_lookup_does_not_guess_or_reveal_private_accounts(auth_client_a, db, accounts, failure):
    row, _, peer, share = bank_notice(db, accounts)
    if failure in ('unshared', 'revoked'):
        if failure == 'revoked':
            assert views(auth_client_a, row)[0]['transfer_counterparty'] is not None
        db.delete(share)
        # Explicit ownership/share bounds still apply to this new read model.
        alice = db.exec(select(User).where(User.username == 'alice')).one()
        alice.role = 'admin'; db.add(alice)
    elif failure == 'cross_family':
        family = Family(name='Foreign'); db.add(family); db.flush(); peer.family_id = family.id
    elif failure == 'different_bank':
        row.extra = {**row.extra, 'counterparty_bank_name': '中国工商银行'}
    elif failure == 'conflicting_identifier':
        peer.external_identifier = '中国工商银行:9459'
    elif failure == 'ambiguous':
        accounts[2].external_identifier = peer.external_identifier; db.add(accounts[2])
    elif failure == 'missing':
        row.extra = {**row.extra, 'counterparty': {'payer_account_last4': '0001'}}
    elif failure == 'inactive':
        peer.is_active = False
    elif failure == 'no_bank':
        row.extra = {**row.extra, 'counterparty_bank_name': None}
    elif failure == 'only_person_name':
        row.extra = {**row.extra, 'counterparty': {'payer_name': 'Bob'}}
    db.add_all([row, peer]); db.commit()
    count = len(db.exec(select(Account)).all())
    detail, listing = views(auth_client_a, row)
    assert detail['transfer_counterparty'] is None and listing['transfer_counterparty'] is None
    assert listing['transfer_peer_account'] is None and listing['transfer_peer_owner_name'] is None
    assert len(db.exec(select(Account)).all()) == count
    assert len(db.exec(select(Transaction)).all()) == 1
    assert db.exec(select(Transfer)).all() == []


@pytest.mark.parametrize('identifier', ['招商银行信用卡:6225888800000362', '0362'])
def test_identifier_precedes_display_name_and_preserves_leading_zeroes(auth_client_a, db, accounts, identifier):
    row, _, peer, _ = bank_notice(db, accounts)
    peer.external_identifier = identifier
    peer.name = 'Custom alias 9999'
    row.extra = {**row.extra, 'counterparty': {'payer_account_last4': '0362'}}
    db.add_all([row, peer]); db.commit()
    detail, _ = views(auth_client_a, row)
    assert detail['transfer_counterparty']['account_name'] == peer.name


def test_explicit_unpaired_account_pointer_still_honors_visibility(auth_client_a, db, accounts):
    row, _, peer, share = bank_notice(db, accounts)
    row.extra = {'direction': 'inflow', 'from_account_id': str(peer.id), 'transfer_peer_deleted': True}
    db.add(row); db.commit()
    detail, _ = views(auth_client_a, row)
    assert detail['transfer_counterparty']['account_id'] == str(peer.id)
    assert detail['paired_transfer'] is None and len(db.exec(select(Transaction)).all()) == 1
    db.delete(share); db.commit()
    assert views(auth_client_a, row)[0]['transfer_counterparty'] is None


def test_an_existing_pair_keeps_its_status_and_shared_owner_information(auth_client_a, db, accounts):
    incoming, primary, peer, _ = bank_notice(db, accounts)
    outgoing = activity(db, peer, 'transfer', 500, extra={'direction': 'outflow'})
    pair = Transfer(family_id=primary.family_id, outflow_transaction_id=outgoing.id,
                    inflow_transaction_id=incoming.id, amount=500, status='confirmed')
    db.add(pair); db.flush()
    incoming.transfer_id = outgoing.transfer_id = pair.id
    db.add_all([incoming, outgoing]); db.commit()
    detail, listing = views(auth_client_a, incoming)
    assert detail['transfer_counterparty'] is None and listing['transfer_counterparty'] is None
    assert detail['paired_transfer']['transfer_id'] == str(pair.id)
    counterpart = detail['paired_transfer']['counterpart']
    assert counterpart['account_name'] == peer.name
    assert counterpart['owner_name'] == 'Bob' and counterpart['is_owner'] is False
    assert listing['transfer_id'] == str(pair.id)
    assert listing['transfer_peer_owner_name'] == 'Bob' and listing['transfer_peer_is_owner'] is False
    assert len(db.exec(select(Transaction)).all()) == 2

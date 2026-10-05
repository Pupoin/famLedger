"""Bulk account settings are atomic and cannot bypass explicit sharing permissions."""
from decimal import Decimal
import uuid

import pytest
from sqlmodel import select

from models import Account, AccountShare, Family, Transaction, User, UserPreference


@pytest.fixture
def selection(db):
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    family = Family(name='Bulk test family')
    db.add(family); db.flush()
    alice.family_id = bob.family_id = family.id
    carol = User(username='bulk_carol', display_name='Carol', family_id=family.id)
    db.add_all([alice, bob, carol]); db.flush()
    cards = [Account(name=f'Account {i}', account_type='checking', family_id=family.id,
                     owner_id=alice.id, institution_name='Original bank') for i in range(2)]
    shared = Account(name='Shared account', account_type='checking', family_id=family.id, owner_id=bob.id)
    private = Account(name='Private account', account_type='checking', family_id=family.id, owner_id=bob.id)
    db.add_all([*cards, shared, private]); db.flush()
    share = AccountShare(account_id=shared.id, user_id=alice.id, permission='read_only')
    db.add(share); db.commit()
    return alice, bob, carol, cards, shared, private, share


def update(client, cards, **changes):
    return client.patch('/api/v1/accounts/bulk/settings', json={
        'account_ids': [str(card.id) for card in cards], **changes,
    })


def test_batch_information_and_sharing_preserve_identifiers_and_untouched_members(auth_client_a, db, selection):
    alice, bob, carol, cards, _, _, _ = selection
    cards[0].external_identifier = 'unique:1111'; cards[1].external_identifier = 'unique:2222'
    retained = AccountShare(account_id=cards[0].id, user_id=bob.id, permission='read_only', include_in_finances=False)
    db.add_all([*cards, retained]); db.commit()
    result = update(auth_client_a, cards, institution_name=' New bank ', account_type='loan', members=[
        {'user_id': str(bob.id), 'permission': 'full_control'},
        {'user_id': str(carol.id), 'permission': 'read_only'},
        {'user_id': str(alice.id), 'shared': False},
    ])
    assert result.status_code == 200, result.text
    assert result.json()['updated_count'] == 2
    db.expire_all()
    for card in cards:
        current = db.get(Account, card.id)
        assert current.institution_name == 'New bank' and current.account_type == 'loan'
        assert current.classification == 'liability' and current.owner_id == alice.id
        assert current.external_identifier == card.external_identifier
        shares = db.exec(select(AccountShare).where(AccountShare.account_id == card.id)).all()
        assert {share.user_id: share.permission for share in shares} == {bob.id: 'full_control', carol.id: 'read_only'}
    db.refresh(retained)
    assert retained.include_in_finances is False
    assert db.exec(select(Transaction)).all() == []


def test_clear_institution_and_duplicate_selection_are_supported(auth_client_a, db, selection):
    cards = selection[3]
    result = update(auth_client_a, [cards[0], cards[0]], institution_name='')
    assert result.status_code == 200 and result.json()['updated_count'] == 1
    db.expire_all()
    assert db.get(Account, cards[0].id).institution_name is None
    assert db.get(Account, cards[1].id).institution_name == 'Original bank'


@pytest.mark.parametrize('permission', ['read_only', 'read_write', 'full_control'])
def test_account_owners_cannot_downgrade_their_own_permissions(auth_client_a, db, selection, permission):
    alice, _, _, cards, _, _, _ = selection
    result = update(auth_client_a, cards, members=[{'user_id': str(alice.id), 'permission': permission}])
    assert result.status_code == 200, result.text
    assert db.exec(select(AccountShare).where(AccountShare.user_id == alice.id,
                                             AccountShare.account_id.in_([card.id for card in cards]))).all() == []
    rows = auth_client_a.get('/api/v1/accounts/shares/matrix').json()['accounts']
    for row in rows:
        if row['account_id'] in {str(card.id) for card in cards}:
            assert row['owner_id'] == str(alice.id) and row['can_manage'] and row['can_manage_shares']


@pytest.mark.parametrize('role', ['member', 'admin'])
@pytest.mark.parametrize('changes', [{'institution_name': 'Forbidden'}, {'account_type': 'cash'}, {'members': []}])
def test_mixed_read_only_selection_is_rejected_atomically(auth_client_a, db, selection, role, changes):
    alice, bob, carol, cards, shared, _, _ = selection
    alice.role = role; db.add(alice); db.commit()
    if 'members' in changes: changes = {'members': [{'user_id': str(carol.id), 'permission': 'full_control'}]}
    result = update(auth_client_a, [cards[0], shared], hidden=True, **changes)
    assert result.status_code == 403
    db.expire_all()
    assert db.get(Account, cards[0].id).institution_name == 'Original bank'
    assert db.get(Account, cards[0].id).account_type == 'checking'
    assert db.exec(select(AccountShare).where(AccountShare.user_id == carol.id)).all() == []
    pref = db.exec(select(UserPreference).where(UserPreference.username == 'alice')).first()
    assert not pref or not pref.hidden_sidebar_accounts


def test_read_only_recipient_can_hide_and_restore_accounts_without_financial_changes(auth_client_a, db, selection):
    alice, _, _, cards, shared, _, _ = selection
    before = {card.id: card.model_dump() for card in [*cards, shared]}
    for hidden in [True, False]:
        result = update(auth_client_a, [*cards, shared], hidden=hidden)
        assert result.status_code == 200, result.text
        pref = db.exec(select(UserPreference).where(UserPreference.username == alice.username)).one()
        db.refresh(pref)
        assert set(pref.hidden_sidebar_accounts) == ({str(card.id) for card in [*cards, shared]} if hidden else set())
    db.expire_all()
    assert {card.id: db.get(Account, card.id).model_dump() for card in [*cards, shared]} == before


def test_nonzero_confirmation_precedes_all_changes(auth_client_a, db, selection):
    cards = selection[3]
    cards[1].balance = Decimal('42.50'); db.add(cards[1]); db.commit()
    result = update(auth_client_a, cards, hidden=True, institution_name='Changed')
    assert result.status_code == 409
    assert result.json()['detail']['accounts'][0]['balance'] == '42.5000'
    db.expire_all()
    assert all(db.get(Account, card.id).institution_name == 'Original bank' for card in cards)
    result = update(auth_client_a, cards, hidden=True, institution_name='Changed', confirm_nonzero_balance=True)
    assert result.status_code == 200
    db.expire_all()
    assert all(db.get(Account, card.id).institution_name == 'Changed' for card in cards)


@pytest.mark.parametrize('kind', ['private', 'missing', 'foreign'])
def test_inaccessible_id_rejects_whole_batch(auth_client_a, db, selection, kind):
    _, bob, _, cards, _, private, _ = selection
    target = private.id
    if kind == 'missing': target = uuid.uuid4()
    if kind == 'foreign':
        family = Family(name='Foreign family'); db.add(family); db.flush()
        foreign = Account(name='Foreign', owner_id=bob.id, family_id=family.id, account_type='checking')
        db.add(foreign); db.commit(); target = foreign.id
    result = auth_client_a.patch('/api/v1/accounts/bulk/settings', json={
        'account_ids': [str(cards[0].id), str(target)], 'institution_name': 'Forbidden', 'hidden': True,
    })
    assert result.status_code == 404
    db.expire_all()
    assert db.get(Account, cards[0].id).institution_name == 'Original bank'


def test_full_control_batch_revocation_unlinks_supplementary_card(auth_client_a, db, selection):
    alice, bob, _, cards, shared, _, share = selection
    parent, other = cards
    parent.account_type = shared.account_type = 'credit_card'
    parent.classification = shared.classification = 'liability'
    shared.parent_account_id = parent.id
    share.permission = 'full_control'
    db.add_all([parent, shared, share]); db.commit()
    response = update(auth_client_a, [other, shared], members=[{'user_id': str(alice.id), 'shared': False}])
    assert response.status_code == 200, response.text
    assert response.json()['unlinked_account_ids'] == [str(shared.id)]
    db.expire_all()
    assert db.get(Account, shared.id).parent_account_id is None
    assert db.exec(select(AccountShare).where(AccountShare.account_id == shared.id, AccountShare.user_id == alice.id)).first() is None


def test_primary_card_type_failure_leaves_other_cards_unchanged(auth_client_a, db, selection):
    _, _, _, cards, _, _, _ = selection
    parent, child = cards
    parent.account_type = child.account_type = 'credit_card'
    parent.classification = child.classification = 'liability'
    child.parent_account_id = parent.id
    db.add_all(cards); db.commit()
    result = update(auth_client_a, cards, institution_name='Forbidden', account_type='cash')
    assert result.status_code == 400
    db.expire_all()
    assert all(db.get(Account, card.id).institution_name == 'Original bank' for card in cards)
    assert db.get(Account, child.id).parent_account_id == parent.id


@pytest.mark.parametrize('kind', ['foreign_member', 'duplicate_member'])
def test_invalid_sharing_targets_reject_all_other_changes(auth_client_a, db, selection, kind):
    _, bob, _, cards, _, _, _ = selection
    members = [{'user_id': str(bob.id), 'permission': 'read_only'}] * 2
    if kind == 'foreign_member':
        family = Family(name='Other members'); db.add(family); db.flush()
        user = User(username='outsider', display_name='Outsider', family_id=family.id)
        db.add(user); db.commit()
        members = [{'user_id': str(user.id), 'permission': 'read_only'}]
    assert update(auth_client_a, cards, institution_name='Forbidden', hidden=True, members=members).status_code == 400
    db.expire_all()
    assert all(db.get(Account, card.id).institution_name == 'Original bank' for card in cards)
    assert db.exec(select(AccountShare).where(AccountShare.account_id.in_([card.id for card in cards]))).all() == []


def test_unexpected_failure_rolls_back_prior_account_and_share_changes(auth_client_a, db, selection, monkeypatch):
    from routes import v1_accounts
    _, bob, _, cards, _, _, _ = selection
    original = v1_accounts._apply_account_share_updates
    calls = []
    def fail_second(session, account, members):
        calls.append(account.id)
        if len(calls) == 2:
            raise RuntimeError('Synthetic database failure')
        original(session, account, members)
    monkeypatch.setattr(v1_accounts, '_apply_account_share_updates', fail_second)
    with pytest.raises(RuntimeError, match='Synthetic database failure'):
        update(auth_client_a, cards, institution_name='Forbidden', members=[{'user_id': str(bob.id)}])
    db.expire_all()
    assert all(db.get(Account, card.id).institution_name == 'Original bank' for card in cards)
    assert db.exec(select(AccountShare).where(AccountShare.account_id.in_([card.id for card in cards]))).all() == []


@pytest.mark.parametrize('changes,code', [
    ({}, 400), ({'account_type': 'unsupported'}, 422),
    ({'members': [{'user_id': str(uuid.uuid4()), 'permission': 'admin'}]}, 422),
    ({'institution_name': 'x' * 101}, 422), ({'balance': 100}, 422),
])
def test_invalid_settings_do_not_modify_accounts(auth_client_a, db, selection, changes, code):
    cards = selection[3]
    result = update(auth_client_a, cards, **changes)
    assert result.status_code == code, result.text
    db.expire_all()
    assert all(db.get(Account, card.id).institution_name == 'Original bank' for card in cards)

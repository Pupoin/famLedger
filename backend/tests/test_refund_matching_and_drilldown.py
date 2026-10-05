"""Refund confidence, per-user controls and report/drilldown conservation."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine, select

from models import Account, AccountShare, Category, Family, RefundAllocation, Transaction, TransactionSplit
from services.refund_money import AUTO_REFUND_THRESHOLD, refund_match_score
from services.schema import sync_schema
from test_fix104_regressions import setup_accounts
from test_fixed_booking import create, quote, DAY


def post(client, account, **data):
    response = create(client, account, currency='CNY', **data)
    assert response.status_code == 200, response.text
    return response.json()


def test_refund_toggle_persists_and_is_per_user(auth_client_a, auth_client_b):
    assert auth_client_a.get('/api/user-preferences').json()['auto_refund_enabled'] is True
    response = auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': False})
    assert response.status_code == 200 and response.json()['auto_refund_enabled'] is False
    assert auth_client_a.get('/api/user-preferences').json()['auto_refund_enabled'] is False
    assert auth_client_b.get('/api/user-preferences').json()['auto_refund_enabled'] is True
    auth_client_a.put('/api/user-preferences', json={'language': 'zh'})
    assert auth_client_a.get('/api/user-preferences').json()['auto_refund_enabled'] is False


def test_disabled_automation_preserves_manual_offsets(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    category = Category(family_id=family.id, name='Refund category')
    db.add(category); db.commit()
    auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': False})
    expense = post(auth_client_a, accounts[0], category_id=str(category.id))
    refund = post(auth_client_a, accounts[0], transaction_type='refund', narration='Verified merchant refund')
    db.expire_all()
    assert db.get(Transaction, UUID(refund['id'])).refund_of_transaction_id is None
    assert auth_client_a.post('/api/v1/refunds/auto-match').json()['matched'] == 0
    assert auth_client_a.post(f"/api/v1/refunds/{refund['id']}/link/{expense['id']}").status_code == 200
    result = auth_client_a.get('/api/v1/transactions', params={'category_name': category.name, 'spending_net': True}).json()
    assert result['spending_summary']['net'] == 0
    assert result['total_count'] == 2


def test_high_confidence_matching_and_score_metadata(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = post(auth_client_a, accounts[0])
    refund = post(auth_client_a, accounts[0], transaction_type='refund', narration='Verified merchant refund',
                  transacted_at=(DAY + timedelta(days=1)).isoformat())
    saved = db.get(Transaction, UUID(refund['id']))
    assert str(saved.refund_of_transaction_id) == expense['id']
    match = saved.extra['refund_match']
    assert match['score'] > .9 and match['components']['opposite_directions']


@pytest.mark.parametrize('kind,direction', [('expense', 'out'), ('income', 'in'), ('refund', 'out')])
def test_direction_is_a_hard_gate(kind, direction):
    original = Transaction(account_id=UUID(int=1), transacted_at=DAY, amount=Decimal(100),
        original_amount=Decimal(100), original_currency='CNY', narration='Shop', transaction_type='expense')
    refund = original.model_copy(update={'transaction_type': kind, 'extra': {'direction': direction}})
    score, parts = refund_match_score(refund, original, Decimal(100))
    assert score == 0 and parts['opposite_directions'] is False


@pytest.mark.parametrize('change', [
    {'original_amount': Decimal(20)}, {'narration': 'Completely different merchant'},
    {'original_currency': 'USD'}, {'transacted_at': DAY - timedelta(days=1)},
    {'transacted_at': DAY + timedelta(days=91)}, {'extra': {'direction': 'out'}}])
def test_weak_or_ineligible_matches_stay_pending(auth_client_a, db, change):
    _, alice, _, accounts = setup_accounts(db)
    original = post(auth_client_a, accounts[0])
    refund = Transaction(account_id=accounts[0].id, transacted_at=DAY + timedelta(days=1),
        amount=Decimal(100), currency='CNY', original_amount=Decimal(100), original_currency='CNY',
        narration='Verified merchant refund', transaction_type='refund')
    for key, value in change.items():
        setattr(refund, key, value)
    db.add(refund); db.flush()
    from services.refund_money import auto_allocate
    assert auto_allocate(db, alice, refund) is None
    assert refund.refund_of_transaction_id is None
    assert not db.exec(select(RefundAllocation)).all()


def test_exact_threshold_is_not_an_auto_match():
    original = Transaction(account_id=UUID(int=1), transacted_at=DAY, amount=Decimal(100),
        original_amount=Decimal(100), original_currency='CNY', narration='Shop', transaction_type='expense')
    refund = original.model_copy(update={'transaction_type': 'refund', 'transacted_at': DAY + timedelta(days=90)})
    score, _ = refund_match_score(refund, original, Decimal(100))
    assert score == pytest.approx(AUTO_REFUND_THRESHOLD)
    assert score <= AUTO_REFUND_THRESHOLD


def test_similar_candidates_are_not_chosen_arbitrarily(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    for _ in range(2):
        post(auth_client_a, accounts[0])
    refund = post(auth_client_a, accounts[0], transaction_type='refund', narration='Verified merchant refund')
    saved = db.get(Transaction, UUID(refund['id']))
    assert saved.refund_of_transaction_id is None
    assert saved.extra['refund_match']['status'] == 'ambiguous'


def test_history_replay_is_idempotent_and_respects_manual_unlink(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': False})
    expense = post(auth_client_a, accounts[0])
    refund = post(auth_client_a, accounts[0], transaction_type='refund', narration='Verified merchant refund')
    auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': True})
    assert auth_client_a.post('/api/v1/refunds/auto-match').json() == {'examined': 1, 'matched': 1, 'pending': 0}
    assert auth_client_a.post('/api/v1/refunds/auto-match').json()['matched'] == 0
    assert auth_client_a.post(f"/api/v1/refunds/{refund['id']}/unlink").status_code == 200
    assert auth_client_a.post('/api/v1/refunds/auto-match').json()['matched'] == 0
    assert not db.exec(select(RefundAllocation)).all()
    assert auth_client_a.post(f"/api/v1/refunds/{refund['id']}/link/{expense['id']}").status_code == 200


def test_editing_type_to_refund_uses_automation(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = post(auth_client_a, accounts[0])
    income = post(auth_client_a, accounts[0], transaction_type='income', narration='Verified merchant refund')
    response = auth_client_a.patch(f"/api/v1/transactions/{income['id']}", json={'transaction_type': 'refund'})
    assert response.status_code == 200, response.text
    assert response.json()['refund_info']['original_transaction']['id'] == expense['id']


def test_cross_family_and_read_only_candidates_never_match(auth_client_a, db):
    family, alice, bob, accounts = setup_accounts(db)
    foreign_family = Family(name='Another family'); db.add(foreign_family); db.flush()
    foreign = Account(name='Foreign', family_id=foreign_family.id, owner_id=bob.id, currency='CNY', account_type='checking')
    private = Account(name='Read-only', family_id=family.id, owner_id=bob.id, currency='CNY', account_type='checking')
    db.add_all([foreign, private]); db.flush()
    db.add_all([AccountShare(account_id=a.id, user_id=alice.id, permission='read_only') for a in [foreign, private]])
    for a in [foreign, private]:
        db.add(Transaction(account_id=a.id, transacted_at=DAY, narration='Verified merchant',
            amount=Decimal(100), original_amount=Decimal(100), original_currency='CNY'))
    db.commit()
    refund = post(auth_client_a, accounts[0], transaction_type='refund', narration='Verified merchant refund')
    db.expire_all()
    assert db.get(Transaction, UUID(refund['id'])).refund_of_transaction_id is None
    assert auth_client_a.post('/api/v1/refunds/auto-match').json()['matched'] == 0


def test_split_refund_drilldowns_match_reports_budget_and_pagination(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    categories = [Category(family_id=family.id, name=name) for name in ['Category A', 'Category B', 'Other refund']]
    db.add_all(categories); db.commit()
    expense = post(auth_client_a, accounts[0], category_id=str(categories[0].id), transacted_at='2020-01-01')
    original = db.get(Transaction, UUID(expense['id'])); original.is_split = True; db.add(original)
    db.add_all([TransactionSplit(transaction_id=original.id, category_id=c.id, amount=Decimal(amount))
                for c, amount in zip(categories, ['60', '40'])]); db.commit()
    refund = post(auth_client_a, accounts[0], amount='50', transaction_type='refund', narration='Unrelated bank refund',
        category_id=str(categories[2].id), transacted_at='2020-02-01', refund_of_transaction_id=expense['id'])
    for category, expected in zip(categories[:2], [-30, -20]):
        params = {'category_name': category.name, 'spending_net': True,
                  'start_date': '2020-02-01', 'end_date': '2020-02-28', 'limit': 1}
        response = auth_client_a.get('/api/v1/transactions', params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['total_count'] == 1 and data['items'][0]['id'] == refund['id']
        assert data['spending_summary']['net'] == expected
        assert Decimal(data['items'][0]['amount']) == 50  # Keep actual cash unchanged.
    params = {'period': 'custom', 'start_date': '2020-02-01', 'end_date': '2020-02-28'}
    overview = auth_client_a.get('/api/v1/dashboard/summary', params=params).json()
    assert {c['name']: c['amount'] for c in overview['outflows']['categories']} == {'Category A': -30, 'Category B': -20}
    assert auth_client_a.get('/api/v1/analytics/report', params=params).json()['kpis']['total_expense'] == -50
    budget = auth_client_a.get('/api/v1/budgets/summary?month=2020-02').json()
    assert budget['total_spent'] == -50
    assert {c['name']: c['spent'] for c in budget['all_categories'] if c['spent']} == {'Category A': -30, 'Category B': -20}
    assert auth_client_a.get('/api/v1/dashboard/summary', params={**params, 'start_date': '2020-01-01', 'end_date': '2020-01-31'}).json()['outflows']['total'] == 100
    both = auth_client_a.get('/api/v1/transactions', params={'spending_net': True, 'limit': 1}).json()
    assert both['total_count'] == 2 and both['spending_summary']['net'] == 50
    page2 = auth_client_a.get('/api/v1/transactions', params={'spending_net': True, 'limit': 1, 'cursor': both['next_cursor']}).json()
    assert page2['spending_summary'] == both['spending_summary']
    assert page2['items'][0]['id'] != both['items'][0]['id']


def test_cross_account_refund_is_attributed_to_original_account(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = post(auth_client_a, accounts[0])
    refund = post(auth_client_a, accounts[1], amount='30', transaction_type='refund', refund_of_transaction_id=expense['id'])
    response = auth_client_a.get('/api/v1/transactions', params={'account_id': str(accounts[0].id), 'spending_net': True})
    assert response.status_code == 200, response.text
    assert {t['id'] for t in response.json()['items']} == {expense['id'], refund['id']}
    assert response.json()['spending_summary']['net'] == 70


def test_fx_drilldown_offsets_booked_spending_not_refund_cash(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    category = Category(family_id=family.id, name='Overseas purchase'); db.add(category); db.commit()
    quote(db)
    expense = create(auth_client_a, accounts[0], settlement_amount='700', settlement_currency='CNY', category_id=str(category.id)).json()
    refund = create(auth_client_a, accounts[0], transaction_type='refund', settlement_amount='720', settlement_currency='CNY',
                    refund_of_transaction_id=expense['id']).json()
    params = {'category_name': category.name, 'spending_net': True}
    response = auth_client_a.get('/api/v1/transactions', params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['spending_summary']['net'] == 0
    row = next(t for t in data['items'] if t['id'] == refund['id'])
    assert Decimal(row['amount']) == 720 and Decimal(row['spending_amount']) == -700


def test_automation_column_migrates_existing_sqlite(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "old-preferences.db"}')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE userpreference (id INTEGER PRIMARY KEY, username VARCHAR NOT NULL)'))
        conn.execute(text("INSERT INTO userpreference VALUES (1, 'old-user')"))
    sync_schema(engine)
    assert 'auto_refund_enabled' in {c['name'] for c in inspect(engine).get_columns('userpreference')}
    with engine.connect() as conn:
        assert conn.execute(text('SELECT auto_refund_enabled FROM userpreference')).scalar() == 1


def test_one_refund_in_multiple_categories_uses_only_selected_portion(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    categories = [Category(family_id=family.id, name=name) for name in ['A', 'B']]
    db.add_all(categories); db.commit()
    originals = [post(auth_client_a, accounts[0], narration=c.name, category_id=str(c.id)) for c in categories]
    refund = post(auth_client_a, accounts[0], transaction_type='refund', narration='Combined bank refund')
    for original, amount in zip(originals, [30, 70]):
        result = auth_client_a.post(f"/api/v1/refunds/{refund['id']}/allocate", json={
            'original_transaction_id': original['id'], 'allocated_amount': str(amount)})
        assert result.status_code == 200, result.text
    for category, net in zip(categories, [70, 30]):
        result = auth_client_a.get('/api/v1/transactions', params={'category_id': str(category.id), 'spending_net': True}).json()
        assert result['spending_summary']['net'] == net
        assert result['total_count'] == 2
        assert sum(Decimal(t['spending_amount']) for t in result['items']) == net
    unfiltered = auth_client_a.get('/api/v1/transactions', params={'spending_net': True}).json()
    assert unfiltered['spending_summary']['net'] == 100


def test_matching_ignores_untrusted_metadata_shapes(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    post(auth_client_a, accounts[0])
    refund = post(auth_client_a, accounts[0], transaction_type='refund',
                  extra={'direction': ['in'], 'merchant_name': {'name': 'Shop'}})
    db.expire_all()
    assert not db.get(Transaction, UUID(refund['id'])).refund_of_transaction_id


def test_october_third_manual_link_offsets_original_category_everywhere(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    categories = [Category(family_id=family.id, name=name) for name in ['Original shopping', 'Refund other']]
    db.add_all(categories); db.commit()
    auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': False})
    expense = post(auth_client_a, accounts[0], amount='100', transacted_at='2026-10-01',
                   category_id=str(categories[0].id), narration='Original merchant')
    refund = post(auth_client_a, accounts[0], amount='30', transacted_at='2026-10-03',
                  category_id=str(categories[1].id), narration='Bank refund', transaction_type='refund')
    params = {'period': 'custom', 'start_date': '2026-10-01', 'end_date': '2026-10-31'}
    before = auth_client_a.get('/api/v1/dashboard/summary', params=params).json()
    assert {c['name']: c['amount'] for c in before['outflows']['categories']} == {'Original shopping': 100, 'Refund other': -30}
    response = auth_client_a.post(f"/api/v1/refunds/{refund['id']}/link/{expense['id']}")
    assert response.status_code == 200, response.text
    overview = auth_client_a.get('/api/v1/dashboard/summary', params=params).json()
    assert {c['name']: c['amount'] for c in overview['outflows']['categories']} == {'Original shopping': 70}
    analytics = auth_client_a.get('/api/v1/analytics/report', params=params).json()
    assert analytics['kpis']['total_expense'] == 70
    budget = auth_client_a.get('/api/v1/budgets/summary?month=2026-10').json()
    assert {c['name']: c['spent'] for c in budget['all_categories'] if c['spent']} == {'Original shopping': 70}
    detail = auth_client_a.get(f"/api/v1/transactions/{expense['id']}").json()
    assert Decimal(detail['amount']) == 100 and Decimal(detail['refund_info']['total_refunded']) == 30
    drilldown = auth_client_a.get('/api/v1/transactions', params={
        'spending_net': True, 'category_name': categories[0].name,
        'start_date': '2026-10-01', 'end_date': '2026-10-31'}).json()
    assert drilldown['total_count'] == 2 and drilldown['spending_summary']['net'] == 70
    refund_day = auth_client_a.get('/api/v1/dashboard/summary', params={
        **params, 'start_date': '2026-10-03', 'end_date': '2026-10-03'}).json()
    assert {c['name']: c['amount'] for c in refund_day['outflows']['categories']} == {'Original shopping': -30}


def test_fully_linked_refund_category_follows_original_and_rejects_direct_edits(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    categories = [Category(family_id=family.id, name=name) for name in ['Purchase category', 'Bank refund category', 'Corrected purchase']]
    db.add_all(categories); db.commit()
    auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': False})
    expense = post(auth_client_a, accounts[0], category_id=str(categories[0].id))
    refund = post(auth_client_a, accounts[0], amount='30', transaction_type='refund',
                  category_id=str(categories[1].id), refund_of_transaction_id=expense['id'])
    url = f"/api/v1/transactions/{refund['id']}"
    detail = auth_client_a.get(url).json()
    assert detail['category_id'] == str(categories[0].id)
    assert detail['category_name'] == categories[0].name
    assert detail['refund_info']['category_editable'] is False
    assert [c['id'] for c in detail['refund_info']['linked_categories']] == [str(categories[0].id)]
    rejected = auth_client_a.patch(url, json={'category_id': str(categories[1].id), 'notes': 'Must not persist'})
    assert rejected.status_code == 400
    assert auth_client_a.get(url).json()['notes'] != 'Must not persist'
    assert auth_client_a.patch(url, json={'notes': 'Still editable'}).status_code == 200
    split = auth_client_a.post(url + '/split', json={'splits': [
        {'category_id': str(c.id), 'amount': '15'} for c in categories[:2]]})
    assert split.status_code == 400
    assert auth_client_a.patch(f"/api/v1/transactions/{expense['id']}", json={'category_id': str(categories[2].id)}).status_code == 200
    assert auth_client_a.get(url).json()['category_name'] == categories[2].name
    for field, value in [('category_name', categories[2].name), ('category_id', str(categories[2].id))]:
        rows = auth_client_a.get('/api/v1/transactions', params={field: value, 'transaction_type': 'refund'}).json()
        assert rows['total_count'] == 1
        assert rows['items'][0]['category_id'] == str(categories[2].id)
        assert rows['items'][0]['refund_category_info']['category_editable'] is False
    assert auth_client_a.get('/api/v1/transactions', params={'category_name': categories[1].name,
        'transaction_type': 'refund'}).json()['total_count'] == 0
    assert auth_client_a.post(f"/api/v1/refunds/{refund['id']}/unlink").status_code == 200
    assert auth_client_a.get(url).json()['refund_info']['category_editable'] is True
    assert auth_client_a.patch(url, json={'category_id': str(categories[1].id)}).status_code == 200


def test_partial_refund_category_edit_only_changes_unallocated_remainder(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    categories = [Category(family_id=family.id, name=name) for name in ['Purchase', 'Original refund', 'Remaining refund']]
    db.add_all(categories); db.commit()
    auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': False})
    expense = post(auth_client_a, accounts[0], category_id=str(categories[0].id))
    refund = post(auth_client_a, accounts[0], transaction_type='refund', category_id=str(categories[1].id))
    response = auth_client_a.post(f"/api/v1/refunds/{refund['id']}/allocate", json={
        'original_transaction_id': expense['id'], 'allocated_amount': '30'})
    assert response.status_code == 200, response.text
    detail = auth_client_a.patch(f"/api/v1/transactions/{refund['id']}", json={'category_id': str(categories[2].id)}).json()
    assert detail['refund_info']['category_editable'] is True
    assert Decimal(detail['refund_info']['remaining_amount']) == 70
    assert detail['category_name'] == categories[2].name
    assert detail['refund_info']['linked_categories'][0]['name'] == categories[0].name
    assert auth_client_a.get(f"/api/v1/transactions/{expense['id']}").json()['category_id'] == str(categories[0].id)
    overview = auth_client_a.get('/api/v1/dashboard/summary?period=ALL').json()
    assert {c['name']: c['amount'] for c in overview['outflows']['categories']} == {'Purchase': 70, 'Remaining refund': -70}
    response = auth_client_a.post(f"/api/v1/refunds/{refund['id']}/allocate", json={
        'original_transaction_id': expense['id'], 'allocated_amount': '100'})
    assert response.status_code == 200, response.text
    detail = auth_client_a.get(f"/api/v1/transactions/{refund['id']}").json()
    assert detail['refund_info']['category_editable'] is False
    assert detail['category_name'] == categories[0].name


def test_multi_original_and_split_refund_inherits_all_categories(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    categories = [Category(family_id=family.id, name=name) for name in ['Dining', 'Travel', 'Split shopping', 'Bank refund']]
    db.add_all(categories); db.commit()
    auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': False})
    originals = [post(auth_client_a, accounts[0], category_id=str(c.id)) for c in categories[:2]]
    refund = post(auth_client_a, accounts[0], transaction_type='refund', category_id=str(categories[3].id))
    for original, amount in zip(originals, ['30', '70']):
        response = auth_client_a.post(f"/api/v1/refunds/{refund['id']}/allocate", json={
            'original_transaction_id': original['id'], 'allocated_amount': amount})
        assert response.status_code == 200, response.text
    split = auth_client_a.post(f"/api/v1/transactions/{originals[0]['id']}/split", json={'splits': [
        {'category_id': str(c.id), 'amount': '50'} for c in [categories[0], categories[2]]]})
    assert split.status_code == 200, split.text
    detail = auth_client_a.get(f"/api/v1/transactions/{refund['id']}").json()
    assert detail['refund_info']['category_editable'] is False
    assert detail['category_id'] is None
    assert {c['id'] for c in detail['refund_info']['linked_categories']} == {str(c.id) for c in categories[:3]}
    for c in categories[:3]:
        rows = auth_client_a.get('/api/v1/transactions', params={'category_id': str(c.id), 'transaction_type': 'refund'}).json()
        assert rows['total_count'] == 1 and rows['items'][0]['id'] == refund['id']


def test_refund_category_does_not_disclose_a_now_private_original(auth_client_a, db):
    family, _, bob, accounts = setup_accounts(db)
    category = Category(family_id=family.id, name='Private original category'); db.add(category); db.commit()
    expense = post(auth_client_a, accounts[0], category_id=str(category.id))
    refund = post(auth_client_a, accounts[1], amount='30', transaction_type='refund', refund_of_transaction_id=expense['id'])
    accounts[0].owner_id = bob.id; db.add(accounts[0]); db.commit()
    detail = auth_client_a.get(f"/api/v1/transactions/{refund['id']}").json()
    assert detail['refund_info']['category_editable'] is False
    assert detail['refund_info']['linked_categories'] == []
    assert detail['category_name'] == '随原消费分类'
    assert detail['category_id'] is None

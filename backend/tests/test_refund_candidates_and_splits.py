"""Recommendations, manual history searches and operable split/allocation flows."""
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import select

from models import Account, AccountShare, Category, Family, Transaction, TransactionSplit
from test_fix104_regressions import setup_accounts


def activity(db, account, kind='expense', day=date(2026, 10, 30), narration='Order Supermarket', amount='100', **extra):
    row = Transaction(account_id=account.id, transaction_type=kind, transacted_at=day,
        narration=narration, amount=Decimal(amount), currency='CNY',
        original_amount=Decimal(amount), original_currency='CNY', **extra)
    db.add(row); db.commit(); db.refresh(row)
    return row


def candidates(client, refund, **params):
    response = client.get(f'/api/v1/refunds/{refund.id}/candidates', params=params)
    assert response.status_code == 200, response.text
    return response.json()['candidates']


def test_recommendations_use_calendar_months_score_before_limit_and_ignore_refund_prefix(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    refund = activity(db, accounts[0], 'refund', date(2026, 10, 31), 'Refund Order Supermarket')
    old_exact = activity(db, accounts[0], day=date(2026, 8, 31))
    outside = activity(db, accounts[0], day=date(2026, 8, 30))
    activity(db, accounts[0], day=date(2026, 10, 30), narration='XYZ independent seller')
    activity(db, accounts[0], day=date(2026, 11, 1))
    rows = candidates(auth_client_a, refund, limit=1)
    assert [row['id'] for row in rows] == [str(old_exact.id)]
    assert rows[0]['similarity_score'] > .5
    assert rows[0]['score_components']['opposite_directions'] is True
    assert str(outside.id) not in {row['id'] for row in candidates(auth_client_a, refund)}


def test_recommendation_score_threshold_is_strict(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db)
    refund = activity(db, accounts[0], 'refund')
    excluded = activity(db, accounts[0], narration='At threshold')
    included = activity(db, accounts[0], narration='Above threshold')
    monkeypatch.setattr('routes.v1_refunds.refund_match_score', lambda refund, original, remaining, **kw:
        (.5 if original.id == excluded.id else .50001, {'opposite_directions': True}))
    assert [row['id'] for row in candidates(auth_client_a, refund)] == [str(included.id)]


def test_history_checkbox_search_finds_old_unrelated_expenses_but_not_future_or_income(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    refund = activity(db, accounts[0], 'refund')
    old = activity(db, accounts[0], day=date(2020, 1, 1), narration='Unique old purchase')
    activity(db, accounts[0], 'income', date(2020, 1, 1), 'Unique income')
    activity(db, accounts[0], day=date(2026, 11, 1), narration='Unique future')
    assert candidates(auth_client_a, refund, search='Unique') == []
    rows = candidates(auth_client_a, refund, recommendations_only=False, search='Unique')
    assert [row['id'] for row in rows] == [str(old.id)]
    assert rows[0]['score_components']['days_apart'] > 90
    assert 0 <= rows[0]['similarity_score'] <= 1


def test_preview_expense_to_refund_does_not_mutate_the_original(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    source = activity(db, accounts[0], extra={'direction': 'outflow'})
    original = activity(db, accounts[0], day=date(2026, 10, 29))
    rows = candidates(auth_client_a, source, preview_refund=True)
    assert [row['id'] for row in rows] == [str(original.id)]
    db.expire_all()
    assert db.get(Transaction, source.id).transaction_type == 'expense'
    assert db.get(Transaction, source.id).extra['direction'] == 'outflow'
    auth_client_a.put('/api/user-preferences', json={'auto_refund_enabled': False})
    converted = auth_client_a.put(f'/api/v1/transactions/{source.id}', json={'transaction_type': 'refund'})
    assert converted.status_code == 200, converted.text
    assert converted.json()['extra']['direction'] == 'inflow'
    assert [row['id'] for row in candidates(auth_client_a, source)] == [str(original.id)]


def test_partial_and_multi_purchase_allocation_remains_operable(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    refund = activity(db, accounts[0], 'refund')
    first = activity(db, accounts[0], amount='30')
    second = activity(db, accounts[0], amount='70')
    assert str(first.id) in {row['id'] for row in candidates(auth_client_a, refund)}
    response = auth_client_a.post(f'/api/v1/refunds/{refund.id}/allocate', json={
        'original_transaction_id': str(first.id), 'allocated_amount': '30', 'original_currency': 'CNY', 'refund_original_amount': '30'})
    assert response.status_code == 200, response.text
    rows = candidates(auth_client_a, refund)
    assert [row['id'] for row in rows] == [str(second.id)]
    response = auth_client_a.post(f'/api/v1/refunds/{refund.id}/allocate', json={
        'original_transaction_id': str(second.id), 'allocated_amount': '70', 'original_currency': 'CNY', 'refund_original_amount': '70'})
    assert response.status_code == 200, response.text
    detail = auth_client_a.get(f'/api/v1/transactions/{refund.id}').json()['refund_info']
    assert detail['is_fully_allocated'] and len(detail['allocations']) == 2
    assert all(row['narration'] == 'Order Supermarket' for row in detail['allocations'])
    assert auth_client_a.post(f'/api/v1/refunds/{refund.id}/unlink').status_code == 200
    assert len(candidates(auth_client_a, refund)) == 2


def test_candidates_exclude_readonly_cross_family_and_wrong_direction_expenses(auth_client_a, db):
    family, alice, bob, accounts = setup_accounts(db)
    refund = activity(db, accounts[0], 'refund')
    allowed = activity(db, accounts[0])
    readonly = Account(family_id=family.id, owner_id=bob.id, name='Readonly', currency='CNY', account_type='checking')
    other_family = Family(name='Foreign'); db.add(other_family); db.flush()
    foreign = Account(family_id=other_family.id, owner_id=bob.id, name='Foreign', currency='CNY', account_type='checking')
    db.add_all([readonly, foreign]); db.flush()
    db.add(AccountShare(account_id=readonly.id, user_id=alice.id, permission='read_only')); db.commit()
    activity(db, readonly); activity(db, foreign)
    activity(db, accounts[0], extra={'direction': 'inflow'})
    for history in [True, False]:
        assert [row['id'] for row in candidates(auth_client_a, refund, recommendations_only=history)] == [str(allowed.id)]
    alice.role = 'admin'; db.add(alice); db.commit()
    assert [row['id'] for row in candidates(auth_client_a, refund, recommendations_only=False)] == [str(allowed.id)]


@pytest.mark.parametrize('kind', ['expense', 'refund'])
def test_splits_round_trip_clear_and_preserve_parent_money(auth_client_a, db, kind):
    family, _, _, accounts = setup_accounts(db)
    categories = [Category(family_id=family.id, name=name) for name in ['Food', 'Shopping']]
    db.add_all(categories); db.commit()
    row = activity(db, accounts[0], kind, category_id=categories[0].id)
    url = f'/api/v1/transactions/{row.id}/split'
    payload = {'splits': [{'amount': '30.0001', 'category_id': str(categories[0].id)},
                          {'amount': '69.9999', 'category_id': str(categories[1].id)}]}
    response = auth_client_a.post(url, json=payload)
    assert response.status_code == 200, response.text
    bad = {'splits': [{'amount': '30.004'}, {'amount': '70'}]}
    assert auth_client_a.post(url, json=bad).status_code == 400
    detail = auth_client_a.get(f'/api/v1/transactions/{row.id}').json()
    assert detail['is_split'] and len(detail['splits']) == 2
    assert sum(Decimal(s['amount']) for s in detail['splits']) == 100
    assert {Decimal(s['amount']) for s in detail['splits']} == {Decimal('30.0001'), Decimal('69.9999')}
    stored_splits = auth_client_a.get(f'/api/v1/transactions/{row.id}/splits').json()
    assert {Decimal(s['amount']) for s in stored_splits} == {Decimal('30.0001'), Decimal('69.9999')}
    assert auth_client_a.delete(url).status_code == 200
    db.expire_all()
    saved = db.get(Transaction, row.id)
    assert not saved.is_split and saved.amount == 100 and saved.category_id == categories[0].id
    assert not db.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == row.id)).all()


def test_split_mutations_reject_readonly_and_income_accounts(auth_client_a, db):
    family, alice, bob, accounts = setup_accounts(db)
    account = Account(family_id=family.id, owner_id=bob.id, name='Read only', currency='CNY', account_type='checking')
    db.add(account); db.flush()
    db.add(AccountShare(account_id=account.id, user_id=alice.id, permission='read_only')); db.commit()
    readonly = activity(db, account)
    payload = {'splits': [{'amount': '40'}, {'amount': '60'}]}
    url = f'/api/v1/transactions/{readonly.id}/split'
    assert auth_client_a.post(url, json=payload).status_code == 403
    assert auth_client_a.delete(url).status_code == 403
    income = activity(db, accounts[0], 'income')
    assert auth_client_a.post(f'/api/v1/transactions/{income.id}/split', json=payload).status_code == 400


def test_manual_cross_currency_match_requires_explicit_native_quantities(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    refund = activity(db, accounts[0], 'refund', amount='70')
    original = activity(db, accounts[0], amount='70')
    original.original_currency = 'USD'; original.original_amount = Decimal(10)
    db.add(original); db.commit()
    assert str(original.id) in {row['id'] for row in candidates(auth_client_a, refund)}
    url = f'/api/v1/refunds/{refund.id}/allocate'
    assert auth_client_a.post(url, json={'original_transaction_id': str(original.id), 'allocated_amount': '10'}).status_code == 400
    response = auth_client_a.post(url, json={'original_transaction_id': str(original.id), 'allocated_amount': '10',
        'original_currency': 'USD', 'refund_original_amount': '70'})
    assert response.status_code == 200, response.text
    assert auth_client_a.get(f'/api/v1/transactions/{refund.id}').json()['refund_info']['is_fully_allocated']

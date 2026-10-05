from datetime import date
from decimal import Decimal

import pytest

from models import Category, Transaction
from test_fix104_regressions import setup_accounts


def test_budget_percentages_persist_resize_and_remove(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    db.add(Category(family_id=family.id, name='餐饮美食', icon='🍴', color='#8b5cf6'))
    db.commit()
    payload = {"total_budget": 1000, "expected_income": 2000, "category_percentages": {"餐饮美食": 25, "购物消费": 12.5}}
    saved = auth_client_a.post('/api/v1/budgets/settings', json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()['settings']['category_budgets'] == {"餐饮美食": 250, "购物消费": 125}
    resized = auth_client_a.post('/api/v1/budgets/settings', json={"total_budget": 2000})
    assert resized.status_code == 200
    assert resized.json()['settings']['category_budgets'] == {"餐饮美食": 500, "购物消费": 250}
    category = Category(family_id=family.id, name='购物消费')
    db.add(category)
    db.flush()
    db.add(Transaction(account_id=accounts[0].id, amount=Decimal('10'), currency='CNY',
                       transaction_type='expense', transacted_at=date.today(), category_id=category.id, narration='Budget test'))
    db.commit()
    removed = auth_client_a.post('/api/v1/budgets/settings', json={"category_percentages": {"餐饮美食": 25}})
    assert removed.status_code == 200
    summary = auth_client_a.get('/api/v1/budgets/summary').json()
    assert summary['category_percentages'] == {"餐饮美食": 25}
    assert summary['category_budgets'] == {"餐饮美食": 500}
    assert next(category for category in summary['all_categories'] if category['name'] == '餐饮美食')['icon'] == '🍴'
    assert next(category for category in summary['all_categories'] if category['name'] == '购物消费')['budget'] == 0


def test_percentage_budget_rounding_zero_and_empty(auth_client_a, db):
    setup_accounts(db)
    saved = auth_client_a.post('/api/v1/budgets/settings', json={
        'total_budget': .01, 'expected_income': 0, 'category_percentages': {'A': 50, 'B': 50}})
    assert saved.status_code == 200
    assert saved.json()['settings']['category_budgets'] == {'A': .01, 'B': 0}
    zero = auth_client_a.post('/api/v1/budgets/settings', json={'total_budget': 0})
    assert zero.json()['settings']['category_budgets'] == {'A': 0, 'B': 0}
    assert auth_client_a.get('/api/v1/budgets/summary').json()['expected_income'] == 0
    empty = auth_client_a.post('/api/v1/budgets/settings', json={'category_percentages': {}})
    assert empty.status_code == 200
    assert auth_client_a.get('/api/v1/budgets/summary').json()['category_percentages'] == {}


@pytest.mark.parametrize('percentages', [[], {'A': -1}, {'A': 101}, {'A': 60, 'B': 41},
                                       {'A': 'nan'}, {'A': 'inf'}, {'A': True}, {'A': 0.001}, {'': 10}, {' A ': 10}])
def test_invalid_percentages_do_not_modify_saved_budget(auth_client_a, db, percentages):
    setup_accounts(db)
    original = {'total_budget': 1000, 'category_percentages': {'餐饮美食': 25}}
    assert auth_client_a.post('/api/v1/budgets/settings', json=original).status_code == 200
    rejected = auth_client_a.post('/api/v1/budgets/settings', json={'total_budget': 2000, 'category_percentages': percentages})
    assert rejected.status_code == 400, rejected.text
    summary = auth_client_a.get('/api/v1/budgets/summary').json()
    assert summary['total_budget'] == 1000
    assert summary['category_budgets'] == {'餐饮美食': 250}


def test_ordinary_member_cannot_change_budget_percentages(auth_client_b, auth_client_a, db):
    _, _, bob, _ = setup_accounts(db)
    bob.role = 'member'
    db.add(bob)
    db.commit()
    assert auth_client_b.post('/api/v1/budgets/settings', json={'category_percentages': {'餐饮美食': 100}}).status_code == 403

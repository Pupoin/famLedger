"""Behavior and tenant boundaries of persistent, portable classification rules."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import uuid
import pytest
from sqlmodel import select
from models import Account, AccountShare, Category, Family, Rule, Transaction, User
from services.rules.bundles import default_bundle, export_bundle, import_bundle
from services.rules.defaults import initialize_family_rules
from services.rules.pipeline import RulePipeline
from services.stats_engine import classify_transaction, classify_split_item


@pytest.fixture
def scope(db):
    family = Family(name='rules source')
    other_family = Family(name='rules destination')
    db.add_all([family, other_family]); db.flush()
    user = db.exec(select(User).where(User.username == 'alice')).one()
    user.family_id = family.id; user.role = 'owner'
    db.add(user)
    account = Account(name='rule account', account_type='checking', family_id=family.id, owner_id=user.id, currency='CNY')
    db.add(account); db.flush()
    initialize_family_rules(db, family.id)
    db.commit()
    return family, other_family, account


def txn(account, narration='unknown', **kwargs):
    return Transaction(account_id=account.id, external_id=str(uuid.uuid4()), narration=narration,
                       transacted_at=date(2026, 10, 1), amount=Decimal('100'), currency='CNY', **kwargs)


def cats(db, family):
    return {c.name: c for c in db.exec(select(Category).where(Category.family_id == family.id)).all()}


def category_rule(family, category, priority=10, **kwargs):
    return Rule(family_id=family.id, name=category.name, priority=priority,
                conditions={'operator': 'AND', 'rules': []}, actions=[{'type': 'set_category', 'value': str(category.id)}], **kwargs)


def test_first_category_wins_but_later_actions_run(db, scope):
    family, _, account = scope; categories = cats(db, family)
    first = category_rule(family, categories['交通出行'], 1)
    second = category_rule(family, categories['餐饮美食'], 2)
    second.actions += [{'type': 'add_tag', 'value': 'reviewed'}]
    row = txn(account, '美团骑行')
    RulePipeline([second, first], db).process_transaction(row)
    assert row.category_id == categories['交通出行'].id
    assert row.tags == ['reviewed']
    assert row.extra['classification']['rule_id'] == str(first.id)


def test_same_category_already_stored_still_locks_first_match(db, scope):
    family, _, account = scope; categories = cats(db, family)
    first = category_rule(family, categories['交通出行'], 1)
    row = txn(account, category_id=categories['交通出行'].id)
    RulePipeline([first, category_rule(family, categories['餐饮美食'], 2)], db).process_transaction(row)
    assert row.category_id == categories['交通出行'].id


@pytest.mark.parametrize('narration', ['unknown', '星巴克咖啡'])
def test_no_rules_always_other_and_statistics_have_no_hidden_classifier(db, scope, narration):
    family, _, account = scope; categories = cats(db, family)
    row = txn(account, narration, category_id=categories['餐饮美食'].id)
    RulePipeline([], db).process_transaction(row)
    assert row.category_id == categories['其他'].id
    mapping = {c.id: c for c in categories.values()}
    assert classify_transaction(row, mapping)['name'] == '其他'
    assert classify_split_item(categories['其他'].id, '星巴克咖啡', row, mapping)['name'] == '其他'


def test_manual_other_and_type_are_protected(db, scope):
    family, _, account = scope; categories = cats(db, family)
    row = txn(account, '星巴克', category_id=categories['其他'].id, category_source='manual',
              transaction_type='expense', extra={'transaction_type_source': 'manual'})
    rule = category_rule(family, categories['餐饮美食'])
    rule.actions += [{'type': 'set_transaction_type', 'value': 'transfer'}, {'type': 'add_tag', 'value': 'ok'}]
    RulePipeline([rule], db).process_transaction(row)
    assert row.category_id == categories['其他'].id
    assert row.transaction_type == 'expense'
    assert row.tags == ['ok']


def test_dry_run_is_detached_including_tags_and_trace(db, scope):
    family, _, account = scope; categories = cats(db, family)
    row = txn(account, '星巴克'); db.add(row); db.commit()
    db.refresh(row)
    before = deepcopy(row.model_dump())
    rule = category_rule(family, categories['餐饮美食'])
    rule.actions += [{'type': 'add_tag', 'value': 'preview'}, {'type': 'set_note', 'value': 'memo', 'mode': 'append'}]
    result = RulePipeline([rule], db).dry_run_batch([row], {})
    assert result['total_affected'] == 1
    assert row.model_dump() == before
    db.commit(); db.refresh(row)
    assert row.category_id is None and not row.tags and not row.extra


def test_portable_round_trip_all_actions_disabled_rules_and_category_conditions(db, scope):
    family, destination, _ = scope; categories = cats(db, family)
    rule = category_rule(family, categories['医疗健康'], priority=7, is_active=False, stop_processing=True)
    rule.conditions = {'field': 'category', 'operator': 'in', 'value': [str(categories['其他'].id)]}
    rule.actions += [{'type': 'exclude_from_statistics', 'value': False}, {'type': 'set_note', 'value': 'memo', 'mode': 'prepend'},
                     {'type': 'set_merchant', 'value': 'Clinic'}, {'type': 'set_transaction_type', 'value': 'expense'},
                     {'type': 'add_tag', 'value': 'health'}]
    db.add(rule); db.commit()
    bundle = export_bundle(db, family.id)
    assert str(categories['其他'].id) not in str(bundle)
    assert str(family.id) not in str(bundle)
    import_bundle(db, destination.id, bundle); db.commit()
    assert export_bundle(db, destination.id) == bundle


def test_import_preview_and_invalid_import_leave_database_untouched(db, scope):
    _, destination, _ = scope
    bundle = default_bundle()
    summary = import_bundle(db, destination.id, bundle, preview=True)
    assert summary['rule_count'] == 12
    assert not db.exec(select(Rule).where(Rule.family_id == destination.id)).all()
    assert not db.exec(select(Category).where(Category.family_id == destination.id)).all()
    bundle['rules'][-1]['actions'].append({'type': 'exclude_from_statistics', 'value': 'false'})
    with pytest.raises(ValueError): import_bundle(db, destination.id, bundle)
    db.commit()
    assert not db.exec(select(Category).where(Category.family_id == destination.id)).all()


def test_cross_family_category_rejected_in_import_and_actions(db, scope):
    source, destination, account = scope; categories = cats(db, source)
    bundle = default_bundle(); bundle['rules'][0]['actions'][0]['value'] = str(categories['餐饮美食'].id)
    with pytest.raises(ValueError): import_bundle(db, destination.id, bundle)
    foreign = Category(family_id=destination.id, name='foreign'); db.add(foreign); db.commit()
    row = txn(account)
    RulePipeline([category_rule(source, foreign)], db).process_transaction(row)
    assert row.category_id == categories['其他'].id


def test_legacy_regex_import_order_and_match(db, scope):
    _, destination, account = scope
    payload = [{'category': 'custom', 'emoji': '☕', 'patterns': ['^shop-[0-9]+$', '^shop-[0-9]+$']},
               {'category': '其他', 'emoji': '📦', 'patterns': ['unknown']}]
    import_bundle(db, destination.id, payload); db.commit()
    account.family_id = destination.id; db.add(account); db.commit()
    rules = db.exec(select(Rule).where(Rule.family_id == destination.id).order_by(Rule.priority)).all()
    assert len(rules[0].conditions['rules']) == 1
    row = txn(account, 'SHOP-123')
    RulePipeline(rules, db).process_transaction(row)
    assert db.get(Category, row.category_id).name == 'custom'


def test_default_rules_are_not_recreated_after_user_deletion(db, scope):
    family, _, _ = scope
    for rule in db.exec(select(Rule).where(Rule.family_id == family.id)).all(): db.delete(rule)
    db.commit()
    initialize_family_rules(db, family.id, migrate_history=True); db.commit()
    assert not db.exec(select(Rule).where(Rule.family_id == family.id)).all()


def test_initial_history_migration_preserves_types_amounts_ids_and_manual_categories(db, scope):
    family, _, account = scope; categories = cats(db, family)
    family.classification_rules_version = 0; db.add(family)
    auto = Rule(family_id=family.id, name='dangerous type action', priority=1,
                conditions={'operator': 'AND', 'rules': []}, actions=[{'type': 'set_transaction_type', 'value': 'income'}])
    db.add(auto)
    rows = [txn(account, '财付通-转账', transaction_type='transfer') for _ in range(31)]
    manual = txn(account, '星巴克咖啡', category_source='manual', category_id=categories['其他'].id)
    db.add_all([*rows, manual]); db.commit()
    before = [(r.id, r.external_id, r.amount, r.transaction_type) for r in rows]
    initialize_family_rules(db, family.id, migrate_history=True); db.commit()
    assert [(r.id, r.external_id, r.amount, r.transaction_type) for r in rows] == before
    assert all(r.transfer_id is None for r in rows)
    assert manual.category_id == categories['其他'].id


def test_rule_import_export_api_and_reorder_tenant_isolation(auth_client_a, db, scope):
    family, destination, _ = scope
    export = auth_client_a.get('/api/v1/rules/export')
    assert export.status_code == 200, export.text
    preview = auth_client_a.post('/api/v1/rules/import', json={'bundle': export.json(), 'preview': True})
    assert preview.status_code == 200, preview.text
    foreign = Rule(family_id=destination.id, name='foreign', conditions={}, actions=[]); db.add(foreign); db.commit()
    own = db.exec(select(Rule).where(Rule.family_id == family.id)).first(); priority = own.priority
    response = auth_client_a.put('/api/v1/rules/reorder', json=[{'id': str(own.id), 'priority': 1}, {'id': str(foreign.id), 'priority': 2}])
    assert response.status_code == 404
    db.refresh(own); assert own.priority == priority


def test_history_application_counts_only_writable_transactions_and_reports_zero_updates(auth_client_a, db, scope):
    family, destination, account = scope
    categories = cats(db, family)
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    read_only = Account(family_id=family.id, owner_id=bob.id, name='Read only', account_type='checking')
    foreign = Account(family_id=destination.id, owner_id=account.owner_id, name='Other family', account_type='checking')
    inactive = Account(family_id=family.id, owner_id=account.owner_id, name='Inactive', account_type='checking', is_active=False)
    db.add_all([read_only, foreign, inactive]); db.flush()
    db.add(AccountShare(account_id=read_only.id, user_id=account.owner_id, permission='read_only'))
    manual = txn(account, '星巴克咖啡', category_id=categories['其他'].id, category_source='manual')
    rows = [txn(account, '星巴克咖啡'), txn(account, 'unrecognized merchant xyz'), manual]
    untouched = [txn(a, '星巴克咖啡') for a in (read_only, foreign, inactive)]
    db.add_all([*rows, *untouched]); db.commit()

    response = auth_client_a.post('/api/v1/rules/apply-retroactive')
    assert response.status_code == 200, response.text
    assert response.json() == {'status': 'ok', 'evaluated_count': 3, 'modified_count': 2}
    for row in rows + untouched: db.refresh(row)
    assert rows[0].category_id == categories['餐饮美食'].id
    assert rows[1].category_id == manual.category_id == categories['其他'].id
    assert all(row.category_id is None and not row.extra for row in untouched)

    repeated = auth_client_a.post('/api/v1/rules/apply-retroactive')
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {'status': 'ok', 'evaluated_count': 3, 'modified_count': 0}


@pytest.mark.parametrize('single_rule', [False, True])
def test_history_application_without_writable_accounts_reports_completion(auth_client_a, db, scope, single_rule):
    family, _, account = scope
    account.is_active = False
    db.add(account); db.commit()
    rule = db.exec(select(Rule).where(Rule.family_id == family.id)).first()
    path = f'/api/v1/rules/{rule.id}/apply' if single_rule else '/api/v1/rules/apply-retroactive'
    response = auth_client_a.post(path)
    assert response.status_code == 200, response.text
    assert response.json() == {'status': 'ok', 'evaluated_count': 0, 'modified_count': 0}


def test_post_category_manual_choice_and_duplicate_preserve_original(auth_client_a, db, scope):
    family, _, account = scope; categories = cats(db, family)
    base = dict(account=str(account.id), amount='10', currency='CNY', transacted_at='2026-10-01', transaction_type='expense')
    for key, text, explicit, expected in [('match', '星巴克咖啡', False, '餐饮美食'),
                                          ('fallback', 'unrecognized merchant xyz', False, '其他'),
                                          ('manual', '星巴克咖啡', True, '其他')]:
        payload = {**base, 'external_id': key, 'narration': text}
        if explicit: payload['category_id'] = str(categories['其他'].id)
        response = auth_client_a.post('/api/v1/transactions', json=payload)
        assert response.status_code == 200, response.text
        row = db.get(Transaction, uuid.UUID(response.json()['id']))
        assert row.category_id == categories[expected].id
        detail = auth_client_a.get(f'/api/v1/transactions/{row.id}').json()
        assert detail['category_name'] == expected
        duplicate = auth_client_a.post('/api/v1/transactions', json={**payload, 'amount': '200', 'narration': 'changed'})
        assert duplicate.status_code == 200 and duplicate.json()['status'] == 'duplicate'
        db.refresh(row)
        assert row.amount == Decimal('10') and row.narration == text


def test_wallet_payment_rule_uses_bank_facts_and_cannot_auto_pair(auth_client_a, db, scope):
    family, _, account = scope
    rule = Rule(family_id=family.id, name='Wallet payment is expense', priority=1,
                conditions={'operator':'AND','rules':[
                    {'field':'import_source','operator':'equals','value':'mailbridge'},
                    {'field':'bank_action','operator':'equals','value':'支付'},
                    {'field':'merchant','operator':'contains','value':'微信转账'}]},
                actions=[{'type':'set_transaction_type','value':'expense'}])
    other = Account(family_id=family.id, owner_id=account.owner_id, name='Other account', account_type='checking', currency='CNY')
    db.add_all([rule,other]); db.flush()
    income = Transaction(account_id=other.id, narration='收到转账', amount=Decimal('30'), currency='CNY',
                         transacted_at=date(2026,10,1), transaction_type='income')
    db.add(income); db.commit()
    response = auth_client_a.post('/api/v1/transactions',json={
        'account':str(account.id),'external_id':'wallet-payment','amount':'30','currency':'CNY',
        'narration':'财付通-微信转账快捷','transaction_type':'transfer','transacted_at':'2026-10-01',
        'extra':{'import_source':'mailbridge','bank_action':'支付','direction':'outflow'}})
    assert response.status_code == 200, response.text
    row = db.get(Transaction,uuid.UUID(response.json()['id']))
    assert row.transaction_type == 'expense' and row.transfer_id is None
    db.refresh(income)
    assert income.transaction_type == 'income' and income.transfer_id is None

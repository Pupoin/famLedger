"""Portable, validated import/export of categories and complete automation rules."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from functools import lru_cache
from typing import Any, Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select
from models import Category, Rule
from .categories import category_path, resolve_category
from .evaluator import ConditionEvaluator


class CategoryDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: list[str] = Field(min_length=1, max_length=12)
    name: str = Field(min_length=1, max_length=100)
    icon: Optional[str] = Field(default=None, max_length=50)
    color: Optional[str] = Field(default=None, max_length=30)
    category_type: Literal['expense', 'income'] = 'expense'
    i18n_key: Optional[str] = Field(default=None, max_length=100)


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=5000)
    priority: int = Field(default=100, ge=-2147483648, le=2147483647)
    is_active: bool = True
    stop_processing: bool = False
    conditions: dict[str, Any]
    actions: list[dict[str, Any]] = Field(min_length=1, max_length=30)


class Bundle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['famledger.rules']
    schema_version: Literal[1]
    categories: list[CategoryDefinition] = Field(default_factory=list, max_length=500)
    rules: list[RuleDefinition] = Field(max_length=500)


def legacy_bundle(groups):
    """Only the explicitly imported legacy JSON defines legacy keyword rules."""
    categories, rules = [], []
    if not groups or len(groups) > 500:
        raise ValueError('旧格式分类规则数量无效')
    for index, group in enumerate(groups):
        if not isinstance(group, dict) or set(group) - {'category', 'emoji', 'patterns'}:
            raise ValueError('旧格式必须包含 category、emoji、patterns')
        name, patterns = group.get('category'), group.get('patterns')
        if not isinstance(patterns, list) or not patterns or any(not isinstance(p, str) or not p for p in patterns):
            raise ValueError('旧格式 patterns 必须为非空字符串数组')
        categories.append(dict(path=[name], name=name, icon=group.get('emoji'), category_type='expense'))
        rules.append(dict(name=name, priority=1000 + index,
            conditions={'operator': 'OR', 'rules': [dict(field='merchant', operator='regex', value=p)
                                                  for p in dict.fromkeys(patterns)]},
            actions=[dict(type='set_category', value={'path': [name]})]))
    return dict(format='famledger.rules', schema_version=1, categories=categories, rules=rules)


def validate_actions(actions, category_resolver):
    allowed = {'set_category', 'set_merchant', 'set_narration', 'set_description',
               'set_transaction_type', 'exclude_from_statistics', 'set_note', 'add_tag'}
    if not isinstance(actions, list) or not 1 <= len(actions) <= 30:
        raise ValueError('actions 必须包含 1–30 个动作')
    normalized = deepcopy(actions)
    for act in normalized:
        if not isinstance(act, dict) or act.get('type') not in allowed or set(act) - {'type', 'value', 'target_value', 'mode'}:
            raise ValueError('无效或不支持的规则动作')
        if 'value' not in act and 'target_value' in act:
            act['value'] = act.pop('target_value')
        val = act.get('value')
        if val is None or (isinstance(val, str) and not val.strip() and act['type'] != 'set_note'):
            raise ValueError('规则动作缺少 value')
        if act['type'] == 'set_category':
            act['value'] = str(category_resolver(val))
        elif act['type'] == 'exclude_from_statistics':
            if not isinstance(val, bool):
                raise ValueError('统计排除动作必须使用布尔值')
        elif act['type'] == 'set_transaction_type':
            if val not in ('expense', 'income', 'transfer', 'refund'):
                raise ValueError('无效的交易类型')
        elif not isinstance(val, str) or len(val) > 5000:
            raise ValueError('动作文本必须为字符串且不能超过 5000 字符')
        if 'mode' in act and (act['type'] != 'set_note' or act['mode'] not in ('overwrite', 'append', 'prepend')):
            raise ValueError('无效的备注写入模式')
    return normalized


def map_category_conditions(node, resolver):
    result = deepcopy(node)
    if result.get('field') in ('category', 'category_id') and result.get('operator') not in ('is_empty', 'is_not_empty'):
        if result.get('operator') not in ('equals', '==', 'not_equals', '!=', 'in', 'not_in'):
            raise ValueError('分类条件只支持相等、集合与空值比较')
        value = result.get('value')
        result['value'] = [resolver(v) for v in value] if isinstance(value, list) else resolver(value)
    if 'rules' in result:
        result['rules'] = [map_category_conditions(child, resolver) for child in result['rules']]
    return result


def plan_import(session, family_id, payload, mode='append'):
    if mode not in ('append', 'merge') or not family_id:
        raise ValueError('导入必须指定当前家庭和有效模式')
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 2_000_000:
        raise ValueError('规则文件不能超过 2 MB')
    bundle = Bundle.model_validate(legacy_bundle(payload) if isinstance(payload, list) else payload)
    existing = session.exec(select(Category).where(Category.family_id == family_id)).all()
    mapping = {c.id: c for c in existing}
    paths = {}
    for cat in existing:
        key = tuple(category_path(cat, mapping))
        if key in paths:
            raise ValueError('当前家庭存在重名分类路径，请先处理重名分类')
        paths[key] = cat
    new_categories, declared = [], set()
    for definition in sorted(bundle.categories, key=lambda c: len(c.path)):
        key = tuple(definition.path)
        if definition.path[-1] != definition.name or any(not isinstance(p, str) or not p.strip() or len(p) > 100 for p in key) or key in declared:
            raise ValueError('分类路径无效或重复')
        declared.add(key)
        if key in paths:
            continue
        parent = paths.get(key[:-1]) if len(key) > 1 else None
        if len(key) > 1 and parent is None:
            raise ValueError('分类路径缺少父分类定义')
        cat = Category(id=uuid.uuid4(), family_id=family_id, parent_id=parent.id if parent else None,
                       **definition.model_dump(exclude={'path'}))
        paths[key] = cat
        new_categories.append(cat)

    def resolve(value):
        if isinstance(value, dict) and set(value) == {'path'} and isinstance(value['path'], list):
            cat = paths.get(tuple(value['path']))
            if cat:
                return cat.id
            raise ValueError('分类引用不存在于文件或当前家庭')
        return resolve_category(session, value, family_id)

    new_rules, names = [], set()
    existing_rules = session.exec(select(Rule).where(Rule.family_id == family_id)).all()
    for definition in bundle.rules:
        if mode == 'merge' and (definition.name in names or sum(r.name == definition.name for r in existing_rules) > 1):
            raise ValueError('按名称合并要求规则名称唯一')
        names.add(definition.name)
        data = definition.model_dump()
        data['conditions'] = map_category_conditions(data['conditions'], lambda v: str(resolve(v)))
        ConditionEvaluator.validate(data['conditions'])
        data['actions'] = validate_actions(data['actions'], resolve)
        target = next((r for r in existing_rules if r.name == definition.name), None) if mode == 'merge' else None
        new_rules.append((target, data))
    return new_categories, new_rules


def import_bundle(session, family_id, payload, mode='append', preview=False):
    categories, rules = plan_import(session, family_id, payload, mode)
    summary = dict(rule_count=len(rules), categories_created=len(categories),
                   rules_created=sum(target is None for target, _ in rules),
                   rules_updated=sum(target is not None for target, _ in rules),
                   active_count=sum(data['is_active'] for _, data in rules),
                   rules=[{'name': data['name'], 'priority': data['priority'],
                           'is_active': data['is_active'], 'action_count': len(data['actions'])} for _, data in rules])
    if preview:
        return summary
    for cat in categories:
        session.add(cat)
    session.flush()
    now = datetime.now(timezone.utc)
    for index, (target, data) in enumerate(rules):
        if target is None:
            target = Rule(family_id=family_id, created_at=now + timedelta(microseconds=index), **data)
        else:
            for key, value in data.items():
                setattr(target, key, value)
            target.updated_at = now
        session.add(target)
    session.flush()
    return summary


def export_bundle(session, family_id):
    categories = session.exec(select(Category).where(Category.family_id == family_id)).all()
    mapping = {c.id: c for c in categories}

    def reference(value):
        identifier = uuid.UUID(str(value))
        if identifier not in mapping:
            raise ValueError('规则包含无效或跨家庭分类引用，请先修正规则')
        return {'path': category_path(mapping[identifier], mapping)}

    rules = session.exec(select(Rule).where(Rule.family_id == family_id)
                         .order_by(Rule.priority, Rule.created_at, Rule.id)).all()
    items = []
    for rule in rules:
        data = {key: getattr(rule, key) for key in RuleDefinition.model_fields}
        data['conditions'] = map_category_conditions(data['conditions'], reference)
        data['actions'] = deepcopy(rule.actions)
        for act in data['actions']:
            if act['type'] == 'set_category':
                act['value'] = reference(act.get('value', act.get('target_value')))
                act.pop('target_value', None)
        items.append(data)
    return dict(format='famledger.rules', schema_version=1,
                categories=[dict(path=category_path(c, mapping), **{k: getattr(c, k) for k in CategoryDefinition.model_fields if k != 'path'})
                            for c in sorted(categories, key=lambda c: category_path(c, mapping))], rules=items)


@lru_cache(maxsize=1)
def _default_bundle():
    return json.loads(Path(__file__).with_name('default_rules.json').read_text(encoding='utf-8'))


def default_bundle():
    return deepcopy(_default_bundle())

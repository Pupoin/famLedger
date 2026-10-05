"""Specification + Composite Condition Evaluator for FamLedger Rules Engine."""

from __future__ import annotations

import regex as re
from functools import lru_cache
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from models import Transaction


@lru_cache(maxsize=4096)
def _compiled_regex(pattern):
    return re.compile(pattern, flags=re.IGNORECASE)


class ConditionEvaluator:
    """评估单条或复合规则条件树。"""

    @classmethod
    def evaluate(cls, condition: Dict[str, Any], txn: Transaction, account_name: str = "") -> bool:
        """
        递归评估条件节点。
        节点类型：
        1. 逻辑复合节点: {"operator": "AND"|"OR"|"NOT", "rules": [...]}
        2. 基础比较节点: {"field": "...", "operator": "...", "value": ...}
        """
        try:
            cls.validate(condition)
        except ValueError:
            return False
        return cls._evaluate(condition, txn, account_name)

    @classmethod
    def _evaluate(cls, condition, txn, account_name):
        operator = condition.get("operator", "AND").upper()

        if operator in ("AND", "OR", "NOT"):
            sub_rules = condition.get("rules", [])
            if operator == "AND":
                return all(cls._evaluate(sub, txn, account_name) for sub in sub_rules)
            elif operator == "OR":
                return any(cls._evaluate(sub, txn, account_name) for sub in sub_rules)
            elif operator == "NOT":
                return not any(cls._evaluate(sub, txn, account_name) for sub in sub_rules)

        # 基础条件评估
        field = condition.get("field", "")
        op = condition.get("operator", "equals").lower()
        expected = condition.get("value")

        actual_val = cls._get_field_value(field, txn, account_name)
        return cls._match_condition(actual_val, op, expected)

    @classmethod
    def validate(cls, condition, depth=0, budget=None):
        budget = [0] if budget is None else budget
        budget[0] += 1
        if depth > 12 or budget[0] > 200 or not isinstance(condition, dict):
            raise ValueError("规则条件树结构无效或超出限制")
        op = condition.get("operator", "AND")
        if not isinstance(op, str):
            raise ValueError("规则运算符必须为字符串")
        if op.upper() in {"AND", "OR", "NOT"}:
            rules = condition.get("rules", [])
            if not isinstance(rules, list):
                raise ValueError("复合规则必须包含 rules 数组")
            for sub in rules:
                cls.validate(sub, depth + 1, budget)
            return
        allowed = {">", ">=", "gte", "<", "<=", "lte", "==", "!=", "equals", "not_equals",
                   "contains", "not_contains", "starts_with", "ends_with", "regex", "in", "not_in",
                   "between", "is_empty", "is_not_empty"}
        field = condition.get("field")
        if op.lower() not in allowed or not isinstance(field, str) or not field:
            raise ValueError("规则字段或运算符无效")
        field = field.strip().lower()
        if field not in {"merchant", "merchant_name", "description", "name", "narration", "amount", "account", "notes", "category", "category_id", "type", "currency", "transaction_type", "tags", "status", "transacted_at", "is_reimbursable", "excluded_from_stats", "import_source", "bank_action"}:
            raise ValueError("不支持的规则字段")
        value = condition.get("value")
        if field == "amount" and op.lower() not in {"is_empty", "is_not_empty"}:
            values = value if op.lower() in {"between", "in", "not_in"} else [value]
            if not isinstance(values, (list, tuple)) or (op.lower() == "between" and len(values) != 2):
                raise ValueError("金额条件必须包含有效数字范围")
            try:
                if any(not Decimal(str(v)).is_finite() for v in values):
                    raise ValueError("金额条件必须为有限数字")
            except InvalidOperation:
                raise ValueError("金额条件必须为有效数字")
        if op.lower() in {"in", "not_in"} and not isinstance(value, list):
            raise ValueError("成员比较条件必须为数组")
        if op.lower() == "regex":
            if not isinstance(value, str) or len(value) > 512:
                raise ValueError("正则表达式过长或无效")
            try:
                _compiled_regex(value)
            except re.error:
                raise ValueError("正则表达式无效")

    @classmethod
    def _get_field_value(cls, field: str, txn: Transaction, account_name: str) -> Any:
        field = field.lower().strip()
        if field in ('import_source', 'bank_action'):
            return (txn.extra or {}).get(field, '')
        if field in ("merchant", "merchant_name", "description", "name", "narration"):
            return txn.narration or ""
        elif field == "amount":
            return txn.amount
        elif field == "account":
            return account_name
        elif field == "notes":
            return txn.notes or ""
        elif field in ("category", "category_id"):
            return str(txn.category_id) if txn.category_id else ""
        elif field == "type":
            return txn.transaction_type or ""
        return getattr(txn, field, "")

    @classmethod
    def _match_condition(cls, actual: Any, op: str, expected: Any) -> bool:
        # 空值判断
        if op == "is_empty":
            return not actual or str(actual).strip() == ""
        if op == "is_not_empty":
            return bool(actual) and str(actual).strip() != ""

        # 数值类型比较
        if isinstance(actual, (Decimal, int, float)) and expected is not None:
            if op == "between" and isinstance(expected, (list, tuple)) and len(expected) == 2:
                try:
                    low, high = Decimal(str(expected[0])), Decimal(str(expected[1]))
                    act_num = Decimal(str(actual))
                    return low <= act_num <= high
                except (ValueError, TypeError, InvalidOperation):
                    return False
            try:
                exp_num = Decimal(str(expected))
                act_num = Decimal(str(actual))
                if op == ">":
                    return act_num > exp_num
                elif op in (">=", "gte"):
                    return act_num >= exp_num
                elif op == "<":
                    return act_num < exp_num
                elif op in ("<=", "lte"):
                    return act_num <= exp_num
                elif op in ("==", "equals"):
                    return act_num == exp_num
                elif op in ("!=", "not_equals"):
                    return act_num != exp_num
            except (ValueError, TypeError, InvalidOperation):
                return False

        # 文本类型比较
        act_str = str(actual or "")
        exp_str = str(expected or "")

        if op in ("equals", "=="):
            return act_str.casefold() == exp_str.casefold()
        elif op in ("not_equals", "!="):
            return act_str.casefold() != exp_str.casefold()
        elif op == "contains":
            return exp_str.casefold() in act_str.casefold()
        elif op == "not_contains":
            return exp_str.casefold() not in act_str.casefold()
        elif op == "starts_with":
            return act_str.casefold().startswith(exp_str.casefold())
        elif op == "ends_with":
            return act_str.casefold().endswith(exp_str.casefold())
        elif op == "regex":
            try:
                if len(exp_str) > 512 or len(act_str) > 4096:
                    return False
                return bool(_compiled_regex(exp_str).search(act_str, timeout=0.02))
            except (re.error, TimeoutError):
                return False
        elif op == "in" and isinstance(expected, (list, tuple)):
            exp_set = {str(item).casefold() for item in expected}
            return act_str.casefold() in exp_set
        elif op == "not_in" and isinstance(expected, (list, tuple)):
            exp_set = {str(item).casefold() for item in expected}
            return act_str.casefold() not in exp_set

        return False

"""Specification + Composite Condition Evaluator for FamLedger Rules Engine."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, List, Optional
from models import Transaction


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
        operator = condition.get("operator", "AND").upper()

        if operator in ("AND", "OR", "NOT"):
            sub_rules = condition.get("rules", [])
            if operator == "AND":
                return all(cls.evaluate(sub, txn, account_name) for sub in sub_rules)
            elif operator == "OR":
                return any(cls.evaluate(sub, txn, account_name) for sub in sub_rules)
            elif operator == "NOT":
                return not any(cls.evaluate(sub, txn, account_name) for sub in sub_rules)

        # 基础条件评估
        field = condition.get("field", "")
        op = condition.get("operator", "equals").lower()
        expected = condition.get("value")

        actual_val = cls._get_field_value(field, txn, account_name)
        return cls._match_condition(actual_val, op, expected)

    @classmethod
    def _get_field_value(cls, field: str, txn: Transaction, account_name: str) -> Any:
        field = field.lower().strip()
        if field in ("merchant", "merchant_name"):
            return txn.merchant_name or txn.name or ""
        elif field in ("description", "name"):
            return txn.name or ""
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
                except (ValueError, TypeError):
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
            except (ValueError, TypeError):
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
                return bool(re.search(exp_str, act_str, flags=re.IGNORECASE))
            except re.error:
                return False
        elif op == "in" and isinstance(expected, (list, tuple)):
            exp_set = {str(item).casefold() for item in expected}
            return act_str.casefold() in exp_set
        elif op == "not_in" and isinstance(expected, (list, tuple)):
            exp_set = {str(item).casefold() for item in expected}
            return act_str.casefold() not in exp_set

        return False

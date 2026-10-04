"""Pipeline Orchestrator for FamLedger Rules Engine."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from models import Rule, Transaction
from services.rules.evaluator import ConditionEvaluator
from services.rules.actions import ActionExecutor

logger = logging.getLogger(__name__)


class RulePipeline:
    """按优先级顺序评估规则流水线，执行动作并支持阻断与 Dry-Run 预演。"""

    def __init__(self, rules: List[Rule], session=None):
        self.session = session
        # 按 priority 升序排序（数值越小优先级越高）
        self.rules = sorted(
            [r for r in rules if r.is_active],
            key=lambda r: r.priority
        )

    def process_transaction(
        self,
        txn: Transaction,
        account_name: str = "",
        dry_run: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        对单笔交易应用整条规则流水线。
        返回触发命中的规则及其带来的变更差异集。
        """
        # Evaluate cascading rules against a detached working copy in previews.
        if dry_run:
            txn = Transaction.model_validate(txn.model_dump())
        matched_records: List[Dict[str, Any]] = []

        for rule in self.rules:
            is_matched = ConditionEvaluator.evaluate(rule.conditions, txn, account_name)
            if is_matched:
                changes = ActionExecutor.apply_actions(rule.actions, txn, dry_run=False, session=self.session)
                matched_records.append({
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "priority": rule.priority,
                    "changes": changes,
                    "stopped_pipeline": rule.stop_processing,
                })
                logger.debug("交易 %s 命中规则 [%s](优先级 %s), 产生变更: %s", txn.id, rule.name, rule.priority, changes)

                if rule.stop_processing:
                    logger.debug("规则 [%s] 触发 stop_processing，流水线终止", rule.name)
                    break

        return matched_records

    def dry_run_batch(
        self,
        transactions: List[Transaction],
        account_names_map: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        批量模拟预演：评估如果上线新规则，将影响历史上的哪些交易以及具体的变动前后对比。
        完全在内存中运行，不产生任何数据库提交。
        """
        affected: List[Dict[str, Any]] = []
        total_eval = len(transactions)

        for txn in transactions:
            acc_name = account_names_map.get(str(txn.account_id), "")
            # 记录初始快照
            orig_snapshot = {
                "id": str(txn.id),
                "narration": txn.narration,
                "category_id": str(txn.category_id) if txn.category_id else None,
                "transaction_type": txn.transaction_type,
                "notes": txn.notes,
                "amount": str(txn.amount),
                "transacted_at": txn.transacted_at.isoformat(),
            }

            matches = self.process_transaction(txn, account_name=acc_name, dry_run=True)
            has_effective_changes = any(bool(m.get("changes")) for m in matches)

            if has_effective_changes:
                affected.append({
                    "transaction": orig_snapshot,
                    "matched_rules": matches,
                })

        return {
            "total_evaluated": total_eval,
            "total_affected": len(affected),
            "affected_transactions": affected,
        }

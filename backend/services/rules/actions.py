"""Command Pattern Action Executors for FamLedger Rules Pipeline."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from models import Transaction


class ActionExecutor:
    """执行规则动作。严格遵循 manual > rule > import 溯源防护原则。"""

    @classmethod
    def apply_actions(
        cls,
        actions: List[Dict[str, Any]],
        txn: Transaction,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        对交易执行动作列表。
        返回动作所产生的字段修改记录变更集（diff）。
        """
        changes: Dict[str, Any] = {}

        for act in actions:
            action_type = act.get("type", "").lower()
            val = act.get("value")

            if action_type == "set_category":
                # 防护：若用户已手动指定过分类，规则不得静默覆盖
                if getattr(txn, "category_source", "import") != "manual":
                    try:
                        cat_uuid = uuid.UUID(str(val)) if val else None
                        if txn.category_id != cat_uuid:
                            changes["category_id"] = {"old": str(txn.category_id) if txn.category_id else None, "new": str(cat_uuid) if cat_uuid else None}
                            if not dry_run:
                                txn.category_id = cat_uuid
                                txn.category_source = "rule"
                    except (ValueError, TypeError):
                        pass

            elif action_type == "set_merchant":
                if getattr(txn, "merchant_source", "import") != "manual":
                    new_merchant = str(val or "").strip()
                    if txn.merchant_name != new_merchant:
                        changes["merchant_name"] = {"old": txn.merchant_name, "new": new_merchant}
                        if not dry_run:
                            txn.merchant_name = new_merchant
                            txn.merchant_source = "rule"

            elif action_type == "set_transaction_type":
                new_type = str(val or "").strip().lower()
                if new_type in ("expense", "income", "transfer", "refund", "adjustment") and txn.transaction_type != new_type:
                    changes["transaction_type"] = {"old": txn.transaction_type, "new": new_type}
                    if not dry_run:
                        txn.transaction_type = new_type

            elif action_type == "exclude_from_statistics":
                exclude_bool = bool(val)
                if txn.excluded_from_stats != exclude_bool:
                    changes["excluded_from_stats"] = {"old": txn.excluded_from_stats, "new": exclude_bool}
                    if not dry_run:
                        txn.excluded_from_stats = exclude_bool

            elif action_type == "set_note":
                note_mode = act.get("mode", "overwrite") # overwrite | append | prepend
                old_note = txn.notes or ""
                new_text = str(val or "")
                if note_mode == "append":
                    target_note = f"{old_note} {new_text}".strip()
                elif note_mode == "prepend":
                    target_note = f"{new_text} {old_note}".strip()
                else:
                    target_note = new_text

                if old_note != target_note:
                    changes["notes"] = {"old": old_note, "new": target_note}
                    if not dry_run:
                        txn.notes = target_note

            elif action_type == "add_tag":
                tag = str(val or "").strip()
                current_tags = list(getattr(txn, "tags", []) or [])
                if tag and tag not in current_tags:
                    updated_tags = current_tags + [tag]
                    changes["tags"] = {"old": current_tags, "new": updated_tags}
                    if not dry_run:
                        txn.tags = updated_tags

        return changes

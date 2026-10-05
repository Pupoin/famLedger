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
        session=None,
        category_resolver=None,
    ) -> Dict[str, Any]:
        """
        对交易执行动作列表。
        返回动作所产生的字段修改记录变更集（diff）。
        """
        changes: Dict[str, Any] = {}

        for act in actions:
            action_type = act.get("type", "").lower()
            val = act.get("value", act.get("target_value"))
            if val is None:
                continue

            if action_type == "set_category":
                # 防护：若用户已手动指定过分类，规则不得静默覆盖
                if getattr(txn, "category_source", "import") != "manual":
                    try:
                        if category_resolver is not None:
                            cat_uuid = category_resolver(val)
                        elif session is not None:
                            from models import Account
                            from .categories import resolve_category
                            account = session.get(Account, txn.account_id)
                            if not account:
                                continue
                            cat_uuid = resolve_category(session, val, account.family_id)
                        else:
                            cat_uuid = uuid.UUID(str(val)) if val else None
                        if txn.category_id != cat_uuid:
                            changes["category_id"] = {"old": str(txn.category_id) if txn.category_id else None, "new": str(cat_uuid) if cat_uuid else None}
                            if not dry_run:
                                txn.category_id = cat_uuid
                        if not dry_run:
                            if txn.category_source != 'rule':
                                changes['category_source'] = {'old': txn.category_source, 'new': 'rule'}
                            txn.category_source = "rule"
                    except (ValueError, TypeError):
                        pass

            elif action_type in ("set_merchant", "set_narration", "set_description"):
                if getattr(txn, "merchant_source", "import") != "manual":
                    new_val = str(val or "").strip()
                    if txn.narration != new_val:
                        changes["narration"] = {"old": txn.narration, "new": new_val}
                        if not dry_run:
                            txn.narration = new_val
                            txn.merchant_source = "rule"

            elif action_type == "set_transaction_type":
                if (txn.extra or {}).get('transaction_type_source') == 'manual':
                    continue
                if txn.transfer_id or txn.refund_of_transaction_id or txn.is_split:
                    continue
                if session is not None:
                    from models import RefundAllocation
                    from sqlmodel import select
                    linked = session.exec(select(RefundAllocation).where(
                        (RefundAllocation.refund_transaction_id == txn.id) |
                        (RefundAllocation.original_transaction_id == txn.id))).first()
                    if linked:
                        continue
                new_type = str(val or "").strip().lower()
                if new_type in ("expense", "income", "transfer", "refund") and txn.transaction_type != new_type:
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

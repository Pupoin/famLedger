"""Rules Engine REST API and Dry-Run Simulation Endpoints."""

from __future__ import annotations

from services.transaction_lock import lock_mutation

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select, desc

from database import get_session
from models import Account, Family, Rule, Transaction, User
from auth import get_current_user_or_token
from services.rules.pipeline import RulePipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/rules", tags=["Rules Engine"])


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = None
    priority: int = 100
    stop_processing: bool = False
    is_active: bool = True
    conditions: Dict[str, Any] = Field(description="Composite condition tree (AND/OR/NOT, rules)")
    actions: List[Dict[str, Any]] = Field(description="Action commands (set_category, set_merchant, etc.)")


class RuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    description: Optional[str] = None
    priority: Optional[int] = None
    stop_processing: Optional[bool] = None
    is_active: Optional[bool] = None
    conditions: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None


class RuleReorderItem(BaseModel):
    id: uuid.UUID
    priority: int


class DryRunPayload(BaseModel):
    rule: Optional[RuleCreate] = Field(default=None, description="Draft rule to test; if null, tests current active rules")
    limit: int = Field(default=100, ge=1, le=1000)
    account_id: Optional[uuid.UUID] = None


def _resolve_user_family_id(session: Session, user_or_ctx: Any) -> Optional[uuid.UUID]:
    from services.principals import resolve_family_id
    return resolve_family_id(session, user_or_ctx)

@router.get("")
@router.get("/")
def list_rules(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取所有已配置的自动化规则（按 priority 升序排序）。"""
    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        return {"rules": [], "count": 0}

    rules = session.exec(
        select(Rule).where(Rule.family_id == family_id).order_by(Rule.priority)
    ).all()

    items = []
    for r in rules:
        items.append({
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "priority": r.priority,
            "stop_processing": r.stop_processing,
            "is_active": r.is_active,
            "conditions": r.conditions,
            "actions": r.actions,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"rules": items, "count": len(items)}


def _require_admin_or_owner(session: Session, user_or_ctx: Any):
    from models import User
    if isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"):
        return
    u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    if not u or u.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="仅家庭组管理者或系统管理员有权配置或修改规则")


def _validate_rule_actions(session: Session, actions: Any, family_id: Optional[uuid.UUID]):
    if not isinstance(actions, list):
        raise HTTPException(status_code=400, detail="actions 必须为动作列表")
    from services.rules.categories import resolve_category
    allowed = {"set_category", "set_merchant", "set_narration", "set_description",
               "set_transaction_type", "exclude_from_statistics", "set_note", "add_tag"}
    for act in actions:
        if not isinstance(act, dict) or act.get("type") not in allowed:
            raise HTTPException(status_code=400, detail="无效的规则动作")
        if "value" not in act and "target_value" in act:
            act["value"] = act.pop("target_value")
        val = act.get("value")
        if val is None or (isinstance(val, str) and not val.strip()):
            raise HTTPException(status_code=400, detail="规则动作缺少 value")
        if act["type"] == "set_category":
            try:
                act["value"] = str(resolve_category(session, val, family_id, create=True))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if act["type"] == "exclude_from_statistics" and not isinstance(val, bool):
            raise HTTPException(status_code=400, detail="统计排除动作必须使用布尔值")
        if act["type"] == "set_transaction_type" and val not in ("expense", "income", "transfer", "refund"):
            raise HTTPException(status_code=400, detail="无效的交易类型")


@router.post("")
@router.post("/")
def create_rule(
    data: RuleCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """创建新自动化清洗与分类规则。"""
    lock_mutation(session)
    _require_admin_or_owner(session, user_or_ctx)
    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        raise HTTPException(status_code=400, detail="您尚未加入家庭组，无法创建家庭规则")

    from services.rules.evaluator import ConditionEvaluator
    try:
        ConditionEvaluator.validate(data.conditions)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    _validate_rule_actions(session, data.actions, family_id)

    rule = Rule(
        family_id=family_id,
        name=data.name,
        description=data.description,
        priority=data.priority,
        stop_processing=data.stop_processing,
        is_active=data.is_active,
        conditions=data.conditions,
        actions=data.actions,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)

    return {
        "id": str(rule.id),
        "name": rule.name,
        "priority": rule.priority,
        "is_active": rule.is_active,
    }


@router.put("/reorder")
def reorder_rules(
    items: List[RuleReorderItem],
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """批量调整规则优先级（支持前端拖拽排序后一键持久化）。"""
    lock_mutation(session)
    _require_admin_or_owner(session, user_or_ctx)
    family_id = _resolve_user_family_id(session, user_or_ctx)
    for item in items:
        rule = session.get(Rule, item.id)
        if rule and rule.family_id == family_id:
            rule.priority = item.priority
            session.add(rule)
    session.commit()
    return {"status": "ok", "updated_count": len(items)}


@router.put("/{rule_id}")
@router.patch("/{rule_id}")
def update_rule(
    rule_id: uuid.UUID,
    data: RuleUpdate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """更新指定规则信息或启用状态。"""
    lock_mutation(session)
    _require_admin_or_owner(session, user_or_ctx)
    family_id = _resolve_user_family_id(session, user_or_ctx)
    from models import User
    u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    is_admin = (u and u.role == "admin") or (isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"))
    rule = session.get(Rule, rule_id)
    if not rule or (not is_admin and rule.family_id != family_id):
        raise HTTPException(status_code=404, detail="Rule not found")

    if "conditions" in data.model_fields_set:
        from services.rules.evaluator import ConditionEvaluator
        try:
            ConditionEvaluator.validate(data.conditions)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    if "actions" in data.model_fields_set:
        if data.actions is None:
            raise HTTPException(422, "actions 不能为 null")
        _validate_rule_actions(session, data.actions, family_id)

    update_dict = data.model_dump(exclude_unset=True)
    for k, v in update_dict.items():
        setattr(rule, k, v)

    session.add(rule)
    session.commit()
    session.refresh(rule)
    return {
        "id": str(rule.id),
        "name": rule.name,
        "priority": rule.priority,
        "is_active": rule.is_active,
    }


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """删除指定自动化规则。"""
    lock_mutation(session)
    _require_admin_or_owner(session, user_or_ctx)
    family_id = _resolve_user_family_id(session, user_or_ctx)
    from models import User
    u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) else None
    is_admin = (u and u.role == "admin") or (isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"))
    rule = session.get(Rule, rule_id)
    if not rule or (not is_admin and rule.family_id != family_id):
        raise HTTPException(status_code=404, detail="Rule not found")

    session.delete(rule)
    session.commit()
    return {"status": "ok", "deleted_id": str(rule_id)}


@router.post("/dry-run")
def dry_run_rules(
    payload: DryRunPayload,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    Dry-Run 规则预演模拟：
    无需落库，在历史流水样本上评估命中情况与字段变更集。
    """
    lock_mutation(session)
    _require_admin_or_owner(session, user_or_ctx)
    family_id = _resolve_user_family_id(session, user_or_ctx)

    # 1. 准备要评估的规则列表
    if payload.rule:
        from services.rules.evaluator import ConditionEvaluator
        try:
            ConditionEvaluator.validate(payload.rule.conditions)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        _validate_rule_actions(session, payload.rule.actions, family_id)
        test_rule = Rule(
            family_id=family_id,
            name=payload.rule.name,
            description=payload.rule.description,
            priority=payload.rule.priority,
            stop_processing=payload.rule.stop_processing,
            is_active=payload.rule.is_active,
            conditions=payload.rule.conditions,
            actions=payload.rule.actions,
        )
        rules_to_eval = [test_rule]
    else:
        rules_to_eval = session.exec(
            select(Rule).where(Rule.family_id == family_id).order_by(Rule.priority)
        ).all()

    # 2. 采样历史流水（严格限于当前用户有权限查阅的账户）
    from services.stats_engine import get_user_visible_account_ids
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first() if (isinstance(user_or_ctx, str) and not is_service) else None
    visible_acc_ids = get_user_visible_account_ids(session, user_or_ctx if is_service else curr_user, family_id=family_id)

    accounts = session.exec(select(Account).where(Account.id.in_(visible_acc_ids))).all() if visible_acc_ids else []
    acc_map = {str(a.id): a.name for a in accounts}
    family_acc_ids = list(acc_map.keys())

    stmt = select(Transaction)
    if payload.account_id:
        if str(payload.account_id) not in family_acc_ids:
            return {"total_evaluated": 0, "matched_count": 0, "results": []}
        stmt = stmt.where(Transaction.account_id == payload.account_id)
    else:
        if family_acc_ids:
            stmt = stmt.where(Transaction.account_id.in_([uuid.UUID(aid) for aid in family_acc_ids]))
        else:
            return {"total_evaluated": 0, "matched_count": 0, "results": []}

    stmt = stmt.order_by(desc(Transaction.transacted_at), desc(Transaction.id)).limit(payload.limit)
    txns = session.exec(stmt).all()

    # 3. 执行内存模拟
    pipeline = RulePipeline(rules_to_eval, session=session)
    result = pipeline.dry_run_batch(txns, acc_map)

    return result


@router.post("/apply-retroactive")
def apply_all_rules_retroactively(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """批量回溯：将当前家庭所有已启用的规则应用到历史流水（仅限当前用户具备写权限的账户）。"""
    lock_mutation(session)
    _require_admin_or_owner(session, user_or_ctx)
    family_id = _resolve_user_family_id(session, user_or_ctx)
    rules = session.exec(
        select(Rule).where(Rule.family_id == family_id, Rule.is_active == True).order_by(Rule.priority)
    ).all()
    if not rules:
        return {"status": "ok", "modified_count": 0}

    from services.stats_engine import get_user_writable_account_ids
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first() if (isinstance(user_or_ctx, str) and not is_service) else None
    writable_acc_ids = get_user_writable_account_ids(session, user_or_ctx if is_service else curr_user, family_id=family_id)
    if not writable_acc_ids:
        return {"status": "ok", "modified_count": 0}

    accounts = session.exec(select(Account).where(Account.id.in_(writable_acc_ids))).all()
    acc_map = {str(a.id): a.name for a in accounts}

    txns = session.exec(
        select(Transaction).where(Transaction.account_id.in_(writable_acc_ids))
    ).all()
    pipeline = RulePipeline(rules, session=session)

    modified_count = 0
    for txn in txns:
        acc_name = acc_map.get(str(txn.account_id), "")
        matches = pipeline.process_transaction(txn, account_name=acc_name, dry_run=False)
        if any(bool(m.get("changes")) for m in matches):
            session.add(txn)
            modified_count += 1

    session.commit()
    logger.info("全量规则历史回溯完成，更新流水数: %s", modified_count)
    return {"status": "ok", "modified_count": modified_count}


@router.post("/{rule_id}/apply")
def apply_rule_retroactively(
    rule_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """回溯历史：将指定规则立即应用到所有历史流水中（仅限当前用户具备写权限的账户）。"""
    lock_mutation(session)
    _require_admin_or_owner(session, user_or_ctx)
    family_id = _resolve_user_family_id(session, user_or_ctx)
    rule = session.get(Rule, rule_id)
    if not rule or rule.family_id != family_id:
        raise HTTPException(status_code=404, detail="Rule not found")

    from services.stats_engine import get_user_writable_account_ids
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first() if (isinstance(user_or_ctx, str) and not is_service) else None
    writable_acc_ids = get_user_writable_account_ids(session, user_or_ctx if is_service else curr_user, family_id=family_id)
    if not writable_acc_ids:
        return {"status": "ok", "modified_count": 0}

    accounts = session.exec(select(Account).where(Account.id.in_(writable_acc_ids))).all()
    acc_map = {str(a.id): a.name for a in accounts}

    txns = session.exec(
        select(Transaction).where(Transaction.account_id.in_(writable_acc_ids))
    ).all()
    pipeline = RulePipeline([rule], session=session)

    modified_count = 0
    for txn in txns:
        acc_name = acc_map.get(str(txn.account_id), "")
        matches = pipeline.process_transaction(txn, account_name=acc_name, dry_run=False)
        if any(bool(m.get("changes")) for m in matches):
            session.add(txn)
            modified_count += 1

    session.commit()
    logger.info("规则 [%s] 历史回溯完成，更新流水数: %s", rule.name, modified_count)
    return {"status": "ok", "modified_count": modified_count}

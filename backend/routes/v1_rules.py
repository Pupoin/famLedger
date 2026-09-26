"""Rules Engine REST API and Dry-Run Simulation Endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select, desc

from database import get_session
from models import Account, Family, Rule, Transaction
from auth import get_current_user_or_token
from services.rules.pipeline import RulePipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/rules", tags=["Rules Engine"])


class RuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    priority: int = 100
    stop_processing: bool = False
    is_active: bool = True
    conditions: Dict[str, Any] = Field(description="Composite condition tree (AND/OR/NOT, rules)")
    actions: List[Dict[str, Any]] = Field(description="Action commands (set_category, set_merchant, etc.)")


class RuleUpdate(BaseModel):
    name: Optional[str] = None
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


@router.get("")
@router.get("/")
def list_rules(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取所有已配置的自动化规则（按 priority 升序排序）。"""
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    rules = session.exec(
        select(Rule).where(Rule.family_id == family.id).order_by(Rule.priority)
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


@router.post("")
@router.post("/")
def create_rule(
    data: RuleCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """创建新自动化清洗与分类规则。"""
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    rule = Rule(
        family_id=family.id,
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
    for item in items:
        rule = session.get(Rule, item.id)
        if rule:
            rule.priority = item.priority
            session.add(rule)
    session.commit()
    return {"status": "ok", "updated_count": len(items)}


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
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    # 1. 准备要评估的规则列表
    if payload.rule:
        test_rule = Rule(
            family_id=family.id,
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
            select(Rule).where(Rule.family_id == family.id).order_by(Rule.priority)
        ).all()

    # 2. 采样历史流水
    stmt = select(Transaction)
    if payload.account_id:
        stmt = stmt.where(Transaction.account_id == payload.account_id)
    stmt = stmt.order_by(desc(Transaction.transacted_at), desc(Transaction.id)).limit(payload.limit)
    txns = session.exec(stmt).all()

    # 3. 账户名称字典
    accounts = session.exec(select(Account).where(Account.family_id == family.id)).all()
    acc_map = {str(a.id): a.name for a in accounts}

    # 4. 执行内存模拟
    pipeline = RulePipeline(rules_to_eval)
    result = pipeline.dry_run_batch(txns, acc_map)

    return result


@router.post("/{rule_id}/apply")
def apply_rule_retroactively(
    rule_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """回溯历史：将指定规则立即应用到所有历史流水中（不覆盖手动修改的字段）。"""
    rule = session.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    family_id = rule.family_id
    accounts = session.exec(select(Account).where(Account.family_id == family_id)).all()
    acc_map = {str(a.id): a.name for a in accounts}

    # 获取所有流水进行批量回溯处理
    txns = session.exec(select(Transaction)).all()
    pipeline = RulePipeline([rule])

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

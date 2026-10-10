"""Scheduled transfers and staged loan repayment plans."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlmodel import Session, select

from auth import get_current_user
from database import get_session
from models import Account, Loan, ScheduledPlan, ScheduledOccurrence, Transaction
from services.request_validation import CurrencyCode
from services.schedule_math import LoanConfig, check_timezone, interest_for, rounded, active_rate, next_rate_change, occurrence_date, scheduled_date, repayment_phase
from services.schedules import actor_for, authorized, projection, records_for, occurrence, post, undo, balance, booking_plan, pending_for_plan, PAID
from services.transaction_lock import lock_mutation

router = APIRouter(prefix='/v1/plans', tags=['Scheduled payments'])


class PlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['transfer', 'loan']
    account_id: uuid.UUID
    destination_id: uuid.UUID
    amount: Decimal = Field(default=0, ge=0, max_digits=19, decimal_places=4)
    currency: CurrencyCode
    start_date: date
    end_date: date | None = None
    frequency: Literal['weekly', 'monthly', 'quarterly', 'yearly'] = 'monthly'
    interval: int = Field(default=1, ge=1, le=120)
    occurrence_limit: int = Field(default=120, ge=1, le=1200)
    timezone_name: str = 'UTC'
    execution_mode: Literal['auto', 'confirm'] = 'confirm'
    loan: LoanConfig | None = None

    _timezone = field_validator('timezone_name')(check_timezone)

    @model_validator(mode='after')
    def valid_dates(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('计划名称不能为空')
        if self.account_id == self.destination_id:
            raise ValueError('转出和转入账户不能相同')
        if self.end_date and self.end_date < self.start_date:
            raise ValueError('结束日期不能早于开始日期')
        if self.kind == 'transfer' and (self.amount <= 0 or self.loan):
            raise ValueError('定期转账必须有正数金额且不能携带贷款配置')
        if self.kind == 'loan':
            if not self.loan or self.frequency != 'monthly' or self.interval != 1:
                raise ValueError('贷款必须配置按月还款计划')
            if self.loan.interest_start_date >= self.start_date:
                raise ValueError('计息开始日期必须早于首次还款日')
            self.occurrence_limit = self.loan.term_months
            if self.end_date:
                raise ValueError('贷款结束日期由期限决定')
        if self.start_date.year < 1900:
            raise ValueError('计划开始日期不能早于1900年')
        try:
            scheduled_date(self, self.occurrence_limit)
        except (ValueError, OverflowError) as error:
            raise ValueError('计划日期超出支持范围') from error
        return self


class ActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['post', 'skip', 'undo', 'link']
    transaction_id: uuid.UUID | None = None
    payment_date: date | None = None
    bank_amount: Decimal | None = Field(default=None, gt=0, max_digits=19, decimal_places=4)


class StateInput(BaseModel):
    status: Literal['active', 'paused', 'cancelled']


class PrepayInput(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    payment_date: date
    strategy: Literal['reduce_payment', 'reduce_term', 'keep_schedule']
    bank_amount: Decimal | None = Field(default=None, gt=0, max_digits=19, decimal_places=4)


def get_plan(session, username, plan_id, write=False):
    actor = actor_for(session, username)
    plan = session.get(ScheduledPlan, plan_id)
    if not plan:
        raise HTTPException(404, '计划不存在')
    authorized(session, actor, plan, write)
    return actor, plan


def validate_accounts(session, actor, body):
    from routes.v1_transactions import _verify_account_write_permission, _verify_account_transfer_in_permission
    from routes.v1_accounts import _verify_account_management_permission
    for key in [body.account_id, body.destination_id]:
        account = session.get(Account, key)
        if not account or account.family_id != actor.family_id or not account.is_active:
            raise HTTPException(403, '计划账户必须为当前家庭中有效且可写的账户')
        checker = _verify_account_transfer_in_permission if body.kind == 'transfer' and key == body.destination_id else _verify_account_write_permission
        checker(session, actor.username, key, '创建计划')
    target, source = session.get(Account, body.destination_id), session.get(Account, body.account_id)
    if body.kind == 'loan':
        _verify_account_management_permission(actor, target, '配置贷款', session=session)
        if target.account_type not in {'loan', 'mortgage'} or source.classification != 'asset':
            raise HTTPException(422, '贷款计划需要贷款账户和资产扣款账户')
        if body.currency != target.currency:
            raise HTTPException(422, '贷款计划币种必须与贷款账户一致')
        if target.parent_account_id:
            raise HTTPException(422, '贷款账户不能是副卡')


def construct(actor, body, previous=None, session=None):
    values = body.model_dump(exclude={'loan'})
    values['config'] = {'loan': body.loan.model_dump(mode='json')} if body.loan else {}
    if previous:
        values['config'] = {**previous.config, **values['config']}
        records = records_for(session, previous)
        first = max((n for n, r in records.items() if r.status in PAID | {'skipped', 'undone'}), default=0) + 1
        try:
            regular_next = scheduled_date(previous, first)
        except (ValueError, OverflowError):
            regular_next = previous.start_date
        # The editor submits the next regular date. Keeping that date must not
        # re-anchor a Jan-31 schedule on Feb-29 and move later dates to the 29th.
        anchor_changed = body.start_date != previous.start_date and (not records or body.start_date != regular_next)
        if records and not anchor_changed:
            values['start_date'] = previous.start_date
        versions = previous.config.get('history_versions', [])
        captured = {key for v in versions for key in v['occurrence_ids']}
        uncaptured = [str(r.id) for r in records.values() if r.status in PAID | {'skipped', 'undone'} and str(r.id) not in captured]
        if uncaptured:
            old_terms = previous.model_dump(mode='json')
            old_terms['config'].pop('history_versions', None)
            values['config']['history_versions'] = [*versions, {'occurrence_ids': uncaptured, 'terms': old_terms}]
        if anchor_changed or body.frequency != previous.frequency or body.interval != previous.interval:
            if records:
                try:
                    anchor = body.start_date if anchor_changed else scheduled_date(previous, first)
                except (ValueError, OverflowError) as error:
                    raise HTTPException(422, '计划日期超出支持范围') from error
                if any(r.number > 0 and r.status in PAID | {'skipped', 'undone'} and r.due_date >= anchor for r in records.values()):
                    raise HTTPException(422, '下次执行日期必须晚于已处理期次')
                stages = previous.config.get('recurrence_stages') or [{
                    'from_period': 1, 'start_date': previous.start_date.isoformat(),
                    'frequency': previous.frequency, 'interval': previous.interval}]
                values['config']['recurrence_stages'] = [s for s in stages if s['from_period'] < first] + [{
                    'from_period': first, 'start_date': anchor.isoformat(),
                    'frequency': body.frequency, 'interval': body.interval}]
            else:
                values['config'].pop('recurrence_stages', None)
        if body.loan and body.loan.model_dump(mode='json') != LoanConfig.model_validate(previous.config['loan']).model_dump(mode='json'):
            values['config'].pop('payment_override', None)
        if body.destination_id != previous.destination_id:
            values['accrual_account_id'] = None
        if body.account_id != previous.account_id or body.destination_id != previous.destination_id:
            values['owner_id'] = actor.id
        for key, value in values.items():
            setattr(previous, key, value)
        previous.updated_at = datetime.now(timezone.utc)
        try:
            scheduled_date(previous, previous.occurrence_limit)
        except (ValueError, OverflowError) as error:
            raise HTTPException(422, '计划日期超出支持范围') from error
        return previous
    return ScheduledPlan(family_id=actor.family_id, owner_id=actor.id, **values)


def serialize(session, actor, plan, detailed=False):
    future = projection(session, plan)
    upcoming = next((r for r in future if pending_for_plan(plan, r)), None)
    can_manage = True
    try:
        authorized(session, actor, plan, True)
    except HTTPException:
        can_manage = False
    source, destination = session.get(Account, plan.account_id), session.get(Account, plan.destination_id)
    from routes.v1_transactions import _verify_account_write_permission
    can_undo = can_manage
    if can_undo:
        try:
            _verify_account_write_permission(session, actor.username, destination.id, '撤销计划流水')
        except HTTPException:
            can_undo = False
    result = plan.model_dump(mode='json') | {
        'config': {key: value for key, value in plan.config.items() if key != 'history_versions'},
        'account_name': source.name, 'destination_name': destination.name,
        'can_manage': can_manage, 'can_undo': can_undo, 'next': upcoming,
        'loan_balance': str(balance(session, destination)) if plan.kind == 'loan' else None,
        'pause_reason': plan.config.get('pause_reason'),
    }
    records = records_for(session, plan)
    first = max((n for n, r in records.items() if r.status in PAID | {'skipped', 'undone'}), default=0) + 1
    result['edit_from_period'] = first
    try:
        result['edit_start_date'] = scheduled_date(plan, first).isoformat()
    except (ValueError, OverflowError):
        result['edit_start_date'] = plan.start_date.isoformat()
    if plan.kind == 'loan':
        config = LoanConfig.model_validate(plan.config['loan'])
        final_row = records.get(plan.occurrence_limit)
        result['final_payment_processed'] = bool(final_row and final_row.status in PAID | {'skipped', 'undone'})
        final_date = final_row.due_date if result['final_payment_processed'] else occurrence_date(plan, plan.occurrence_limit)
        result['final_payment_date'] = final_date.isoformat()
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo(plan.timezone_name)).date()
        result['current_rate'] = str(active_rate(config, max(today, config.interest_start_date)))
        result['next_rate_change'] = next_rate_change(config, today)
        result['unpaid_interest'] = str(balance(session, session.get(Account, plan.accrual_account_id))) if plan.accrual_account_id else '0'
        all_paid = [r for r in records.values() if r.status in PAID]
        result['paid_totals_by_currency'] = {
            code: {name: str(sum((Decimal(r.snapshot.get(name, '0')) for r in all_paid if booking_plan(plan, r).currency == code), Decimal(0)))
                   for name in ['principal', 'interest', 'fee']}
            for code in {booking_plan(plan, r).currency for r in all_paid}}
        paid = [r for r in all_paid if booking_plan(plan, r).currency == plan.currency]
        result['paid_totals'] = {name: str(sum((Decimal(r.snapshot.get(name,'0')) for r in paid), Decimal(0))) for name in ['principal','interest','fee']}
    if detailed:
        extra = [r.model_dump(mode='json') | {'currency': booking_plan(plan, r).currency}
                 for n, r in records.items() if n < 1]
        result['occurrences'] = future
        result['prepayments'] = extra
    return result


@router.get('')
def list_plans(account_id: uuid.UUID | None = None, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    actor = actor_for(session, username)
    from services.stats_engine import get_user_visible_account_ids
    visible = get_user_visible_account_ids(session, actor, actor.family_id)
    query = select(ScheduledPlan).where(ScheduledPlan.family_id == actor.family_id,
        ScheduledPlan.account_id.in_(visible), ScheduledPlan.destination_id.in_(visible))
    if account_id:
        query = query.where((ScheduledPlan.account_id == account_id) | (ScheduledPlan.destination_id == account_id))
    plans = session.exec(query.order_by(ScheduledPlan.created_at.desc()).limit(500)).all()
    items = []
    for plan in plans:
        try:
            authorized(session, actor, plan)
        except HTTPException:
            continue
        items.append(serialize(session, actor, plan))
    return {'items': items}


@router.post('/preview')
def preview(body: PlanInput, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    actor = actor_for(session, username)
    validate_accounts(session, actor, body)
    return {'occurrences': projection(session, construct(actor, body))}


@router.post('')
def create(body: PlanInput, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    lock_mutation(session)
    actor = actor_for(session, username)
    validate_accounts(session, actor, body)
    if body.kind == 'loan':
        existing = session.exec(select(ScheduledPlan).where(ScheduledPlan.kind == 'loan',
            ScheduledPlan.destination_id == body.destination_id, ScheduledPlan.status != 'cancelled')).first()
        if existing:
            raise HTTPException(409, '该贷款已有还款计划，请编辑现有计划')
    plan = construct(actor, body)
    projection(session, plan)  # Reject unpayable configurations before writing.
    if body.kind == 'loan':
        loan = session.exec(select(Loan).where(Loan.account_id == body.destination_id)).first()
        if not loan:
            loan = Loan(account_id=body.destination_id, original_amount=max(Decimal(0), balance(session, session.get(Account, body.destination_id))),
                        term_months=body.loan.term_months, interest_rate=body.loan.rates[0].annual_rate,
                        repayment_method=body.loan.phases[0].method, start_date=body.loan.interest_start_date)
            session.add(loan)
    session.add(plan)
    session.commit()
    return serialize(session, actor, plan, True)


@router.get('/{plan_id}')
def detail(plan_id: uuid.UUID, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    actor, plan = get_plan(session, username, plan_id)
    return serialize(session, actor, plan, True)


@router.put('/{plan_id}')
def update(plan_id: uuid.UUID, body: PlanInput, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    lock_mutation(session)
    actor, plan = get_plan(session, username, plan_id, True)
    validate_accounts(session, actor, body)
    validate_update(session, plan, body)
    plan = construct(actor, body, plan, session)
    projection(session, plan)
    if body.loan and not session.exec(select(Loan).where(Loan.account_id == body.destination_id)).first():
        session.add(Loan(account_id=body.destination_id, original_amount=max(Decimal(0), balance(session, session.get(Account, body.destination_id))),
                         term_months=body.loan.term_months, interest_rate=body.loan.rates[0].annual_rate,
                         repayment_method=body.loan.phases[0].method, start_date=body.loan.interest_start_date))
    for row in records_for(session, plan).values():
        if row.number > 0 and row.status not in PAID | {'skipped', 'undone'}:
            due = occurrence_date(plan, row.number)
            row.due_date, row.account_id = due, plan.account_id
            row.status, row.snapshot, row.last_error, row.retry_after = 'planned', {}, None, None
            session.add(row)
    session.add(plan)
    session.commit()
    return serialize(session, actor, plan, True)


def validate_update(session, plan, body):
    if plan.kind != body.kind:
        raise HTTPException(409, '计划类型不能修改')
    if body.loan and plan.status != 'cancelled':
        existing = session.exec(select(ScheduledPlan).where(ScheduledPlan.kind == 'loan',
            ScheduledPlan.destination_id == body.destination_id, ScheduledPlan.status != 'cancelled', ScheduledPlan.id != plan.id)).first()
        if existing:
            raise HTTPException(409, '该贷款已有还款计划，请编辑现有计划')
    records = records_for(session, plan)
    fixed = [r for r in records.values() if r.status in PAID | {'skipped', 'undone'}]
    last_number = max((r.number for r in fixed), default=0)
    final_row = records.get(body.occurrence_limit)
    if body.loan and final_row and final_row.status in PAID | {'skipped', 'undone'}:
        previous_final = LoanConfig.model_validate(plan.config['loan'])
        if (body.loan.final_payment_day, body.loan.final_payment_date) != (previous_final.final_payment_day, previous_final.final_payment_date):
            raise HTTPException(409, '最后一期已处理，不能修改最后一期还款日')
    if body.occurrence_limit < last_number:
        raise HTTPException(409, '期限不能短于已经支付的期次')
    if body.end_date and any(r.due_date > body.end_date for r in fixed):
        raise HTTPException(409, '结束日期不能早于已处理期次')


@router.post('/{plan_id}/preview')
def preview_update(plan_id: uuid.UUID, body: PlanInput, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    actor, plan = get_plan(session, username, plan_id, True)
    validate_accounts(session, actor, body)
    validate_update(session, plan, body)
    # Detached copy: future preview reads paid snapshots without flushing any edits.
    draft = ScheduledPlan.model_validate(plan.model_dump())
    construct(actor, body, draft, session)
    return {'occurrences': projection(session, draft)}


@router.patch('/{plan_id}/status')
def state(plan_id: uuid.UUID, body: StateInput, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    lock_mutation(session)
    actor, plan = get_plan(session, username, plan_id, True)
    if plan.status == 'cancelled':
        raise HTTPException(409, '已取消的计划不能恢复')
    plan.status = body.status
    plan.config = {k: v for k, v in plan.config.items() if k != 'pause_reason'}
    session.add(plan)
    session.commit()
    return serialize(session, actor, plan, True)


@router.post('/{plan_id}/occurrences/{number}')
def act(plan_id: uuid.UUID, number: int, body: ActionInput, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    lock_mutation(session)
    actor, plan = get_plan(session, username, plan_id, True)
    if body.action == 'undo':
        undo(session, actor, plan, number)
    elif body.action == 'skip':
        row = occurrence(session, plan, number)
        if row.status in PAID:
            raise HTTPException(409, '已支付期次需要先撤销')
        row.snapshot = next((r for r in projection(session, plan) if r['number'] == number), {})
        row.status = 'skipped'
        session.add(row)
    else:
        linked = session.get(Transaction, body.transaction_id) if body.transaction_id else None
        if body.action == 'link' and linked is None:
            raise HTTPException(404, '银行流水不存在')
        from services.booking_money import PendingExchangeRate
        try:
            post(session, actor, plan, number, body.payment_date, linked, body.bank_amount)
        except PendingExchangeRate as error:
            raise HTTPException(503, '汇率暂不可用，本期尚未入账，请稍后重试') from error
    session.commit()
    return serialize(session, actor, plan, True)


@router.get('/{plan_id}/candidates/{number}')
def candidates(plan_id: uuid.UUID, number: int, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    actor, plan = get_plan(session, username, plan_id, True)
    row = records_for(session, plan).get(number)
    if row:
        plan = booking_plan(plan, row)
        authorized(session, actor, plan, True)
    from datetime import timedelta
    from services.booking_money import money
    item = next((p for p in projection(session, plan) if p['number'] == number), None)
    if not item:
        raise HTTPException(404, '期次不存在')
    when = date.fromisoformat(item['due_date'])
    rows = session.exec(select(Transaction).where(Transaction.account_id == plan.account_id,
        Transaction.transaction_type == 'expense', Transaction.transacted_at >= when - timedelta(days=7),
        Transaction.transacted_at <= when + timedelta(days=7))).all()
    return {'items': [{'id': str(r.id), 'narration': r.narration, 'date': r.transacted_at.isoformat(),
                      'amount': str(r.original_amount or r.amount), 'currency': r.original_currency or r.currency}
                     for r in rows if not (r.extra or {}).get('scheduled_occurrence_id') and not r.transfer_id
                     and (((r.original_currency or r.currency) == plan.currency and money(r.original_amount or r.amount) == money(item['total']))
                          or (r.currency != plan.currency and (r.original_currency or r.currency) == r.currency)
                          or (plan.kind == 'loan' and (plan.config['loan']['day_count'] != 'monthly'
                              or (number == plan.occurrence_limit and (plan.config['loan'].get('final_payment_day') is not None
                                  or plan.config['loan'].get('final_payment_date') is not None)))))]}


@router.post('/{plan_id}/prepay')
def prepay(plan_id: uuid.UUID, body: PrepayInput, session: Session = Depends(get_session), username: str = Depends(get_current_user)):
    lock_mutation(session)
    actor, plan = get_plan(session, username, plan_id, True)
    if plan.kind != 'loan':
        raise HTTPException(422, '仅贷款支持提前还款')
    remaining = max(Decimal(0), balance(session, session.get(Account, plan.destination_id)))
    if body.amount > remaining:
        raise HTTPException(422, '提前还款不能超过剩余本金')
    future = projection(session, plan)
    if any(p['due_date'] <= body.payment_date.isoformat() and p['status'] not in PAID | {'skipped'} for p in future):
        raise HTTPException(409, '请先处理提前还款日前的贷款期次')
    next_payment = next((p for p in future if p['status'] not in PAID | {'skipped'}), None)
    if not next_payment:
        raise HTTPException(409, '贷款已经结清')
    loan = LoanConfig.model_validate(plan.config['loan'])
    phase = repayment_phase(loan, next_payment['number'], date.fromisoformat(next_payment['due_date']))
    if body.strategy == 'reduce_term' and phase.method != 'equal_installment':
        raise HTTPException(422, '缩短期限适用于等额本息阶段，其他阶段请修改后续还款配置')
    if body.strategy == 'reduce_payment' and phase.method not in {'equal_installment', 'equal_principal'}:
        raise HTTPException(422, '固定金额或仅还利息阶段请保持原还款安排或编辑后续阶段')
    # Negative installment numbers identify additional payments without
    # renumbering or overwriting any regular occurrence.
    existing = records_for(session, plan)
    number = min([0, *existing]) - 1
    row = ScheduledOccurrence(plan_id=plan.id, account_id=plan.account_id, number=number, due_date=body.payment_date)
    session.add(row)
    session.flush()
    post(session, actor, plan, number, body.payment_date, bank_amount=body.bank_amount, prepayment=body.amount)
    row.snapshot = {**row.snapshot, 'previous_payment_override': plan.config.get('payment_override')}
    session.add(row)
    config = dict(plan.config)
    if body.strategy != 'keep_schedule':
        config.pop('payment_override', None)
    if body.strategy == 'reduce_term':
        config['payment_override'] = {'rate': next_payment['annual_rate'], 'phase': phase.from_period,
            'amount': str(Decimal(next_payment['principal']) + Decimal(next_payment['interest']))}
    plan.config = config
    session.add(plan)
    session.commit()
    return serialize(session, actor, plan, True)

"""Authorized projections, atomic posting, import reconciliation and due worker."""
import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlmodel import Session, select

from models import Account, Family, Loan, ScheduledPlan, ScheduledOccurrence, ScheduledBankMatch, Transaction, Transfer, User
from services.booking_money import prepare_booking, money, PendingExchangeRate
from services.schedule_math import LoanConfig, add_months, occurrence_date, scheduled_date, scheduled_period_days, installment, rounded, interest_for
from services.transaction_lock import lock_mutation

PAID = {'posted', 'reconciled'}


def booking_plan(plan, row):
    """A processed period keeps the terms under which it was recorded."""
    for version in plan.config.get('history_versions', []):
        if str(row.id) in version['occurrence_ids']:
            values = {**version['terms'], 'family_id': plan.family_id,
                      'owner_id': plan.owner_id, 'status': plan.status}
            return ScheduledPlan.model_validate(values)
    return plan


def plan_account_ids(plan):
    plans = [plan, *[ScheduledPlan.model_validate(v['terms']) for v in plan.config.get('history_versions', [])]]
    return {key for p in plans for key in [p.account_id, p.destination_id, p.accrual_account_id] if key}


def pending_for_plan(plan, detail):
    return detail['status'] not in PAID | {'skipped'} and (plan.kind != 'loan' or (
        detail['destination_id'] == str(plan.destination_id) and detail['currency'] == plan.currency))


def accrual_date(row, config):
    detail = row.snapshot.get('undone_detail', row.snapshot)
    if config.day_count != 'monthly' or detail.get('prepayment'):
        return date.fromisoformat(detail.get('payment_date', row.due_date.isoformat()))
    return row.due_date


def actor_for(session, username):
    actor = session.exec(select(User).where(User.username == username)).first()
    if not actor or not actor.is_active or not actor.family_id:
        raise HTTPException(403, '需要有效家庭成员身份')
    family = session.get(Family, actor.family_id)
    if not family or family.status != 'active':
        raise HTTPException(403, '家庭已归档，不能执行计划')
    return actor


def authorized(session, actor, plan, write=False):
    from routes.v1_transactions import _verify_account_read_permission, _verify_account_write_permission
    if plan.family_id != actor.family_id:
        raise HTTPException(404, '计划不存在')
    checker = _verify_account_write_permission if write else _verify_account_read_permission
    for account_id in [plan.account_id, plan.destination_id]:
        account = session.get(Account, account_id)
        if not account or account.family_id != plan.family_id:
            raise HTTPException(403, '计划账户关系已失效')
        checker(session, actor.username, account_id, '管理计划' if write else '查看计划')
        if write and not account.is_active:
            raise HTTPException(409, '计划账户已停用')
    if write and actor.id != plan.owner_id:
        # Shared read-write access can post a due installment; changing the
        # authority of a persistent automated job requires full control.
        from routes.v1_accounts import _verify_account_management_permission
        for account_id in [plan.account_id, plan.destination_id]:
            _verify_account_management_permission(actor, session.get(Account, account_id), '管理计划', session=session)
    # Editing a job must not expose its previous private accounts to recipients
    # of its newly selected accounts.
    historical = {uuid.UUID(v['terms'][key]) for v in plan.config.get('history_versions', [])
                  for key in ['account_id', 'destination_id']}
    for account_id in historical - {plan.account_id, plan.destination_id}:
        _verify_account_read_permission(session, actor.username, account_id, '查看历史计划')


def balance(session, account):
    from routes.v1_accounts import get_account_realtime_balance
    return get_account_realtime_balance(session, account.id, account.classification, account.balance)


def records_for(session, plan):
    return {r.number: r for r in session.exec(select(ScheduledOccurrence).where(
        ScheduledOccurrence.plan_id == plan.id).order_by(ScheduledOccurrence.number)).all()}


def projection(session, plan):
    records = records_for(session, plan)
    config = LoanConfig.model_validate(plan.config['loan']) if plan.kind == 'loan' else None
    if config and (config.final_payment_day is not None or config.final_payment_date is not None):
        final_row = records.get(plan.occurrence_limit)
        final_due = final_row.due_date if final_row and final_row.status in PAID | {'skipped', 'undone'} else occurrence_date(plan, plan.occurrence_limit)
        last_month = scheduled_date(plan, plan.occurrence_limit)
        if (final_due.year, final_due.month) > (last_month.year, last_month.month):
            raise HTTPException(422, f'最后一期还款月份不能晚于 {last_month:%Y-%m}')
        if final_due <= config.interest_start_date:
            raise HTTPException(422, '最后一期还款日期必须晚于计息开始日期')
        previous_row = records.get(plan.occurrence_limit - 1)
        previous = previous_row.due_date if previous_row and previous_row.status in PAID | {'skipped', 'undone'} else (
            occurrence_date(plan, plan.occurrence_limit - 1) if plan.occurrence_limit > 1 else config.interest_start_date)
        if final_due <= previous:
            raise HTTPException(422, '最后一期还款日期必须晚于上一期还款日')
        prior_payments = [date.fromisoformat(r.snapshot.get('payment_date', r.due_date.isoformat()))
                          for n, r in records.items() if n < plan.occurrence_limit and r.status in PAID
                          and booking_plan(plan, r).destination_id == plan.destination_id
                          and booking_plan(plan, r).currency == plan.currency]
        if prior_payments and final_due <= max(prior_payments):
            raise HTTPException(422, '最后一期还款日期必须晚于已发生的还款日期')
    if config and any(p.end_date >= occurrence_date(plan, plan.occurrence_limit) for p in config.interest_only_periods):
        raise HTTPException(422, '仅还利息结束日期必须早于最后一期还款日')
    principal = max(Decimal(0), balance(session, session.get(Account, plan.destination_id))) if config else Decimal(0)
    deferred = max(Decimal(0), balance(session, session.get(Account, plan.accrual_account_id))) if plan.accrual_account_id else Decimal(0)
    # Historical snapshots are immutable. Future amounts start from the live
    # unpaid balance, so external repayments and reconciliation are respected.
    loan_started = False
    projected_previous = None
    result = []
    for number in range(1, plan.occurrence_limit + 1):
        row = records.get(number)
        historical_plan = booking_plan(plan, row) if row and row.status in PAID | {'skipped', 'undone'} else plan
        due = row.due_date if row and row.status in PAID | {'skipped', 'undone'} else occurrence_date(plan, number)
        if plan.end_date and due > plan.end_date:
            break
        saved_detail = row.snapshot.get('undone_detail') if row and row.status == 'undone' else row.snapshot if row and row.status in PAID | {'skipped'} else None
        if saved_detail and 'total' in saved_detail:
            detail = dict(saved_detail)
            if row.status == 'undone' and config and historical_plan.destination_id == plan.destination_id and historical_plan.currency == plan.currency:
                principal = max(Decimal(0), principal - Decimal(detail.get('principal', '0')) + Decimal(detail.get('capitalized', '0')))
                deferred = max(Decimal(0), deferred + Decimal(detail.get('accrued', '0')) - Decimal(detail.get('deferred_paid', '0')))
                projected_previous = accrual_date(row, LoanConfig.model_validate(historical_plan.config['loan']))
                loan_started = True
        else:
            if config:
                if principal <= 0 and deferred <= 0:
                    break
                previous = occurrence_date(plan, number - 1) if number > 1 else config.interest_start_date
                # A skipped period does not waive its accrued interest.
                prior_paid = max((accrual_date(r, LoanConfig.model_validate(booking_plan(plan, r).config['loan']))
                                  for n, r in records.items() if n < number and r.status in PAID
                                  and booking_plan(plan, r).destination_id == plan.destination_id
                                  and booking_plan(plan, r).currency == plan.currency), default=config.interest_start_date)
                prior_paid = max(prior_paid, config.interest_start_date)
                if not loan_started:
                    previous = prior_paid
                    loan_started = True
                    projected_previous = previous
                previous = projected_previous
                try:
                    detail = installment(config, number, due, previous, principal, deferred,
                                         plan.currency, plan.config.get('payment_override'), scheduled_period_days(plan, number))
                except ValueError as error:
                    raise HTTPException(422, str(error)) from error
                if not row or row.status != 'skipped':
                    principal = Decimal(detail['remaining_principal'])
                    deferred = Decimal(detail['deferred_interest'])
                    projected_previous = due
            else:
                detail = {'total': str(historical_plan.amount), 'principal': '0', 'interest': '0', 'fee': '0'}
        result.append({**detail, 'id': str(row.id) if row else None, 'number': number,
                       'due_date': due.isoformat(), 'currency': historical_plan.currency,
                       'account_id': str(historical_plan.account_id), 'destination_id': str(historical_plan.destination_id),
                       'status': row.status if row else 'planned', 'last_error': row.last_error if row else None,
                       'transaction_ids': (row.transaction_ids + ([str(row.linked_transaction_id)] if row.linked_transaction_id else [])) if row else [],
                       'posted_at': row.posted_at.isoformat() if row and row.posted_at else None})
    return result


def occurrence(session, plan, number):
    existing = session.exec(select(ScheduledOccurrence).where(
        ScheduledOccurrence.plan_id == plan.id, ScheduledOccurrence.number == number)).first()
    if existing:
        return existing
    if number < 1 or number > plan.occurrence_limit:
        raise HTTPException(404, '期次不存在')
    due = occurrence_date(plan, number)
    if plan.end_date and due > plan.end_date:
        raise HTTPException(404, '期次不存在')
    row = ScheduledOccurrence(plan_id=plan.id, account_id=plan.account_id, number=number, due_date=due)
    session.add(row)
    session.flush()
    return row


def loan_category(session, plan, component):
    from models import Category
    name = '贷款手续费' if component == 'fee' else '贷款利息'
    category = session.exec(select(Category).where(Category.family_id == plan.family_id, Category.name == name)).first()
    if not category:
        category = Category(family_id=plan.family_id, name=name, icon='🏦', color='#6366f1')
        session.add(category)
        session.flush()
    return category.id


def make_transaction(session, plan, row, account, amount, kind, component, when, excluded=False, bank_amount=None):
    if amount <= 0:
        return None
    fields = prepare_booking(session, account, amount, plan.currency, when,
                             bank_amount, account.currency if bank_amount is not None else None)
    txn = Transaction(account_id=account.id, external_id=f'scheduled:{row.id}:{component}:{account.id}',
                      transacted_at=when, occurred_at=datetime.combine(when, datetime.min.time(), ZoneInfo(plan.timezone_name)).astimezone(timezone.utc).replace(tzinfo=None),
                      narration=plan.name, transaction_type=kind, excluded_from_stats=excluded,
                      extra={'scheduled_occurrence_id': str(row.id), 'scheduled_plan_id': str(plan.id),
                             'component': component}, **fields)
    if kind == 'expense' and component in {'interest', 'fee', 'capitalized_interest'}:
        txn.category_id = loan_category(session, plan, component)
        txn.category_source = 'manual'
    else:
        from services.rules.categories import other_category
        txn.category_id = other_category(session, plan.family_id, create=True).id
    txn.extra = {**txn.extra, 'transaction_type_source': 'manual'}
    session.add(txn)
    session.flush()
    row.transaction_ids = [*row.transaction_ids, str(txn.id)]
    return txn


def pair(session, plan, row, outgoing, incoming):
    transfer = Transfer(family_id=plan.family_id, outflow_transaction_id=outgoing.id,
                        inflow_transaction_id=incoming.id, amount=outgoing.amount)
    session.add(transfer)
    session.flush()
    row.transfer_ids = [*row.transfer_ids, str(transfer.id)]
    outgoing.transaction_type = incoming.transaction_type = 'transfer'
    outgoing.transfer_id = incoming.transfer_id = transfer.id
    outgoing.extra = {**outgoing.extra, 'direction': 'outflow'}
    incoming.extra = {**incoming.extra, 'direction': 'inflow'}
    session.add(outgoing)
    session.add(incoming)


def ensure_accrual_account(session, plan):
    if plan.accrual_account_id:
        return session.get(Account, plan.accrual_account_id)
    target = session.get(Account, plan.destination_id)
    account = Account(family_id=plan.family_id, owner_id=target.owner_id or plan.owner_id,
                      name=(plan.name[:75] + ' · unpaid interest'), account_type='other_liability',
                      classification='liability', currency=target.currency, balance=Decimal(0))
    session.add(account)
    session.flush()
    plan.accrual_account_id = account.id
    session.add(plan)
    return account


def post(session, actor, plan, number, payment_date=None, linked=None, bank_amount=None, prepayment=None):
    root_plan = plan
    authorized(session, actor, plan, write=True)
    if plan.status != 'active':
        raise HTTPException(409, '计划已暂停或取消')
    row = occurrence(session, plan, number)
    if row.status in PAID:
        return row
    plan = booking_plan(plan, row)
    authorized(session, actor, plan, write=True)
    if row.status == 'skipped':
        raise HTTPException(409, '本期已跳过')
    today = datetime.now(ZoneInfo(plan.timezone_name)).date()
    when = payment_date or row.due_date
    if when > today or (row.due_date > today and prepayment is None):
        raise HTTPException(400, '未来期次不能提前作为实际扣款记账，请使用提前还款')
    records = records_for(session, plan)
    loan_paid = [r for r in records.values() if r.status in PAID
                 and booking_plan(root_plan, r).destination_id == plan.destination_id
                 and booking_plan(root_plan, r).currency == plan.currency]
    if plan.kind == 'loan' and prepayment is None and any(
        1 <= n < number and r.status not in PAID | {'skipped'}
        and booking_plan(root_plan, r).destination_id == plan.destination_id
        and booking_plan(root_plan, r).currency == plan.currency for n, r in records.items()):
        raise HTTPException(409, '请先处理之前的贷款期次')
    items = projection(session, plan)
    if plan.kind == 'loan' and prepayment is None:
        unpaid = next((p for p in items if pending_for_plan(plan, p)), None)
        if not unpaid or unpaid['number'] != number:
            raise HTTPException(409, '请按顺序处理贷款期次')
    detail = next((p for p in items if p['number'] == number), None)
    if row.status == 'undone' and row.snapshot.get('undone_detail'):
        detail = dict(row.snapshot['undone_detail'])
    if prepayment is not None:
        config = LoanConfig.model_validate(plan.config['loan'])
        next_item = next((p for p in items if pending_for_plan(plan, p)), None)
        if not next_item:
            raise HTTPException(409, '贷款已经结清')
        start = max((accrual_date(r, LoanConfig.model_validate(booking_plan(root_plan, r).config['loan']))
                     for r in loan_paid if accrual_date(r, LoanConfig.model_validate(booking_plan(root_plan, r).config['loan'])) <= when), default=config.interest_start_date)
        start = max(start, config.interest_start_date)
        next_due = date.fromisoformat(next_item['due_date'])
        preceding = add_months(next_due, -1)
        period_days = scheduled_period_days(plan, next_item['number']) if (
            (config.final_payment_day is not None or config.final_payment_date is not None) and next_item['number'] == config.term_months
        ) else (next_due - preceding).days
        charged_interest = rounded(interest_for(config, max(Decimal(0), balance(session, session.get(Account, plan.destination_id))),
                                                start, when, period_days), plan.currency)
        treatment = next_item.get('interest_treatment')
        paid_interest = charged_interest if treatment is None else Decimal(0)
        detail = {'principal': str(prepayment), 'interest': str(paid_interest), 'fee': '0',
                  'total': str(prepayment + paid_interest), 'accrued': str(charged_interest if treatment == 'defer' else 0),
                  'capitalized': str(charged_interest if treatment == 'capitalize' else 0), 'prepayment': True}
    if not detail:
        raise HTTPException(409, '贷款已结清或期次已不存在')
    source, target = session.get(Account, plan.account_id), session.get(Account, plan.destination_id)
    actual_date = linked.transacted_at if linked else when
    if plan.kind == 'loan':
        config = LoanConfig.model_validate(plan.config['loan'])
        last_paid = max((date.fromisoformat(r.snapshot.get('payment_date', r.due_date.isoformat()))
                         for r in loan_paid), default=config.interest_start_date)
        if actual_date < last_paid:
            raise HTTPException(422, '支付日期不能早于上次还款或计息开始日期')
    if plan.kind == 'loan' and prepayment is None:
        config = LoanConfig.model_validate(plan.config['loan'])
        irregular_final = (config.final_payment_day is not None or config.final_payment_date is not None) and number == config.term_months
        if actual_date != row.due_date and (config.day_count != 'monthly' or irregular_final):
            previous = max((accrual_date(r, LoanConfig.model_validate(booking_plan(root_plan, r).config['loan'])) for r in loan_paid), default=config.interest_start_date)
            previous = max(previous, config.interest_start_date)
            detail = installment(config, number, actual_date, previous,
                max(Decimal(0), balance(session, target)),
                max(Decimal(0), balance(session, session.get(Account, plan.accrual_account_id))) if plan.accrual_account_id else Decimal(0),
                plan.currency, plan.config.get('payment_override'), scheduled_period_days(plan, number), phase_date=row.due_date)
    principal, interest, fee = [Decimal(detail[k]) for k in ('principal', 'interest', 'fee')]
    total = Decimal(detail['total'])
    if total == 0 and (linked is not None or bank_amount is not None):
        raise HTTPException(422, '本期无需扣款，不能关联实际扣款')
    if bank_amount is not None and source.currency == plan.currency and money(bank_amount) != money(total):
        raise HTTPException(422, '同币种实际扣款必须与本期总额一致')
    linked_amount = None
    if linked:
        from models import RefundAllocation, TransactionSplit
        if linked.account_id != source.id or linked.transaction_type != 'expense' or linked.transfer_id or linked.is_split or linked.refund_of_transaction_id or linked.is_reimbursable:
            raise HTTPException(400, '只能关联扣款账户中未关联的普通支出')
        if linked.extra.get('scheduled_occurrence_id') or session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == linked.id)).first() or session.exec(select(RefundAllocation).where(RefundAllocation.original_transaction_id == linked.id)).first():
            raise HTTPException(409, '此流水已有拆分或其他关联')
        same_original = linked.original_currency == plan.currency and money(linked.original_amount or linked.amount) == money(total)
        confirmed_fx = source.currency != plan.currency and linked.original_currency == source.currency
        if not same_original and not confirmed_fx:
            raise HTTPException(400, '扣款原币金额与本期计划不一致，请先修改后续计划')
        if abs((linked.transacted_at - row.due_date).days) > 7:
            raise HTTPException(400, '扣款日期与本期计划相差超过7天')
        when = linked.transacted_at
        linked_amount = linked.amount
        row.linked_transaction_id = linked.id
        row.linked_original = linked.model_dump(mode='json')
    elif bank_amount is not None:
        linked_amount = money(bank_amount, positive=True)
    cash_component = principal if plan.kind == 'loan' else total
    outgoing = None
    if cash_component > 0:
        allocation = money(linked_amount * cash_component / total) if linked_amount is not None and total else None
        if linked:
            fields = prepare_booking(session, source, cash_component, plan.currency, when,
                                     allocation, source.currency)
            for k, v in fields.items():
                setattr(linked, k, v)
            linked.extra = {**linked.extra, 'scheduled_occurrence_id': str(row.id), 'scheduled_plan_id': str(plan.id), 'component': 'principal' if plan.kind == 'loan' else 'transfer'}
            linked.excluded_from_stats = False
            outgoing = linked
        else:
            outgoing = make_transaction(session, plan, row, source, cash_component, 'transfer', 'principal' if plan.kind == 'loan' else 'transfer', when, bank_amount=allocation)
        incoming = make_transaction(session, plan, row, target, cash_component, 'transfer', 'receipt', when)
        pair(session, plan, row, outgoing, incoming)
    allocated = outgoing.amount if outgoing else Decimal(0)
    for component, value in [('interest', interest), ('fee', fee)]:
        if not value:
            continue
        allocation = None
        if linked_amount is not None:
            allocation = linked_amount - allocated if (component == 'fee' or not fee) else money(linked_amount * value / total)
            allocated += allocation
        if linked and outgoing is None:
            fields = prepare_booking(session, source, value, plan.currency, when, allocation, source.currency)
            for k, v in fields.items():
                setattr(linked, k, v)
            linked.extra = {**linked.extra, 'scheduled_occurrence_id': str(row.id), 'scheduled_plan_id': str(plan.id), 'component': component}
            linked.excluded_from_stats = False
            linked.category_id = loan_category(session, plan, component)
            linked.category_source = 'manual'
            linked.extra = {**linked.extra, 'transaction_type_source': 'manual'}
            outgoing = linked
            session.add(linked)
        else:
            make_transaction(session, plan, row, source, value, 'expense', component, when, bank_amount=allocation)
    if plan.kind == 'loan':
        accrued = Decimal(detail.get('accrued', '0'))
        capitalized = Decimal(detail.get('capitalized', '0'))
        if accrued:
            accrual_account = ensure_accrual_account(session, plan)
            make_transaction(session, plan, row, accrual_account, accrued, 'expense', 'deferred_interest', when, excluded=True)
        if capitalized:
            make_transaction(session, plan, row, target, capitalized, 'expense', 'capitalized_interest', when)
        if Decimal(detail.get('deferred_paid', '0')) and plan.accrual_account_id:
            accrual_account = session.get(Account, plan.accrual_account_id)
            deferred = max(Decimal(0), balance(session, accrual_account))
            repaid = min(deferred, Decimal(detail['deferred_paid']))
            make_transaction(session, plan, row, accrual_account, repaid, 'income', 'deferred_interest_paid', when, excluded=True)
    session.flush()
    if plan.kind == 'loan':
        detail['remaining_principal'] = str(max(Decimal(0), balance(session, target)))
        detail['deferred_interest'] = str(max(Decimal(0), balance(session, session.get(Account, plan.accrual_account_id)))) if plan.accrual_account_id else '0'
    detail['payment_date'] = when.isoformat()
    row.snapshot = detail
    row.status = 'reconciled' if linked else 'posted'
    row.last_error = None
    row.retry_after = None
    row.posted_at = datetime.now(timezone.utc)
    session.add(row)
    return row


def guard_transaction(txn):
    if (txn.extra or {}).get('scheduled_occurrence_id'):
        raise HTTPException(409, '计划流水请在计划详情中撤销该期后重新处理')


def undo(session, actor, plan, number):
    authorized(session, actor, plan, write=True)
    row = occurrence(session, plan, number)
    original_plan = booking_plan(plan, row)
    authorized(session, actor, original_plan, write=True)
    if any(r.id != row.id and r.status in PAID and r.posted_at and row.posted_at and r.posted_at > row.posted_at
           for r in records_for(session, plan).values()):
        raise HTTPException(409, '请先撤销后续已支付期次')
    from models import RefundAllocation
    ids = [uuid.UUID(k) for k in row.transaction_ids + ([str(row.linked_transaction_id)] if row.linked_transaction_id else [])]
    if ids and session.exec(select(RefundAllocation).where(RefundAllocation.original_transaction_id.in_(ids))).first():
        raise HTTPException(409, '请先解除本期流水的退款关联')
    if number < 1 and original_plan.destination_id == plan.destination_id and original_plan.config.get('loan') == plan.config.get('loan'):
        config = {k: v for k, v in plan.config.items() if k != 'payment_override'}
        if row.snapshot.get('previous_payment_override'):
            config['payment_override'] = row.snapshot['previous_payment_override']
        plan.config = config
        session.add(plan)
    for alias in session.exec(select(ScheduledBankMatch).where(ScheduledBankMatch.occurrence_id == row.id)).all():
        session.delete(alias)
    session.flush()
    for key in row.transfer_ids:
        transfer = session.get(Transfer, uuid.UUID(key))
        if transfer:
            session.delete(transfer)
    session.flush()
    for key in row.transaction_ids:
        txn = session.get(Transaction, uuid.UUID(key))
        if txn:
            session.delete(txn)
    if row.linked_transaction_id:
        txn = session.get(Transaction, row.linked_transaction_id)
        if not txn:
            raise HTTPException(409, '关联的银行流水已不存在')
        saved = Transaction.model_validate(row.linked_original)
        for name in Transaction.model_fields:
            if name != 'id':
                setattr(txn, name, getattr(saved, name))
        session.add(txn)
    session.flush()
    undone_detail = row.snapshot.get('undone_detail', row.snapshot) if row.status in PAID | {'undone'} else None
    row.status, row.snapshot, row.transaction_ids, row.transfer_ids = 'undone', {'undone_detail': undone_detail} if undone_detail else {}, [], []
    row.linked_transaction_id, row.linked_original = None, {}
    row.posted_at, row.bank_external_id, row.last_error, row.retry_after = None, None, None, None
    if number < 1:
        session.delete(row)
        versions = [{**v, 'occurrence_ids': [key for key in v['occurrence_ids'] if key != str(row.id)]}
                    for v in plan.config.get('history_versions', [])]
        plan.config = {**plan.config, 'history_versions': [v for v in versions if v['occurrence_ids']]}
        session.add(plan)
    else:
        session.add(row)
    return row


def delete_plans_for_accounts(session, account_ids):
    ids = set(account_ids)
    plans = [p for p in session.exec(select(ScheduledPlan)).all() if plan_account_ids(p) & ids]
    delete_plans(session, plans)


def delete_plans_for_owner(session, owner_id):
    delete_plans(session, session.exec(select(ScheduledPlan).where(ScheduledPlan.owner_id == owner_id)).all())


def delete_plans(session, plans):
    for plan in plans:
        for row in records_for(session, plan).values():
            for alias in session.exec(select(ScheduledBankMatch).where(ScheduledBankMatch.occurrence_id == row.id)).all():
                session.delete(alias)
            session.flush()
            # Other accounts retain historical postings, but cease to refer to
            # a removed plan and can subsequently be edited normally.
            for key in row.transaction_ids + ([str(row.linked_transaction_id)] if row.linked_transaction_id else []):
                txn = session.get(Transaction, uuid.UUID(key))
                if txn:
                    txn.extra = {k: v for k, v in txn.extra.items() if k not in {'scheduled_plan_id', 'scheduled_occurrence_id'}}
                    session.add(txn)
            session.delete(row)
        session.flush()
        session.delete(plan)
    session.flush()


def reconcile_import(session, actor_name, account, data, day):
    """Reconcile each bank leg using stable IDs and exact confirmed amounts."""
    if not data.external_id:
        return None

    def check(plan):
        if isinstance(actor_name, str) and actor_name.startswith('service:'):
            from services.principals import verify_service_account
            verify_service_account(session, actor_name, account)
            owner = session.get(User, plan.owner_id)
            if not owner:
                raise HTTPException(403, '计划创建者已不存在')
            authorized(session, actor_for(session, owner.username), plan, write=True)
        else:
            authorized(session, actor_for(session, actor_name), plan, write=True)

    previous = session.exec(select(ScheduledBankMatch).where(
        ScheduledBankMatch.account_id == account.id, ScheduledBankMatch.external_id == data.external_id)).first()
    if previous:
        row = session.get(ScheduledOccurrence, previous.occurrence_id)
        check(session.get(ScheduledPlan, row.plan_id))
        return {'id': str(previous.transaction_id), 'account_id': str(account.id),
                'external_id': data.external_id, 'status': 'duplicate'}
    explicit = (data.extra or {}).get('scheduled_occurrence_id')
    if explicit:
        try:
            row = session.get(ScheduledOccurrence, uuid.UUID(str(explicit)))
        except ValueError:
            raise HTTPException(422, '期次ID无效')
        plan = session.get(ScheduledPlan, row.plan_id) if row else None
        original_plan = booking_plan(plan, row) if plan else None
        if not plan or account.id not in {original_plan.account_id, original_plan.destination_id} or plan.family_id != account.family_id:
            raise HTTPException(404, '期次不存在')
        candidates = [row]
    else:
        plans = [p for p in session.exec(select(ScheduledPlan).where(ScheduledPlan.family_id == account.family_id)).all()
                 if account.id in plan_account_ids(p)]
        candidates = [r for p in plans
                      for r in records_for(session, p).values()
                      if booking_plan(p, r).name.strip() == data.narration.strip()
                      and account.id in {booking_plan(p, r).account_id, booking_plan(p, r).destination_id}
                      and r.snapshot.get('payment_date', r.due_date.isoformat()) == day.isoformat() and r.status in PAID]
    matching = []
    for row in candidates:
        root_plan = session.get(ScheduledPlan, row.plan_id)
        plan = booking_plan(root_plan, row)
        outgoing = account.id == plan.account_id
        if data.transaction_type not in ({'expense', 'transfer'} if outgoing else {'income', 'transfer'}):
            continue
        keys = row.transaction_ids + ([str(row.linked_transaction_id)] if row.linked_transaction_id else [])
        legs = [session.get(Transaction, uuid.UUID(k)) for k in keys]
        legs = [t for t in legs if t and t.account_id == account.id]
        booked = sum((t.amount for t in legs), Decimal(0))
        original = sum((t.original_amount for t in legs if t.original_currency == plan.currency), Decimal(0))
        native, amount = data.original_currency or data.currency or account.currency, money(data.original_amount or data.amount)
        exact = (native == plan.currency and amount == money(original)) or (native == account.currency and amount == money(booked))
        if exact and legs and row.status in PAID:
            matching.append((row, root_plan, plan, legs, booked))
    if len(matching) != 1:
        if explicit:
            raise HTTPException(409, '本期金额、币种或状态不匹配，请在计划详情中关联银行流水')
        return None
    row, root_plan, plan, legs, booked = matching[0]
    check(root_plan)
    existing_leg = session.exec(select(ScheduledBankMatch).where(
        ScheduledBankMatch.occurrence_id == row.id, ScheduledBankMatch.account_id == account.id)).first()
    if existing_leg:
        if explicit:
            raise HTTPException(409, '本期已关联其他银行流水或尚未入账')
        return None
    if data.settlement_amount is not None and money(data.settlement_amount) != money(booked):
        raise HTTPException(409, '实际结算金额不同，请先撤销该期并关联实际银行流水')
    session.add(ScheduledBankMatch(occurrence_id=row.id, account_id=account.id,
                                 external_id=data.external_id, transaction_id=legs[0].id))
    row.status = 'reconciled'
    if account.id == plan.account_id:
        row.bank_external_id = data.external_id
    session.add(row)
    return {'id': str(legs[0].id), 'account_id': str(account.id), 'external_id': data.external_id,
            'status': 'reconciled', 'scheduled_occurrence_id': str(row.id)}


def run_due(engine, stopped=None, now=None):
    now = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        ids = session.exec(select(ScheduledPlan.id).where(ScheduledPlan.status == 'active')).all()
    for plan_id in ids:
        if stopped and stopped.is_set():
            break
        with Session(engine) as session:
            lock_mutation(session)
            plan = session.get(ScheduledPlan, plan_id)
            if not plan or plan.status != 'active':
                continue
            try:
                actor = session.get(User, plan.owner_id)
                if not actor:
                    raise HTTPException(403, '计划创建者已不存在')
                actor = actor_for(session, actor.username)
                authorized(session, actor, plan, write=True)
                today = now.astimezone(ZoneInfo(plan.timezone_name)).date()
                processed = 0
                for detail in projection(session, plan):
                    if detail['due_date'] > today.isoformat():
                        break
                    row = occurrence(session, plan, detail['number'])
                    if row.status == 'undone':
                        original_plan = booking_plan(plan, row)
                        if plan.kind == 'loan' and original_plan.destination_id == plan.destination_id and original_plan.currency == plan.currency:
                            break
                        continue
                    if row.status in PAID | {'skipped'}:
                        continue
                    if plan.execution_mode == 'confirm':
                        row.status = 'awaiting'
                        row.snapshot = detail
                        session.add(row)
                        continue
                    if row.retry_after and row.retry_after.replace(tzinfo=timezone.utc) > now:
                        break
                    try:
                        with session.begin_nested():
                            post(session, actor, plan, row.number)
                        processed += 1
                        if processed >= 25:
                            break
                    except (HTTPException, PendingExchangeRate) as error:
                        row.last_error = str(getattr(error, 'detail', str(error)))[:500]
                        row.status = 'failed'
                        row.retry_after = now + timedelta(minutes=10)
                        session.add(row)
                        break
                session.commit()
            except HTTPException as error:
                session.rollback()
                lock_mutation(session)
                plan = session.get(ScheduledPlan, plan_id)
                plan.status = 'paused'
                plan.config = {**plan.config, 'pause_reason': str(error.detail)}
                session.add(plan)
                session.commit()
            except Exception:
                session.rollback()
                logging.getLogger(__name__).exception('Scheduled execution failed for %s', plan_id)


def start_worker(engine):
    stopped = threading.Event()
    def work():
        while not stopped.is_set():
            try:
                run_due(engine, stopped)
            except Exception:
                logging.getLogger(__name__).exception('Scheduled worker failed')
            stopped.wait(30)
    worker = threading.Thread(target=work, daemon=True, name='scheduled-payments')
    worker.start()
    return stopped, worker

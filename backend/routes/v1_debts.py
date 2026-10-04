"""Loans and Peer-to-Peer Debts (IOUs) REST API."""

from __future__ import annotations

from services.transaction_lock import lock_mutation

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from services.request_validation import CurrencyCode
from pydantic import BaseModel, Field
from sqlmodel import Session, select, desc, or_

from database import get_session
from models import Family, Loan, PersonalDebt, User
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Debts & Loans"])


class PersonalDebtCreate(BaseModel):
    # 支持多种字段命名规范：counterparty / debtor_or_creditor_name / person_name
    counterparty: Optional[str] = Field(default=None, max_length=100)
    debtor_or_creditor_name: Optional[str] = Field(default=None, max_length=100)
    person_name: Optional[str] = Field(default=None, max_length=100)
    # 支持 debt_type ("lend" | "borrow") 或 direction ("owe_me" | "i_owe")
    debt_type: Optional[str] = None
    direction: Optional[str] = None
    # 支持 principal_amount 或 amount
    principal_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    currency: CurrencyCode = "CNY"
    borrowed_date: Optional[date] = None
    due_date: Optional[date] = None
    interest_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1000)
    notes: Optional[str] = None


class PersonalDebtRepay(BaseModel):
    # 支持 repay_amount 或 amount
    repay_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    notes: Optional[str] = None


class LoanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    lender: Optional[str] = Field(default=None, max_length=100)
    original_principal: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    current_balance: Optional[Decimal] = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    interest_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1000)
    currency: CurrencyCode = "CNY"
    monthly_payment: Optional[Decimal] = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    term_months: Optional[int] = Field(default=360, ge=1, le=1200)
    repayment_method: Optional[str] = "equal_installment"
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None


def _resolve_user_family_id(session: Session, user_or_ctx: Any) -> Optional[uuid.UUID]:
    from services.principals import resolve_family_id
    return resolve_family_id(session, user_or_ctx)

# ── 个人往来借还款 (Personal Debts / IOUs) ──────────────────────────────────

@router.get("/debts")
def list_personal_debts(
    direction: Optional[str] = Query(None, description="owe_me | i_owe"),
    is_settled: Optional[bool] = Query(None),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """查询个人往来账目与借还款清单（支持朋友/同事借款借出统计）。"""
    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        return {
            "debts": [],
            "items": [],
            "total_owe_me": "0.00",
            "total_i_owe": "0.00",
            "count": 0,
        }

    current_u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:") else None

    stmt = select(PersonalDebt).where(PersonalDebt.family_id == family_id)
    if current_u and current_u.role not in ("admin", "owner"):
        stmt = stmt.where(or_(PersonalDebt.owner_id == current_u.id, PersonalDebt.owner_id.is_(None)))

    if direction:
        mapped_type = "lend" if direction == "owe_me" else "borrow"
        stmt = stmt.where(PersonalDebt.debt_type == mapped_type)
    if is_settled is not None:
        target_status = "settled" if is_settled else "active"
        stmt = stmt.where(PersonalDebt.status == target_status)

    debts = session.exec(stmt.order_by(desc(PersonalDebt.created_at))).all()

    items = []
    total_owe_me = Decimal("0")
    total_i_owe = Decimal("0")

    for d in debts:
        settled = (d.status in ("settled", "written_off") or d.remaining_amount <= 0)
        dir_val = "owe_me" if d.debt_type == "lend" else "i_owe"
        if not settled:
            if dir_val == "owe_me":
                total_owe_me += d.remaining_amount
            else:
                total_i_owe += d.remaining_amount

        items.append({
            "id": str(d.id),
            "counterparty": d.counterparty,
            "debtor_or_creditor_name": d.counterparty,
            "debt_type": d.debt_type,
            "direction": dir_val,
            "principal_amount": str(d.principal_amount.quantize(Decimal("0.01"))),
            "amount": str(d.principal_amount.quantize(Decimal("0.01"))),
            "remaining_amount": str(d.remaining_amount.quantize(Decimal("0.01"))),
            "remaining_balance": str(d.remaining_amount.quantize(Decimal("0.01"))),
            "currency": d.currency,
            "borrowed_date": d.borrowed_date.isoformat() if d.borrowed_date else None,
            "due_date": d.due_date.isoformat() if d.due_date else None,
            "interest_rate": str(d.interest_rate or 0),
            "status": d.status,
            "is_settled": settled,
            "notes": d.notes,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })

    return {
        "debts": items,
        "items": items,
        "summary": {
            "total_owe_me": str(total_owe_me.quantize(Decimal("0.01"))), # 应收款 (朋友欠我)
            "total_i_owe": str(total_i_owe.quantize(Decimal("0.01"))),   # 应付款 (我欠朋友)
            "net_debt": str((total_owe_me - total_i_owe).quantize(Decimal("0.01"))),
        },
        "count": len(items),
    }


@router.post("/debts")
def create_personal_debt(
    data: PersonalDebtCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """新建个人借贷记录，兼容前后端多种参数契约。"""
    lock_mutation(session)
    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        raise HTTPException(status_code=400, detail="您尚未加入或创建任何家庭，无法创建借贷记录")

    name = (data.counterparty or data.debtor_or_creditor_name or data.person_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写借款人/出借人姓名 (counterparty)")

    principal = data.principal_amount if data.principal_amount is not None else data.amount
    if principal is None or principal <= Decimal("0"):
        raise HTTPException(status_code=400, detail="借贷本金金额必须大于 0")

    if data.debt_type in ("lend", "borrow"):
        debt_type = data.debt_type
    elif data.direction in ("owe_me", "i_owe"):
        debt_type = "lend" if data.direction == "owe_me" else "borrow"
    else:
        debt_type = "lend"

    dir_label = "owe_me" if debt_type == "lend" else "i_owe"

    current_u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:") else None
    owner_id = current_u.id if current_u else None

    debt = PersonalDebt(
        family_id=family_id,
        owner_id=owner_id,
        debt_type=debt_type,
        counterparty=name,
        principal_amount=principal,
        remaining_amount=principal,
        currency=data.currency or "CNY",
        borrowed_date=data.borrowed_date or date.today(),
        due_date=data.due_date,
        interest_rate=data.interest_rate or Decimal("0"),
        status="active",
        notes=data.notes,
    )
    session.add(debt)
    session.commit()
    session.refresh(debt)

    return {
        "id": str(debt.id),
        "counterparty": debt.counterparty,
        "debtor_or_creditor_name": debt.counterparty,
        "debt_type": debt.debt_type,
        "direction": dir_label,
        "principal_amount": str(debt.principal_amount.quantize(Decimal("0.01"))),
        "amount": str(debt.principal_amount.quantize(Decimal("0.01"))),
        "remaining_amount": str(debt.remaining_amount.quantize(Decimal("0.01"))),
        "remaining_balance": str(debt.remaining_amount.quantize(Decimal("0.01"))),
        "is_settled": False,
        "status": debt.status,
    }


@router.post("/debts/{debt_id}/repay")
def repay_personal_debt(
    debt_id: uuid.UUID,
    data: PersonalDebtRepay,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """记录一笔借贷还款。严格校验还款金额大于 0 且不超过剩余待还。仅限创建者或家庭管理员操作。"""
    lock_mutation(session)
    debt = session.get(PersonalDebt, debt_id)
    if not debt:
        raise HTTPException(status_code=404, detail="Debt record not found")

    family_id = _resolve_user_family_id(session, user_or_ctx)
    current_u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:") else None
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_u and current_u.role == "admin")

    if not is_admin and debt.family_id != family_id:
        raise HTTPException(status_code=403, detail="无权操作其他家庭组的借贷记录")

    is_admin_or_owner = is_admin or (current_u and current_u.role in ("admin", "owner"))
    is_debt_owner = current_u and (debt.owner_id == current_u.id or debt.owner_id is None)
    if not (is_admin_or_owner or is_debt_owner):
        raise HTTPException(status_code=403, detail="无权操作此借贷记录：仅借据创建者或家庭管理员有权记录还款")

    raw_repay = data.repay_amount if data.repay_amount is not None else data.amount
    if raw_repay is None or Decimal(str(raw_repay)) <= Decimal("0"):
        raise HTTPException(status_code=400, detail="还款金额必须大于 0")

    repay_val = Decimal(str(raw_repay))
    if repay_val > debt.remaining_amount:
        raise HTTPException(
            status_code=400,
            detail=f"还款金额 ({repay_val}) 超过了当前剩余待还金额 ({debt.remaining_amount})"
        )

    new_balance = max(Decimal("0"), debt.remaining_amount - repay_val)
    debt.remaining_amount = new_balance
    is_settled = (new_balance == Decimal("0"))
    if is_settled:
        debt.status = "settled"

    if data.notes:
        debt.notes = f"{debt.notes or ''}\n[{date.today()}] 还款 {repay_val}: {data.notes}".strip()

    debt.updated_at = datetime.now(timezone.utc)
    session.add(debt)
    session.commit()
    session.refresh(debt)

    return {
        "id": str(debt.id),
        "remaining_amount": str(debt.remaining_amount.quantize(Decimal("0.01"))),
        "remaining_balance": str(debt.remaining_amount.quantize(Decimal("0.01"))),
        "is_settled": is_settled,
        "status": debt.status,
        "message": "结清成功" if is_settled else "部分还款已记账",
    }


@router.post("/debts/{debt_id}/write-off")
def write_off_personal_debt(
    debt_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """将借贷坏账核销 (status='written_off', remaining_amount=0)。仅限创建者或家庭管理员操作。"""
    lock_mutation(session)
    debt = session.get(PersonalDebt, debt_id)
    if not debt:
        raise HTTPException(status_code=404, detail="Debt record not found")

    family_id = _resolve_user_family_id(session, user_or_ctx)
    current_u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:") else None
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_u and current_u.role == "admin")

    if not is_admin and debt.family_id != family_id:
        raise HTTPException(status_code=403, detail="无权操作其他家庭组的借贷记录")

    is_admin_or_owner = is_admin or (current_u and current_u.role in ("admin", "owner"))
    is_debt_owner = current_u and (debt.owner_id == current_u.id or debt.owner_id is None)
    if not (is_admin_or_owner or is_debt_owner):
        raise HTTPException(status_code=403, detail="无权操作此借贷记录：仅借据创建者或家庭管理员有权核销")

    debt.status = "written_off"
    debt.remaining_amount = Decimal("0")
    debt.updated_at = datetime.now(timezone.utc)
    session.add(debt)
    session.commit()
    session.refresh(debt)

    return {
        "status": "ok",
        "message": "借据已成功核销",
        "id": str(debt.id),
        "debt_status": debt.status,
        "remaining_amount": "0.00",
    }


@router.delete("/debts/{debt_id}")
def delete_personal_debt(
    debt_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """删除指定的借贷记录。仅限创建者或家庭管理员操作。"""
    lock_mutation(session)
    debt = session.get(PersonalDebt, debt_id)
    if not debt:
        raise HTTPException(status_code=404, detail="Debt record not found")

    family_id = _resolve_user_family_id(session, user_or_ctx)
    current_u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:") else None
    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    is_admin = is_service or (current_u and current_u.role == "admin")

    if not is_admin and debt.family_id != family_id:
        raise HTTPException(status_code=403, detail="无权操作其他家庭组的借贷记录")

    is_admin_or_owner = is_admin or (current_u and current_u.role in ("admin", "owner"))
    is_debt_owner = current_u and (debt.owner_id == current_u.id or debt.owner_id is None)
    if not (is_admin_or_owner or is_debt_owner):
        raise HTTPException(status_code=403, detail="无权删除此借贷记录：仅借据创建者或家庭管理员有权删除")

    session.delete(debt)
    session.commit()
    return {"status": "ok", "message": "借据已成功删除", "id": str(debt.id)}


# ── 长期正规贷款 (Loans & Mortgages) ───────────────────────────────────────

@router.get("/loans")
@router.get("/debts/loans")
def list_loans(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取家庭长期借贷与房贷车贷列表。"""
    from models import Account

    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        return {
            "loans": [],
            "items": [],
            "total_loan_balance": "0.00",
            "count": 0,
        }

    from services.stats_engine import get_user_visible_account_ids
    current_u = session.exec(select(User).where(User.username == user_or_ctx)).first() if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:") else None
    acc_ids = get_user_visible_account_ids(session, current_u, family_id=family_id)
    if not acc_ids:
        return {
            "loans": [],
            "items": [],
            "total_loan_balance": "0.00",
            "count": 0,
        }

    loans = session.exec(select(Loan).where(Loan.account_id.in_(acc_ids))).all()

    from routes.v1_accounts import get_account_realtime_balance
    from models import ScheduledPlan
    from services.report_currency import ReportCurrency
    from services.schedules import projection
    from services.schedule_math import LoanConfig, active_rate
    from datetime import datetime, timezone
    report_money = ReportCurrency(session, current_u, cache_independently=True)
    visible_plans = session.exec(select(ScheduledPlan).where(ScheduledPlan.kind == 'loan',
        ScheduledPlan.status != 'cancelled', ScheduledPlan.destination_id.in_(acc_ids), ScheduledPlan.account_id.in_(acc_ids))).all()
    plan_by_account = {p.destination_id:p for p in visible_plans}
    items = []
    total_loan_balance = Decimal("0")
    for l in loans:
        amt = l.original_amount or Decimal("0")
        acc = session.get(Account, l.account_id)
        if acc:
            curr_bal = abs(get_account_realtime_balance(session, acc.id, getattr(acc, "classification", "liability"), acc.balance))
        else:
            curr_bal = amt
        native_currency = acc.currency if acc else 'CNY'
        total_loan_balance += report_money.amount(curr_bal, native_currency)
        plan = plan_by_account.get(l.account_id)
        next_payment = next((r for r in projection(session, plan) if r['status'] not in {'posted','reconciled','skipped'}), None) if plan else None
        config = LoanConfig.model_validate(plan.config['loan']) if plan else None
        current_rate = active_rate(config, max(datetime.now(timezone.utc).date(), config.interest_start_date)) if config else l.interest_rate
        items.append({
            "id": str(l.id),
            "account_id": str(l.account_id),
            "name": acc.name if acc else (l.loan_type or "借贷"),
            "currency": native_currency,
            "plan_id": str(plan.id) if plan else None,
            "next_payment": next_payment,
            "loan_type": l.loan_type,
            "lender": l.lender_name or "金融机构",
            "lender_name": l.lender_name or "金融机构",
            "original_principal": str(amt),
            "original_amount": str(amt),
            "current_balance": str(curr_bal),
            "interest_rate": str(current_rate or 0),
            "term_months": config.term_months if config else l.term_months,
            "repayment_method": l.repayment_method,
            "monthly_payment": next_payment["total"] if next_payment else (str(l.monthly_payment) if not plan and l.monthly_payment else None),
            "start_date": l.start_date.isoformat() if l.start_date else "",
            "end_date": l.end_date.isoformat() if l.end_date else None,
            "notes": None,
        })

    return {
        "loans": items,
        "items": items,
        "total_loan_balance": str(total_loan_balance),
        "currency": report_money.currency,
        "count": len(items),
    }


@router.post("/loans")
@router.post("/debts/loans")
def create_loan(
    data: LoanCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """登记新长期贷款/房贷。"""
    lock_mutation(session)
    from models import Account

    family_id = _resolve_user_family_id(session, user_or_ctx)
    if not family_id:
        raise HTTPException(status_code=400, detail="您尚未加入任何家庭组，无法登记贷款")

    current_u = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_u = session.exec(select(User).where(User.username == user_or_ctx)).first()
    owner_id = current_u.id if current_u else None

    balance_val = abs(Decimal(str(data.current_balance if data.current_balance is not None else data.original_principal)))
    # 创建负债账户
    acc = Account(
        family_id=family_id,
        owner_id=owner_id,
        name=data.name or "长期贷款",
        account_type="loan",
        classification="liability",
        balance=balance_val,
        currency=data.currency or "CNY",
        institution_name=data.lender or "金融机构",
    )
    session.add(acc)
    session.flush()

    from routes.v1_accounts import _ensure_opening_balance_transaction
    _ensure_opening_balance_transaction(session, acc)

    loan = Loan(
        account_id=acc.id,
        loan_type="mortgage" if "房" in (data.name or "") else "consumer",
        original_amount=data.original_principal,
        term_months=data.term_months or 360,
        interest_rate=data.interest_rate,
        repayment_method=data.repayment_method or "equal_installment",
        monthly_payment=data.monthly_payment,
        lender_name=data.lender,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    session.add(loan)
    session.commit()
    session.refresh(loan)

    return {
        "id": str(loan.id),
        "account_id": str(acc.id),
        "name": data.name,
        "lender": loan.lender_name,
        "current_balance": str(data.current_balance if data.current_balance is not None else data.original_principal),
    }

"""Loans and Peer-to-Peer Debts (IOUs) REST API."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select, desc

from database import get_session
from models import Family, Loan, PersonalDebt, User
from auth import get_current_user_or_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Debts & Loans"])


class PersonalDebtCreate(BaseModel):
    debtor_or_creditor_name: str = Field(description="Name of the person (e.g. friend, colleague, relative)")
    direction: str = Field(description="'owe_me' (friend owes me) or 'i_owe' (I owe friend)")
    amount: Decimal = Field(description="Principal amount")
    currency: str = "CNY"
    due_date: Optional[date] = None
    notes: Optional[str] = None


class PersonalDebtRepay(BaseModel):
    repay_amount: Decimal = Field(description="Amount to repay/settle")
    notes: Optional[str] = None


class LoanCreate(BaseModel):
    name: str
    lender: str
    original_principal: Decimal
    current_balance: Decimal
    interest_rate: Decimal = Decimal("0")
    currency: str = "CNY"
    monthly_payment: Optional[Decimal] = None
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None


# ── 个人往来借还款 (Personal Debts / IOUs) ──────────────────────────────────

@router.get("/debts")
def list_personal_debts(
    direction: Optional[str] = Query(None, description="owe_me | i_owe"),
    is_settled: Optional[bool] = Query(None),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """查询个人往来账目与借还款清单（支持朋友/同事借款借出统计）。"""
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    stmt = select(PersonalDebt).where(PersonalDebt.family_id == family.id)
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
        settled = (d.status == "settled" or d.remaining_amount <= 0)
        dir_val = "owe_me" if d.debt_type == "lend" else "i_owe"
        if not settled:
            if dir_val == "owe_me":
                total_owe_me += d.remaining_amount
            else:
                total_i_owe += d.remaining_amount

        items.append({
            "id": str(d.id),
            "debtor_or_creditor_name": d.counterparty,
            "direction": dir_val,
            "amount": str(d.principal_amount.quantize(Decimal("0.01"))),
            "remaining_balance": str(d.remaining_amount.quantize(Decimal("0.01"))),
            "currency": d.currency,
            "due_date": d.due_date.isoformat() if d.due_date else None,
            "is_settled": settled,
            "notes": d.notes,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })

    return {
        "debts": items,
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
    """新建个人借贷记录。"""
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    debt_type = "lend" if data.direction == "owe_me" else "borrow"
    debt = PersonalDebt(
        family_id=family.id,
        debt_type=debt_type,
        counterparty=data.debtor_or_creditor_name,
        principal_amount=data.amount,
        remaining_amount=data.amount,
        currency=data.currency,
        borrowed_date=date.today(),
        due_date=data.due_date,
        status="active",
        notes=data.notes,
    )
    session.add(debt)
    session.commit()
    session.refresh(debt)

    return {
        "id": str(debt.id),
        "debtor_or_creditor_name": debt.counterparty,
        "direction": data.direction,
        "amount": str(debt.principal_amount.quantize(Decimal("0.01"))),
        "remaining_balance": str(debt.remaining_amount.quantize(Decimal("0.01"))),
        "is_settled": False,
    }


@router.post("/debts/{debt_id}/repay")
def repay_personal_debt(
    debt_id: uuid.UUID,
    data: PersonalDebtRepay,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """记录一笔借贷还款。支持部分还款或全额结清。"""
    debt = session.get(PersonalDebt, debt_id)
    if not debt:
        raise HTTPException(status_code=404, detail="Debt record not found")

    repay_val = abs(Decimal(str(data.repay_amount)))
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
        "remaining_balance": str(debt.remaining_amount.quantize(Decimal("0.01"))),
        "is_settled": is_settled,
        "message": "结清成功" if is_settled else "部分还款已记账",
    }


# ── 长期正规贷款 (Loans & Mortgages) ───────────────────────────────────────

@router.get("/loans")
def list_loans(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取家庭长期借贷与房贷车贷列表。"""
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    loans = session.exec(
        select(Loan).where(Loan.family_id == family.id)
    ).all()

    items = []
    total_loan_balance = Decimal("0")
    for l in loans:
        total_loan_balance += l.current_balance
        items.append({
            "id": str(l.id),
            "name": l.name,
            "lender": l.lender,
            "original_principal": str(l.original_principal),
            "current_balance": str(l.current_balance),
            "interest_rate": str(l.interest_rate),
            "monthly_payment": str(l.monthly_payment) if l.monthly_payment else None,
            "start_date": l.start_date.isoformat(),
            "end_date": l.end_date.isoformat() if l.end_date else None,
            "notes": l.notes,
        })

    return {
        "loans": items,
        "total_loan_balance": str(total_loan_balance),
        "count": len(items),
    }


@router.post("/loans")
def create_loan(
    data: LoanCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """登记新长期贷款/房贷。"""
    family = session.exec(select(Family)).first()
    if not family:
        family = Family(name="我的家庭", currency="CNY")
        session.add(family)
        session.commit()
        session.refresh(family)

    loan = Loan(
        family_id=family.id,
        name=data.name,
        lender=data.lender,
        original_principal=data.original_principal,
        current_balance=data.current_balance,
        interest_rate=data.interest_rate,
        currency=data.currency,
        monthly_payment=data.monthly_payment,
        start_date=data.start_date,
        end_date=data.end_date,
        notes=data.notes,
    )
    session.add(loan)
    session.commit()
    session.refresh(loan)

    return {
        "id": str(loan.id),
        "name": loan.name,
        "lender": loan.lender,
        "current_balance": str(loan.current_balance),
    }

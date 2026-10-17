"""A scheduled cash debit is atomic and cannot create a negative balance."""
from datetime import date
from decimal import Decimal
import uuid

import pytest
from sqlmodel import select

from models import ExchangeRateSnapshot, ScheduledOccurrence, ScheduledPlan, Transaction, Transfer
from services.schedules import run_due
from test_scheduled_payments import account, create, payload, perform, value


@pytest.mark.parametrize('kind,opening,allowed', [
    ('cash', '-5', False), ('cash', '0', False), ('cash', '99.9999', False), ('cash', '100', True),
    ('checking', '99', False), ('checking', '100', True),
    ('savings', '99', False), ('savings', '100', True),
])
def test_plan_cash_debit_requires_funds_and_can_leave_exactly_zero(auth_client_a, db, kind, opening, allowed):
    source = account(auth_client_a, 'Credit loan name is not an account type', kind, opening)
    target = account(auth_client_a, 'Receipt', amount='0')
    plan = create(auth_client_a, payload(source, target, 'transfer', occurrence_limit=1))
    before = len(db.exec(select(Transaction)).all())
    response = perform(auth_client_a, plan)
    assert response.status_code == (200 if allowed else 409), response.text
    assert value(auth_client_a, source) == Decimal(opening) - (100 if allowed else 0)
    assert value(auth_client_a, target) == (100 if allowed else 0)
    assert len(db.exec(select(Transaction)).all()) == before + (2 if allowed else 0)
    assert len(db.exec(select(Transfer)).all()) == (1 if allowed else 0)
    assert len(db.exec(select(ScheduledOccurrence)).all()) == (1 if allowed else 0)
    if not allowed:
        assert '余额不足' in response.json()['detail']


def test_auto_plan_stops_when_cash_runs_out_and_retries_after_top_up(auth_client_a, db):
    source = account(auth_client_a, 'Available cash', 'cash', '150')
    target = account(auth_client_a, 'Receipt', amount='0')
    plan = create(auth_client_a, payload(source, target, 'transfer', execution_mode='auto'))
    run_due(db.get_bind())
    db.expire_all()
    rows = db.exec(select(ScheduledOccurrence).order_by(ScheduledOccurrence.number)).all()
    assert [row.status for row in rows] == ['posted', 'failed']
    assert rows[1].last_error and '余额不足' in rows[1].last_error
    assert rows[1].retry_after and not rows[1].transaction_ids and not rows[1].transfer_ids
    assert value(auth_client_a, source) == 50 and value(auth_client_a, target) == 100
    assert db.get(ScheduledPlan, uuid.UUID(plan['id'])).status == 'active'
    run_due(db.get_bind())  # Retrying before the retry time must not duplicate a debit.
    assert value(auth_client_a, source) == 50 and value(auth_client_a, target) == 100
    top_up = auth_client_a.post('/api/v1/transactions', json={
        'account': source, 'amount': 200, 'currency': 'CNY', 'transaction_type': 'income',
        'date': '2024-02-01', 'narration': 'Top up cash', 'external_id': 'cash-plan-top-up'})
    assert top_up.status_code == 200, top_up.text
    db.expire_all()
    failed = db.get(ScheduledOccurrence, rows[1].id)
    failed.retry_after = None
    db.add(failed); db.commit()
    run_due(db.get_bind()); run_due(db.get_bind())
    db.expire_all()
    rows = db.exec(select(ScheduledOccurrence).order_by(ScheduledOccurrence.number)).all()
    assert [row.status for row in rows] == ['posted', 'posted', 'posted']
    assert all(row.last_error is None and row.retry_after is None for row in rows)
    assert value(auth_client_a, source) == 50 and value(auth_client_a, target) == 300
    assert len(db.exec(select(Transaction).where(Transaction.external_id.like('scheduled:%'))).all()) == 6


def test_two_auto_plans_share_the_same_available_cash(auth_client_a, db):
    source = account(auth_client_a, 'One cash pool', amount='100')
    targets = [account(auth_client_a, f'Receipt {i}', amount='0') for i in range(2)]
    for target in targets:
        create(auth_client_a, payload(source, target, 'transfer', amount=80, execution_mode='auto', occurrence_limit=1))
    run_due(db.get_bind())
    assert value(auth_client_a, source) == 20
    assert sum(value(auth_client_a, target) for target in targets) == 80
    db.expire_all()
    assert sorted(row.status for row in db.exec(select(ScheduledOccurrence)).all()) == ['failed', 'posted']


def test_loan_cash_check_includes_principal_interest_and_fees_atomically(auth_client_a, db):
    source = account(auth_client_a, 'Cash', 'cash', '1000')
    target = account(auth_client_a, 'Loan', 'loan', '12000')
    body = payload(source, target, execution_mode='auto')
    body['loan']['fee'] = 10
    plan = create(auth_client_a, body)
    first = plan['occurrences'][0]
    assert Decimal(first['principal']) < 1000 < Decimal(first['total'])
    before = len(db.exec(select(Transaction)).all())
    run_due(db.get_bind())
    db.expire_all()
    failed = db.exec(select(ScheduledOccurrence)).one()
    assert failed.status == 'failed' and not failed.transaction_ids and not failed.transfer_ids
    assert '余额不足' in failed.last_error
    assert value(auth_client_a, source) == 1000 and value(auth_client_a, target) == 12000
    assert len(db.exec(select(Transaction)).all()) == before
    assert not db.exec(select(Transfer)).all()


def test_interest_only_payment_and_fee_must_both_fit_cash_balance(auth_client_a, db):
    source = account(auth_client_a, 'Cash', amount='125')
    target = account(auth_client_a, 'Loan', 'loan', '12000')
    body = payload(source, target)
    body['loan'].update(fee=10, phases=[{'from_period': 1, 'method': 'interest_only'}])
    plan = create(auth_client_a, body)
    assert Decimal(plan['occurrences'][0]['principal']) == 0
    assert Decimal(plan['occurrences'][0]['interest']) == 120
    assert perform(auth_client_a, plan).status_code == 409
    assert value(auth_client_a, source) == 125 and value(auth_client_a, target) == 12000
    assert not db.exec(select(ScheduledOccurrence)).all()


@pytest.mark.parametrize('bank_amount', [None, 750])
def test_cash_check_uses_native_fx_debit_not_original_payment_amount(auth_client_a, db, bank_amount):
    source = account(auth_client_a, 'CNY cash', amount='699')
    target = account(auth_client_a, 'USD receipt', amount='0', currency='USD')
    db.add(ExchangeRateSnapshot(requested_date=date(2024,1,31), effective_date=date(2024,1,31),
        rates={'EUR':'1','USD':'1','CNY':'7'})); db.commit()
    plan = create(auth_client_a, payload(source, target, 'transfer', currency='USD', amount=100, occurrence_limit=1))
    response = perform(auth_client_a, plan, **({'bank_amount':bank_amount} if bank_amount else {}))
    assert response.status_code == 409, response.text
    assert value(auth_client_a, source) == 699 and value(auth_client_a, target) == 0
    assert not db.exec(select(ScheduledOccurrence)).all()
    assert not db.exec(select(Transfer)).all()


def test_plan_link_of_real_bank_debit_does_not_require_funds_twice(auth_client_a, db):
    source = account(auth_client_a, 'Cash', amount='100')
    target = account(auth_client_a, 'Loan', 'loan', '1200')
    body = payload(source, target)
    body['loan'].update(rates=[{'effective_date':'2023-12-31','annual_rate':0}],
                        phases=[{'from_period':1,'method':'custom','amount':100}])
    plan = create(auth_client_a, body)
    bank = auth_client_a.post('/api/v1/transactions', json={
        'account': source, 'amount': 100, 'currency': 'CNY', 'transaction_type': 'expense',
        'date': '2024-01-31', 'narration': 'Already posted by bank', 'external_id': 'cash-bank-debit'})
    assert bank.status_code == 200, bank.text
    assert value(auth_client_a, source) == 0
    response = perform(auth_client_a, plan, action='link', transaction_id=bank.json()['id'])
    assert response.status_code == 200, response.text
    assert value(auth_client_a, source) == 0 and value(auth_client_a, target) == 1100


def test_prepayment_cannot_overdraw_cash_or_leave_partial_records(auth_client_a, db):
    source = account(auth_client_a, 'Cash', amount='500')
    target = account(auth_client_a, 'Loan', 'loan', '1200')
    body = payload(source, target)
    body['loan'].update(term_months=3, rates=[{'effective_date':'2023-12-31','annual_rate':0}])
    plan = create(auth_client_a, body)
    assert perform(auth_client_a, plan).status_code == 200
    assert value(auth_client_a, source) == 100
    response = auth_client_a.post(f'/api/v1/plans/{plan["id"]}/prepay', json={
        'amount':200, 'payment_date':'2024-02-01', 'strategy':'reduce_payment'})
    assert response.status_code == 409, response.text
    assert value(auth_client_a, source) == 100 and value(auth_client_a, target) == 800
    assert [row.number for row in db.exec(select(ScheduledOccurrence)).all()] == [1]


def test_credit_card_debt_is_not_treated_as_cash_available_to_spend(auth_client_a):
    source = account(auth_client_a, 'Credit card', 'credit_card', '0')
    target = account(auth_client_a, 'Cash receipt', amount='0')
    plan = create(auth_client_a, payload(source, target, 'transfer', occurrence_limit=1))
    response = perform(auth_client_a, plan)
    assert response.status_code == 200, response.text
    assert value(auth_client_a, source) == 100 and value(auth_client_a, target) == 100

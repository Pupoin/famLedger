"""A shortened final period can fall in the same month as the previous one."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select

from models import ScheduledPlan, Transaction
from services.schedules import run_due
from test_scheduled_payments import account, payload, create, perform, value


def calendar_body(client, final_date='2024-06-14', day_count='monthly', term=3):
    source = account(client, 'Closing payment')
    target = account(client, 'Closing loan', 'loan', '1200')
    body = payload(source, target, start_date='2024-05-01')
    body['loan'].update(term_months=term, interest_start_date='2024-04-01',
                        final_payment_date=final_date, day_count=day_count,
                        rates=[{'effective_date': '2024-04-01', 'annual_rate': 12}],
                        phases=[{'from_period': 1, 'method': 'interest_only'}])
    return source, target, body


@pytest.mark.parametrize('day_count,interest', [('monthly', '5.20'), ('actual_365', '5.13'), ('actual_360', '5.20')])
def test_last_two_payments_share_a_month_without_changing_count(auth_client_a, db, day_count, interest):
    source, target, body = calendar_body(auth_client_a, day_count=day_count)
    before = len(db.exec(select(Transaction)).all())
    preview = auth_client_a.post('/api/v1/plans/preview', json=body)
    assert preview.status_code == 200, preview.text
    rows = preview.json()['occurrences']
    assert [row['due_date'] for row in rows] == ['2024-05-01', '2024-06-01', '2024-06-14']
    assert Decimal(rows[-1]['interest']) == Decimal(interest)
    assert len(db.exec(select(Transaction)).all()) == before
    plan = create(auth_client_a, body)
    assert plan['occurrence_limit'] == 3 and plan['final_payment_date'] == '2024-06-14'
    assert plan['config']['loan']['final_payment_date'] == '2024-06-14'
    for number in [1, 2, 3]:
        response = perform(auth_client_a, plan, number)
        assert response.status_code == 200, response.text
        assert Decimal(response.json()['occurrences'][number - 1]['total']) == Decimal(rows[number - 1]['total'])
    assert value(auth_client_a, target) == 0
    assert value(auth_client_a, source) == 10000 - sum(Decimal(row['total']) for row in rows)


@pytest.mark.parametrize('final_date', ['2024-05-31', '2024-06-01'])
def test_exact_final_date_must_follow_penultimate_payment(auth_client_a, final_date):
    _, _, body = calendar_body(auth_client_a, final_date)
    for endpoint in ['/api/v1/plans/preview', '/api/v1/plans']:
        response = auth_client_a.post(endpoint, json=body)
        assert response.status_code == 422, response.text
        assert response.json()['detail'] == '最后一期还款日期必须晚于上一期还款日'


def test_single_final_payment_can_precede_regular_date_but_not_interest_start(auth_client_a):
    _, _, body = calendar_body(auth_client_a, '2024-04-14', term=1)
    plan = create(auth_client_a, body)
    assert plan['occurrences'][0]['due_date'] == '2024-04-14'
    assert Decimal(plan['occurrences'][0]['interest']) == Decimal('5.20')
    for date in ['2024-03-31', '2024-04-01']:
        body['loan']['final_payment_date'] = date
        result = auth_client_a.post('/api/v1/plans/preview', json=body)
        assert result.status_code == 422, result.text
        assert result.json()['detail'] == '最后一期还款日期必须晚于计息开始日期'


def test_day_and_exact_date_are_mutually_exclusive(auth_client_a):
    _, _, body = calendar_body(auth_client_a)
    body['loan']['final_payment_day'] = 14
    response = auth_client_a.post('/api/v1/plans/preview', json=body)
    assert response.status_code == 422, response.text
    assert '最后一期只能选择日号或完整日期其中一种' in response.json()['detail'][0]['msg']


@pytest.mark.parametrize('final_date', ['2024-07-14', '2024-07-31'])
def test_exact_day_can_extend_within_last_month(auth_client_a, final_date):
    _, _, body = calendar_body(auth_client_a, final_date)
    plan = create(auth_client_a, body)
    assert plan['occurrence_limit'] == 3
    assert plan['occurrences'][-1]['due_date'] == final_date


@pytest.mark.parametrize('final_date', ['2024-08-01', '2024-08-14', '2025-07-14'])
def test_exact_month_cannot_exceed_repayment_term(auth_client_a, final_date):
    _, _, body = calendar_body(auth_client_a, final_date)
    for endpoint in ['/api/v1/plans/preview', '/api/v1/plans']:
        result = auth_client_a.post(endpoint, json=body)
        assert result.status_code == 422, result.text
        assert result.json()['detail'] == '最后一期还款月份不能晚于 2024-07'


def test_month_limit_uses_original_schedule_when_editing_next_pending_period(auth_client_a):
    _, _, body = calendar_body(auth_client_a, '2024-07-14')
    plan = create(auth_client_a, body)
    assert perform(auth_client_a, plan).status_code == 200
    url = '/api/v1/plans/' + plan['id']
    body['start_date'] = auth_client_a.get(url).json()['edit_start_date']
    assert body['start_date'] == '2024-06-01'
    body['loan']['term_months'] = 2
    for method, endpoint in [('post', url + '/preview'), ('put', url)]:
        result = getattr(auth_client_a, method)(endpoint, json=body)
        assert result.status_code == 422, result.text
        assert result.json()['detail'] == '最后一期还款月份不能晚于 2024-06'
    unchanged = auth_client_a.get(url)
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()['occurrence_limit'] == 3
    assert unchanged.json()['final_payment_date'] == '2024-07-14'


def test_saved_full_date_is_readable_without_losing_its_month(auth_client_a, db):
    _, _, body = calendar_body(auth_client_a, '2035-06-14')
    body['start_date'] = '2035-05-01'
    body['loan']['interest_start_date'] = '2035-04-01'
    body['loan']['rates'][0]['effective_date'] = '2035-04-01'
    plan = create(auth_client_a, body)
    stored = db.get(ScheduledPlan, UUID(plan['id']))
    config = deepcopy(stored.config)
    config['loan'].pop('final_payment_day')
    stored.config = config
    db.add(stored)
    db.commit()
    before = len(db.exec(select(Transaction)).all())
    assert auth_client_a.get('/api/v1/plans').status_code == 200
    detail = auth_client_a.get('/api/v1/plans/' + plan['id'])
    assert detail.status_code == 200, detail.text
    assert detail.json()['final_payment_date'] == '2035-06-14'
    assert auth_client_a.post('/api/v1/plans/' + plan['id'] + '/preview', json=body).status_code == 200
    run_due(db.get_bind(), now=datetime(2035, 6, 14, tzinfo=timezone.utc))
    assert auth_client_a.get('/api/v1/plans/' + plan['id']).json()['occurrences'][-1]['status'] == 'awaiting'
    assert len(db.exec(select(Transaction)).all()) == before


def test_edit_final_date_keeps_paid_history_and_regular_anchor(auth_client_a, db):
    _, _, body = calendar_body(auth_client_a)
    plan = create(auth_client_a, body)
    assert perform(auth_client_a, plan, 1).status_code == 200
    paid = perform(auth_client_a, plan, 2).json()['occurrences'][:2]
    run_due(db.get_bind(), now=datetime(2024, 7, 1, tzinfo=timezone.utc))
    url = '/api/v1/plans/' + plan['id']
    detail = auth_client_a.get(url).json()
    body['start_date'] = detail['edit_start_date']
    assert body['start_date'] == '2024-07-01'
    body['loan']['final_payment_date'] = '2024-06-20'
    before = len(db.exec(select(Transaction)).all())
    preview = auth_client_a.post(url + '/preview', json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['occurrences'][:2] == paid
    assert auth_client_a.get(url).json()['final_payment_date'] == '2024-06-14'
    result = auth_client_a.put(url, json=body)
    assert result.status_code == 200, result.text
    assert result.json()['start_date'] == '2024-05-01'
    assert result.json()['occurrences'][:2] == paid
    assert result.json()['occurrences'][-1]['due_date'] == '2024-06-20'
    assert Decimal(result.json()['occurrences'][-1]['interest']) == Decimal('7.60')
    assert len(db.exec(select(Transaction)).all()) == before
    body['loan']['final_payment_date'] = None
    result = auth_client_a.put(url, json=body)
    assert result.status_code == 200, result.text
    assert result.json()['final_payment_date'] == '2024-07-01'
    assert result.json()['occurrences'][:2] == paid


def test_paid_final_date_cannot_change_or_switch_to_day_mode(auth_client_a):
    _, _, body = calendar_body(auth_client_a)
    plan = create(auth_client_a, body)
    for number in [1, 2, 3]:
        assert perform(auth_client_a, plan, number).status_code == 200
    url = '/api/v1/plans/' + plan['id']
    for final_date, final_day in [('2024-06-20', None), (None, 20), (None, None)]:
        body['loan'].update(final_payment_date=final_date, final_payment_day=final_day)
        for method, endpoint in [('put', url), ('post', url + '/preview')]:
            response = getattr(auth_client_a, method)(endpoint, json=body)
            assert response.status_code == 409, response.text
    assert auth_client_a.get(url).json()['final_payment_date'] == '2024-06-14'


def test_short_final_period_executes_at_local_midnight_once(auth_client_a, db):
    source, target, body = calendar_body(auth_client_a)
    body['execution_mode'] = 'auto'
    plan = create(auth_client_a, body)
    run_due(db.get_bind(), now=datetime(2024, 6, 13, 15, 59, 59, tzinfo=timezone.utc))
    rows = auth_client_a.get('/api/v1/plans/' + plan['id']).json()['occurrences']
    assert rows[1]['status'] == 'posted' and rows[2]['status'] != 'posted'
    run_due(db.get_bind(), now=datetime(2024, 6, 13, 16, tzinfo=timezone.utc))
    rows = auth_client_a.get('/api/v1/plans/' + plan['id']).json()['occurrences']
    assert rows[-1]['status'] == 'posted'
    assert value(auth_client_a, target) == 0
    assert value(auth_client_a, source) == Decimal('8770.80')
    before = len(db.exec(select(Transaction)).all())
    run_due(db.get_bind(), now=datetime(2024, 7, 1, tzinfo=timezone.utc))
    assert len(db.exec(select(Transaction)).all()) == before


def test_bank_actual_final_date_recalculates_short_period_and_remains_a_candidate(auth_client_a):
    source, target, body = calendar_body(auth_client_a)
    plan = create(auth_client_a, body)
    assert perform(auth_client_a, plan, 1).status_code == 200
    assert perform(auth_client_a, plan, 2).status_code == 200
    imported = auth_client_a.post('/api/v1/transactions', json={
        'account': source, 'amount': 1206, 'currency': 'CNY', 'transaction_type': 'expense',
        'date': '2024-06-16', 'narration': 'Actual closing payment', 'external_id': 'closing-payment-2024'})
    assert imported.status_code == 200, imported.text
    candidates = auth_client_a.get(f"/api/v1/plans/{plan['id']}/candidates/3")
    assert candidates.status_code == 200, candidates.text
    assert imported.json()['id'] in {item['id'] for item in candidates.json()['items']}
    before = value(auth_client_a, source)
    result = perform(auth_client_a, plan, 3, action='link', transaction_id=imported.json()['id'])
    assert result.status_code == 200, result.text
    assert Decimal(result.json()['occurrences'][-1]['interest']) == Decimal('6.00')
    assert value(auth_client_a, source) == before and value(auth_client_a, target) == 0


def test_prepaid_interest_and_final_interest_cover_distinct_short_periods(auth_client_a):
    source, target, body = calendar_body(auth_client_a)
    plan = create(auth_client_a, body)
    for number in [1, 2]:
        assert perform(auth_client_a, plan, number).status_code == 200
    result = auth_client_a.post('/api/v1/plans/' + plan['id'] + '/prepay', json={
        'amount': 100, 'payment_date': '2024-06-10', 'strategy': 'keep_schedule'})
    assert result.status_code == 200, result.text
    assert Decimal(result.json()['prepayments'][-1]['snapshot']['interest']) == Decimal('3.60')
    assert Decimal(result.json()['occurrences'][-1]['interest']) == Decimal('1.47')
    result = perform(auth_client_a, plan, 3)
    assert result.status_code == 200, result.text
    assert value(auth_client_a, target) == 0
    assert value(auth_client_a, source) == Decimal('8770.93')

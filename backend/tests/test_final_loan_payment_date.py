"""A closing day changes only the final day's number, never its month or term."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from main import app
from models import ScheduledOccurrence, Transaction
from services.schedule_math import add_months
from services.schedules import run_due
from test_scheduled_payments import account, payload, create, perform, value


def loan_body(client, final_day=20, day_count='monthly', term=3):
    source = account(client, 'Final date source')
    target = account(client, 'Final date loan', 'loan', '1200')
    body = payload(source, target)
    body['loan'].update(term_months=term, final_payment_day=final_day, day_count=day_count,
                        phases=[{'from_period': 1, 'method': 'interest_only'}])
    return source, target, body


@pytest.mark.parametrize('day_count,final_day,interest', [
    ('monthly', 20, '7.74'), ('monthly', 31, '12.00'),
    ('actual_365', 20, '7.89'), ('actual_365', 31, '12.23'),
    ('actual_360', 20, '8.00'), ('actual_360', 31, '12.40'),
])
def test_final_day_preview_and_posting_agree_without_moving_prior_dates(auth_client_a, db, day_count, final_day, interest):
    source, target, body = loan_body(auth_client_a, final_day, day_count)
    final_date = f'2024-03-{final_day:02}'
    before = len(db.exec(select(Transaction)).all())
    preview = auth_client_a.post('/api/v1/plans/preview', json=body)
    assert preview.status_code == 200, preview.text
    rows = preview.json()['occurrences']
    assert [r['due_date'] for r in rows] == ['2024-01-31', '2024-02-29', final_date]
    assert Decimal(rows[-1]['principal']) == 1200
    assert Decimal(rows[-1]['interest']) == Decimal(interest)
    assert len(db.exec(select(Transaction)).all()) == before
    plan = create(auth_client_a, body)
    assert plan['config']['loan']['final_payment_day'] == final_day
    assert plan['final_payment_date'] == final_date and plan['occurrence_limit'] == 3
    for number in [1, 2, 3]:
        result = perform(auth_client_a, plan, number)
        assert result.status_code == 200, result.text
        posted = result.json()['occurrences'][number - 1]
        assert Decimal(posted['total']) == Decimal(rows[number - 1]['total'])
    assert value(auth_client_a, target) == 0
    assert value(auth_client_a, source) == 10000 - sum(Decimal(r['total']) for r in rows)
    closing_transactions = db.exec(select(Transaction).where(Transaction.transacted_at == date.fromisoformat(final_date))).all()
    assert closing_transactions and all(t.extra.get('scheduled_occurrence_id') for t in closing_transactions)


@pytest.mark.parametrize('final_day', [0, 32, -1, 1.5, True, '20', '2024-03-20'])
def test_final_day_must_be_an_integer_from_one_to_thirty_one(auth_client_a, db, final_day):
    _, _, body = loan_body(auth_client_a, final_day)
    before = len(db.exec(select(Transaction)).all())
    for endpoint in ['/api/v1/plans/preview', '/api/v1/plans']:
        response = auth_client_a.post(endpoint, json=body)
        assert response.status_code == 422, response.text
    assert len(db.exec(select(Transaction)).all()) == before


@pytest.mark.parametrize('final_day', [10, 20])
def test_single_installment_day_must_follow_interest_start(auth_client_a, final_day):
    _, _, body = loan_body(auth_client_a, final_day, term=1)
    body['loan']['interest_start_date'] = '2024-01-20'
    response = auth_client_a.post('/api/v1/plans', json=body)
    assert response.status_code == 422, response.text
    assert response.json()['detail'] == '最后一期还款日期必须晚于计息开始日期'


def test_single_installment_can_close_before_regular_monthly_date(auth_client_a):
    _, target, body = loan_body(auth_client_a, 20, term=1)
    plan = create(auth_client_a, body)
    assert plan['occurrences'][0]['due_date'] == '2024-01-20'
    assert Decimal(plan['occurrences'][0]['interest']) == Decimal('7.74')
    assert perform(auth_client_a, plan).status_code == 200
    assert value(auth_client_a, target) == 0


def test_editing_final_date_preserves_paid_history_and_month_end_anchor(auth_client_a, db):
    _, _, body = loan_body(auth_client_a, None)
    plan = create(auth_client_a, body)
    paid = perform(auth_client_a, plan).json()['occurrences'][0]
    run_due(db.get_bind(), now=datetime(2024, 4, 1, tzinfo=timezone.utc))
    saved = auth_client_a.get('/api/v1/plans/' + plan['id']).json()
    # Submit the next-date value used by the real editor, not the original first date.
    body['start_date'] = saved['edit_start_date']
    assert body['start_date'] == '2024-02-29'
    body['loan']['final_payment_day'] = 20
    before = len(db.exec(select(Transaction)).all())
    url = '/api/v1/plans/' + plan['id']
    preview = auth_client_a.post(url + '/preview', json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['occurrences'][0] == paid
    assert auth_client_a.get(url).json()['config']['loan']['final_payment_day'] is None
    result = auth_client_a.put(url, json=body)
    assert result.status_code == 200, result.text
    assert result.json()['occurrences'][0] == paid
    assert result.json()['start_date'] == '2024-01-31'
    assert [r['due_date'] for r in result.json()['occurrences']] == ['2024-01-31', '2024-02-29', '2024-03-20']
    pending = db.exec(select(ScheduledOccurrence).where(ScheduledOccurrence.plan_id == UUID(plan['id']), ScheduledOccurrence.number == 3)).one()
    assert pending.due_date == date(2024, 3, 20) and pending.status == 'planned'
    body['loan']['final_payment_day'] = None
    restored = auth_client_a.put(url, json=body)
    assert restored.status_code == 200, restored.text
    assert [r['due_date'] for r in restored.json()['occurrences']] == ['2024-01-31', '2024-02-29', '2024-03-31']
    assert restored.json()['occurrences'][0] == paid
    assert len(db.exec(select(Transaction)).all()) == before


def test_editor_on_last_pending_period_does_not_use_override_as_regular_anchor(auth_client_a):
    _, _, body = loan_body(auth_client_a)
    plan = create(auth_client_a, body)
    for number in [1, 2]:
        assert perform(auth_client_a, plan, number).status_code == 200
    saved = auth_client_a.get('/api/v1/plans/' + plan['id']).json()
    assert saved['edit_start_date'] == '2024-03-31'
    assert saved['next']['due_date'] == '2024-03-20'
    body['start_date'] = saved['edit_start_date']
    body['loan']['final_payment_day'] = 25
    result = auth_client_a.put('/api/v1/plans/' + plan['id'], json=body)
    assert result.status_code == 200, result.text
    rows = result.json()['occurrences']
    assert [r['due_date'] for r in rows] == ['2024-01-31', '2024-02-29', '2024-03-25']
    assert result.json()['final_payment_date'] == '2024-03-25'
    assert Decimal(rows[-1]['interest']) == Decimal('9.68')


def test_processed_final_date_is_immutable(auth_client_a):
    _, _, body = loan_body(auth_client_a)
    plan = create(auth_client_a, body)
    for number in [1, 2, 3]:
        assert perform(auth_client_a, plan, number).status_code == 200
    url = '/api/v1/plans/' + plan['id']
    saved = auth_client_a.get(url).json()
    assert saved['final_payment_processed'] is True
    for final in [25, None]:
        body['loan']['final_payment_day'] = final
        for endpoint in [url, url + '/preview']:
            response = auth_client_a.put(endpoint, json=body) if endpoint == url else auth_client_a.post(endpoint, json=body)
            assert response.status_code == 409, response.text
    assert auth_client_a.get(url).json()['occurrences'] == saved['occurrences']


def test_monthly_final_bank_date_uses_actual_closing_days(auth_client_a):
    source, target, body = loan_body(auth_client_a)
    plan = create(auth_client_a, body)
    for number in [1, 2]:
        assert perform(auth_client_a, plan, number).status_code == 200
    result = perform(auth_client_a, plan, 3, payment_date='2024-03-22')
    assert result.status_code == 200, result.text
    closing = result.json()['occurrences'][-1]
    assert closing['due_date'] == '2024-03-20'
    assert closing['payment_date'] == '2024-03-22'
    assert Decimal(closing['interest']) == Decimal('8.52')
    assert value(auth_client_a, target) == 0 and value(auth_client_a, source) == Decimal('8767.48')


def test_prepayment_before_custom_final_uses_regular_month_accrual(auth_client_a):
    source, target, body = loan_body(auth_client_a)
    plan = create(auth_client_a, body)
    for number in [1, 2]:
        assert perform(auth_client_a, plan, number).status_code == 200
    response = auth_client_a.post('/api/v1/plans/' + plan['id'] + '/prepay', json={
        'amount': 100, 'payment_date': '2024-03-10', 'strategy': 'keep_schedule'})
    assert response.status_code == 200, response.text
    assert Decimal(response.json()['prepayments'][0]['snapshot']['interest']) == Decimal('3.87')
    closing = response.json()['occurrences'][-1]
    assert closing['due_date'] == '2024-03-20'
    assert Decimal(closing['interest']) == Decimal('3.55')
    assert perform(auth_client_a, plan, 3).status_code == 200
    assert value(auth_client_a, target) == 0
    assert value(auth_client_a, source) == Decimal('8768.58')


def test_bank_candidate_with_shifted_final_date_can_be_linked_without_double_debit(auth_client_a):
    source, target, body = loan_body(auth_client_a)
    plan = create(auth_client_a, body)
    for number in [1, 2]:
        assert perform(auth_client_a, plan, number).status_code == 200
    imported = auth_client_a.post('/api/v1/transactions', json={
        'account': source, 'amount': '1208.52', 'currency': 'CNY',
        'narration': 'Bank final loan payment', 'transaction_type': 'expense',
        'date': '2024-03-22', 'external_id': 'bank-custom-final-payment'})
    assert imported.status_code == 200, imported.text
    candidates = auth_client_a.get('/api/v1/plans/' + plan['id'] + '/candidates/3')
    assert candidates.status_code == 200, candidates.text
    assert imported.json()['id'] in [r['id'] for r in candidates.json()['items']]
    before = value(auth_client_a, source)
    result = perform(auth_client_a, plan, 3, action='link', transaction_id=imported.json()['id'])
    assert result.status_code == 200, result.text
    closing = result.json()['occurrences'][-1]
    assert closing['status'] == 'reconciled' and closing['payment_date'] == '2024-03-22'
    assert Decimal(closing['interest']) == Decimal('8.52')
    assert value(auth_client_a, target) == 0 and value(auth_client_a, source) == before


@pytest.mark.parametrize('final_day', [20, 25])
def test_final_day_cannot_move_before_or_onto_an_existing_prepayment(auth_client_a, final_day):
    _, _, body = loan_body(auth_client_a, None)
    plan = create(auth_client_a, body)
    for number in [1, 2]:
        assert perform(auth_client_a, plan, number).status_code == 200
    response = auth_client_a.post('/api/v1/plans/' + plan['id'] + '/prepay', json={
        'amount': 100, 'payment_date': '2024-03-25', 'strategy': 'keep_schedule'})
    assert response.status_code == 200, response.text
    body['loan']['final_payment_day'] = final_day
    response = auth_client_a.put('/api/v1/plans/' + plan['id'], json=body)
    assert response.status_code == 422, response.text
    assert response.json()['detail'] == '最后一期还款日期必须晚于已发生的还款日期'
    saved = auth_client_a.get('/api/v1/plans/' + plan['id']).json()
    assert saved['config']['loan']['final_payment_day'] is None
    assert saved['occurrences'][-1]['due_date'] == '2024-03-31'


@pytest.mark.parametrize('method', ['equal_installment', 'equal_principal', 'custom'])
def test_later_final_day_in_same_month_settles_remaining_principal_and_interest(auth_client_a, method):
    _, target, body = loan_body(auth_client_a, 31)
    body['start_date'] = '2024-01-05'
    body['loan']['interest_start_date'] = '2023-12-05'
    body['loan']['rates'][0]['effective_date'] = '2023-12-05'
    body['loan']['phases'] = [{'from_period': 1, 'method': method}]
    if method == 'custom':
        body['loan']['phases'][0]['amount'] = 20
    plan = create(auth_client_a, body)
    for number in [1, 2]:
        assert perform(auth_client_a, plan, number).status_code == 200
    remaining = value(auth_client_a, target)
    closing = plan['occurrences'][-1]
    assert Decimal(closing['principal']) == remaining
    assert [r['due_date'] for r in plan['occurrences']] == ['2024-01-05', '2024-02-05', '2024-03-31']
    expected_interest = (remaining * Decimal('0.01') * 55 / 29).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    assert Decimal(closing['interest']) == expected_interest
    assert perform(auth_client_a, plan, 3).status_code == 200
    assert value(auth_client_a, target) == 0


def test_worker_uses_final_day_at_local_midnight_and_remains_idempotent(auth_client_a, db):
    source, target, body = loan_body(auth_client_a)
    body['execution_mode'] = 'auto'
    plan = create(auth_client_a, body)
    run_due(db.get_bind(), now=datetime(2024, 3, 19, 15, 59, 59, tzinfo=timezone.utc))
    assert value(auth_client_a, target) == 1200 and value(auth_client_a, source) == 9976
    run_due(db.get_bind(), now=datetime(2024, 3, 19, 16, tzinfo=timezone.utc))
    assert value(auth_client_a, target) == 0
    before = len(db.exec(select(Transaction)).all())
    run_due(db.get_bind(), now=datetime(2024, 4, 2, tzinfo=timezone.utc))
    assert len(db.exec(select(Transaction)).all()) == before
    assert value(auth_client_a, source) == Decimal('8768.26')
    rows = auth_client_a.get('/api/v1/plans/' + plan['id']).json()['occurrences']
    assert rows[-1]['status'] == 'posted' and rows[-1]['due_date'] == '2024-03-20'


def test_final_day_uses_rate_changes_and_interest_only_window_boundary(auth_client_a):
    _, _, body = loan_body(auth_client_a, 31)
    body['loan']['rates'].append({'effective_date': '2024-03-21', 'annual_rate': 24})
    plan = create(auth_client_a, body)
    assert Decimal(plan['occurrences'][-1]['interest']) == Decimal('15.87')
    _, _, second_body = loan_body(auth_client_a, 20)
    second_body['loan']['phases'] = [{'from_period': 1, 'method': 'equal_installment'}]
    second_body['loan']['interest_only_periods'] = [{'start_date': '2024-01-31', 'end_date': '2024-03-25'}]
    assert auth_client_a.post('/api/v1/plans/preview', json=second_body).status_code == 422
    second_body['loan']['final_payment_day'] = 31
    response = auth_client_a.post('/api/v1/plans/preview', json=second_body)
    assert response.status_code == 200, response.text
    assert response.json()['occurrences'][-1]['method'] == 'equal_installment'


@pytest.mark.parametrize('start,final_date', [
    ('2023-12-05', '2024-02-29'), ('2024-12-05', '2025-02-28'),
    ('2024-02-05', '2024-04-30'), ('2024-11-05', '2025-01-31'),
])
def test_missing_final_day_clamps_to_month_end_without_changing_month_or_count(auth_client_a, start, final_date):
    _, _, body = loan_body(auth_client_a, 31)
    body['start_date'] = start
    interest_start = add_months(date.fromisoformat(start), -1).isoformat()
    body['loan']['interest_start_date'] = interest_start
    body['loan']['rates'][0]['effective_date'] = interest_start
    plan = create(auth_client_a, body)
    assert plan['occurrence_limit'] == len(plan['occurrences']) == 3
    assert [r['due_date'] for r in plan['occurrences'][:2]] == [
        start, add_months(date.fromisoformat(start), 1).isoformat()]
    assert plan['occurrences'][-1]['due_date'] == plan['final_payment_date'] == final_date
    assert plan['config']['loan']['final_payment_day'] == 31


def test_changing_term_moves_final_month_and_restores_old_final_to_regular_day(auth_client_a, db):
    _, _, body = loan_body(auth_client_a)
    plan = create(auth_client_a, body)
    run_due(db.get_bind(), now=datetime(2024, 4, 1, tzinfo=timezone.utc))
    body['loan']['term_months'] = 4
    result = auth_client_a.put('/api/v1/plans/' + plan['id'], json=body)
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved['occurrence_limit'] == len(saved['occurrences']) == 4
    assert [r['due_date'] for r in saved['occurrences']] == [
        '2024-01-31', '2024-02-29', '2024-03-31', '2024-04-20']
    assert saved['config']['loan']['final_payment_day'] == 20
    assert saved['final_payment_date'] == '2024-04-20'
    pending = db.exec(select(ScheduledOccurrence).where(
        ScheduledOccurrence.plan_id == UUID(plan['id']), ScheduledOccurrence.number == 3)).one()
    assert pending.due_date == date(2024, 3, 31)


@pytest.mark.parametrize('field, invalid', [('final_payment_day', '2024-12-20'), ('final_payment_date', 'not-a-date')])
def test_incorrect_final_payment_input_returns_json_validation_error_instead_of_server_error(auth_client_a, field, invalid):
    _, _, body = loan_body(auth_client_a)
    plan = create(auth_client_a, body)
    body['loan'][field] = invalid
    for method, endpoint in [('post', '/api/v1/plans'), ('post', '/api/v1/plans/preview'),
                             ('put', '/api/v1/plans/' + plan['id']),
                             ('post', '/api/v1/plans/' + plan['id'] + '/preview')]:
        response = getattr(auth_client_a, method)(endpoint, json=body)
        assert response.status_code == 422, response.text
        assert response.headers['content-type'].startswith('application/json')
        assert any(error['loc'][-1] == field for error in response.json()['detail'])


def test_plan_server_failure_returns_json_and_logs_the_failed_endpoint(auth_client_a, db, monkeypatch, caplog):
    from routes import v1_schedules
    _, _, body = loan_body(auth_client_a)
    before = len(db.exec(select(Transaction)).all())

    def unavailable(*args, **kwargs):
        raise RuntimeError('private schedule diagnostic')

    monkeypatch.setattr(v1_schedules, 'projection', unavailable)
    raw_client = TestClient(app, raise_server_exceptions=False)
    raw_client.cookies.update(auth_client_a.cookies)
    response = raw_client.post('/api/v1/plans/preview?private_hint=test-only', json=body,
                               headers={'X-FamLedger-CSRF': '1'})
    assert response.status_code == 500
    assert response.headers['content-type'].startswith('application/json')
    assert response.json() == {'detail': '服务器内部错误，请稍后重试。'}
    assert 'private schedule diagnostic' not in response.text
    records = [r for r in caplog.records if r.name == 'famledger' and 'Unhandled request error:' in r.message]
    assert records and 'POST /api/v1/plans/preview' in records[0].message
    assert 'private_hint' not in records[0].message and records[0].exc_info
    assert len(db.exec(select(Transaction)).all()) == before
    raw_client.close()

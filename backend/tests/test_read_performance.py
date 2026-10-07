"""Large ledger reads stay paginated and batch related financial data."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from time import perf_counter

import pytest
from sqlalchemy import event, update
from sqlalchemy.orm import Session as OrmSession

from models import Account, Category, ExchangeRateSnapshot, RefundAllocation, Transaction, TransactionSplit
from services.account_balances import rebuild_latest_balances
from test_fix104_regressions import setup_accounts


@pytest.fixture
def large_ledger(db, request):
    family, _, _, accounts = setup_accounts(db)
    card_group = getattr(request, 'param', None) == 'cards'
    if card_group:
        for account in accounts:
            account.account_type = 'credit_card'
        accounts[1].parent_account_id = accounts[0].id
        db.add_all(accounts); db.commit()
    categories = [Category(family_id=family.id, name=name) for name in ['Food', 'Travel']]
    db.add_all(categories); db.commit()
    rows, links, splits = [], [], []
    for index in range(3000):
        day = date.today() - timedelta(days=index // 10)
        kind = 'income' if index % 10 == 7 else 'transfer' if index % 10 == 8 else 'refund' if index % 10 == 9 else 'expense'
        amount = Decimal(20 if kind == 'income' else 30 if kind == 'transfer' else 5 if kind == 'refund' else 10)
        account = accounts[index % 2] if card_group and kind == 'expense' else accounts[0]
        row = Transaction(account_id=account.id, transacted_at=day,
            occurred_at=datetime.combine(day, time(12, index % 10)),
            amount=amount, currency='CNY', original_amount=amount, original_currency='CNY',
            exchange_rate=Decimal(1), exchange_rate_date=day, exchange_rate_source='same_currency',
            narration=f'Performance fixture {index}', transaction_type=kind, category_id=categories[0].id,
            is_split=index % 40 == 0, extra={'direction': 'inflow' if card_group else 'outflow'} if kind == 'transfer' else {},
            master_account_id=accounts[0].id if card_group and account == accounts[1] else None,
            master_settlement_amount=amount if card_group and account == accounts[1] else None,
            master_settlement_currency='CNY' if card_group and account == accounts[1] else None)
        rows.append(row)
        if row.is_split:
            splits.extend(TransactionSplit(transaction_id=row.id, category_id=category.id, amount=value)
                          for category, value in zip(categories, [Decimal(4), Decimal(6)]))
        if kind == 'refund':
            original = rows[index - 9]
            row.refund_of_transaction_id = original.id
            links.append(RefundAllocation(refund_transaction_id=row.id, original_transaction_id=original.id,
                allocated_amount=amount, original_currency='CNY', original_book_amount=amount,
                original_book_currency='CNY', refund_original_amount=amount, refund_original_currency='CNY',
                refund_book_amount=amount, refund_book_currency='CNY', fx_difference_amount=Decimal(0),
                fx_difference_currency='CNY'))
    # Bulk seeding is confined to this isolated test database. Rebuild the
    # derived snapshots explicitly; no application/runtime data is touched.
    db.execute(Transaction.__table__.insert(), [row.model_dump() for row in rows])
    db.execute(RefundAllocation.__table__.insert(), [row.model_dump() for row in links])
    db.execute(TransactionSplit.__table__.insert(), [row.model_dump() for row in splits])
    db.commit(); rebuild_latest_balances(db)
    return accounts, rows


def measured_get(client, db, url, params=None):
    queries, loaded = [], []
    engine = db.get_bind()
    def sql(conn, cursor, statement, parameters, context, many):
        queries.append(statement)
    def hydrate(session, row):
        if isinstance(row, Transaction):
            loaded.append(row.id)
    event.listen(engine, 'before_cursor_execute', sql)
    event.listen(OrmSession, 'loaded_as_persistent', hydrate)
    started = perf_counter()
    try:
        response = client.get(url, params=params)
    finally:
        event.remove(engine, 'before_cursor_execute', sql)
        event.remove(OrmSession, 'loaded_as_persistent', hydrate)
    print(f'\n{url}: seconds={perf_counter()-started:.3f}, queries={len(queries)}, transaction_objects={len(loaded)}')
    assert response.status_code == 200, response.text
    return response.json(), queries, loaded


def test_large_transaction_list_only_hydrates_requested_page(auth_client_a, db, large_ledger):
    result, queries, loaded = measured_get(auth_client_a, db, '/api/v1/transactions', {'limit': 100})
    assert len(result['items']) == 100 and result['total_count'] == 3000 and result['has_more']
    assert result['items'][0]['occurred_at'].endswith('12:09:00Z')
    assert len(queries) <= 30
    assert len(loaded) <= 120  # one page, its cursor lookahead and linked originals


def test_large_report_batches_refund_reads_and_preserves_category_net(auth_client_a, db, large_ledger):
    report, queries, loaded = measured_get(auth_client_a, db, '/api/v1/analytics/report', {'period': 'all'})
    assert report['kpis']['total_expense'] == 19500
    assert report['kpis']['total_income'] == 6000
    assert sum(row['amount'] for row in report['activity']['expense_categories']) == 19500
    assert len(queries) <= 80  # must not grow once per transaction or refund


def test_large_monthly_overview_preserves_annual_trend(auth_client_a, db, large_ledger):
    accounts, rows = large_ledger
    overview, queries, loaded = measured_get(auth_client_a, db, '/api/v1/dashboard/summary', {'period': 'monthly'})
    days = (date.today() - date.today().replace(day=1)).days + 1
    assert overview['outflows']['total'] == days * 65
    assert sum(row['expense'] for row in overview['money_in_out']['last_12_months']) == 19500
    assert len(queries) <= 45


@pytest.mark.parametrize('large_ledger', ['cards'], indirect=True)
def test_large_card_report_uses_group_debt_without_duplicate_cards(auth_client_a, db, large_ledger):
    report, queries, loaded = measured_get(auth_client_a, db, '/api/v1/analytics/report', {'period': 'monthly'})
    assert len(queries) <= 45
    assert report['net_worth']['liabilities_total'] == 4500
    assert report['net_worth']['current'] == -4500
    assert report['net_worth']['trend'][-1]['value'] == -4500
    first_day = date.today() - timedelta(days=299)
    for point in report['net_worth']['trend']:
        days = min(300, max(0, (date.fromisoformat(point['as_of']) - first_day).days + 1))
        assert point['value'] == -15 * days


@pytest.mark.parametrize('large_ledger', [None, 'cards'], indirect=True)
def test_report_foreground_does_not_replay_history_and_sections_match_full_report(auth_client_a, db, large_ledger):
    params = {'period': 'monthly'}
    core, queries, loaded = measured_get(auth_client_a, db, '/api/v1/analytics/report',
                                         {**params, 'include_history': 'false'})
    assert core['history_loaded'] is False
    assert core['trends'] is None and core['net_worth']['trend'] == []
    assert len(queries) <= 25
    assert len(loaded) <= 650  # selected and prior month, no entire card ledger
    full, _, _ = measured_get(auth_client_a, db, '/api/v1/analytics/report', params)
    history, _, _ = measured_get(auth_client_a, db, '/api/v1/analytics/history', params)
    for key in ['kpis', 'activity', 'investments', 'currency', 'date_range']:
        assert core[key] == full[key]
    for key in ['current', 'assets_total', 'liabilities_total', 'credit_total', 'loan_total']:
        assert core['net_worth'][key] == full['net_worth'][key]
    assert history['history_loaded'] is True
    assert history['trends'] == full['trends']
    assert history['net_worth']['trend'] == full['net_worth']['trend']
    assert history['currency'] == core['currency']


def test_large_category_drilldown_batches_links_and_preserves_full_net(auth_client_a, db, large_ledger):
    result, queries, loaded = measured_get(auth_client_a, db, '/api/v1/transactions', {
        'limit': 100, 'spending_net': 'true', 'category_name': 'Food'})
    assert result['total_count'] == 2400 and len(result['items']) == 100
    assert result['spending_summary']['net'] == 19275
    assert len(queries) <= 20
    assert len(loaded) <= 2420  # income and transfer rows stay out of spending reads


def test_spending_drilldown_does_not_request_quotes_for_ignored_income(auth_client_a, db, monkeypatch):
    _, _, _, accounts = setup_accounts(db)
    accounts[1].currency = 'USD'
    db.add(accounts[1]); db.commit()
    db.add_all([
        Transaction(account_id=accounts[0].id, transacted_at=date.today(), amount=Decimal(100),
                    currency='CNY', narration='Purchase', transaction_type='expense'),
        Transaction(account_id=accounts[1].id, transacted_at=date.today() + timedelta(days=1),
                    amount=Decimal(10), currency='USD', narration='Future income', transaction_type='income'),
    ])
    db.commit()
    monkeypatch.setattr('services.report_currency.requests.get',
                        lambda *a, **k: pytest.fail('income is outside the spending drilldown'))
    result = auth_client_a.get('/api/v1/transactions', params={'spending_net': 'true'})
    assert result.status_code == 200, result.text
    assert result.json()['total_count'] == 1
    assert result.json()['spending_summary']['net'] == 100


def test_keyset_pages_preserve_ties_and_authorization(auth_client_a, db):
    family, _, bob, accounts = setup_accounts(db)
    private = Account(name='Private', family_id=family.id, owner_id=bob.id, account_type='checking')
    db.add(private); db.commit()
    stamp = datetime.combine(date.today(), time(12))
    rows = [Transaction(account_id=accounts[0].id, transacted_at=stamp.date(),
                        occurred_at=stamp if index % 2 else None, created_at=stamp,
                        amount=Decimal(10), narration=f'Tied entry {index}', transaction_type='expense')
            for index in range(25)]
    hidden = Transaction(account_id=private.id, transacted_at=stamp.date(), occurred_at=stamp,
                         amount=Decimal(10), narration='Private entry', transaction_type='expense')
    db.add_all(rows + [hidden]); db.commit()
    # SQLAlchemy applies the model's timestamp default to None on insert.
    # Explicitly reproduce historical NULL timestamps for coalesce pagination.
    db.execute(update(Transaction).where(Transaction.id.in_([row.id for row in rows[::2]]))
               .values(occurred_at=None))
    db.commit()
    expected = [str(row.id) for row in sorted(rows, key=lambda row: row.id.int, reverse=True)]
    first = auth_client_a.get('/api/v1/transactions', params={'limit': 7}).json()
    collected, page = [], first
    while True:
        collected.extend(row['id'] for row in page['items'])
        assert page['total_count'] == 25
        if not page['has_more']:
            break
        response = auth_client_a.get('/api/v1/transactions', params={'limit': 7, 'cursor': page['next_cursor']})
        assert response.status_code == 200, response.text
        page = response.json()
    assert collected == expected
    for cursor in [str(hidden.id), 'invalid-id', '  ']:
        response = auth_client_a.get('/api/v1/transactions', params={'limit': 7, 'cursor': cursor})
        assert response.status_code == 200, response.text
        assert [row['id'] for row in response.json()['items']] == expected[:7]
    offset = auth_client_a.get('/api/v1/transactions', params={'limit': 7, 'offset': 7}).json()
    assert [row['id'] for row in offset['items']] == expected[7:14]
    filtered = auth_client_a.get('/api/v1/transactions', params={
        'limit': 7, 'search': 'Tied entry 0', 'cursor': str(rows[1].id)}).json()
    assert [row['id'] for row in filtered['items']] == [str(rows[0].id)]


def test_cached_daily_report_quotes_are_read_together(db, monkeypatch):
    from services.report_currency import ReportCurrency
    _, _, _, accounts = setup_accounts(db)
    days = [date.today() - timedelta(days=index) for index in range(25)]
    db.add_all(ExchangeRateSnapshot(requested_date=day, effective_date=day,
        rates={'CNY': '2', 'USD': '1', 'EUR': '1'}) for day in days)
    db.commit()
    rows = [Transaction(account_id=accounts[0].id, transacted_at=day, amount=Decimal(10),
                        currency='CNY', narration='Foreign report', transaction_type='expense') for day in days]
    monkeypatch.setattr('services.report_currency.requests.get',
                        lambda *a, **k: pytest.fail('stored daily rates must not fetch from the network'))
    converter = ReportCurrency(db, currency='USD')
    queries = []
    def count_quotes(conn, cursor, statement, parameters, context, many):
        if 'exchange_rate_snapshots' in statement.lower():
            queries.append(statement)
    event.listen(db.get_bind(), 'before_cursor_execute', count_quotes)
    try:
        converted = converter.transactions(rows)
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', count_quotes)
    assert [row.amount for row in converted] == [Decimal(5)] * 25
    assert len(queries) == 1
    assert len(converter.metadata()['exchange_rate_dates']) == 25


@pytest.mark.parametrize('offset,cny', [(-1, '2'), (8, '2'), (0, '0')])
def test_batched_report_quotes_reject_invalid_saved_rates(db, offset, cny):
    from fastapi import HTTPException
    from services.report_currency import ReportCurrency
    _, _, _, accounts = setup_accounts(db)
    day = date.today() - timedelta(days=10)
    db.add(ExchangeRateSnapshot(requested_date=day, effective_date=day - timedelta(days=offset),
                               rates={'CNY': cny, 'USD': '1', 'EUR': '1'}))
    db.commit()
    row = Transaction(account_id=accounts[0].id, transacted_at=day, amount=Decimal(10),
                      currency='CNY', narration='Invalid quote', transaction_type='expense')
    with pytest.raises(HTTPException) as caught:
        ReportCurrency(db, currency='USD').transactions([row])
    assert caught.value.status_code == 502

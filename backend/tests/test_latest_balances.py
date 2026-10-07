"""Materialized balances must conserve money and survive races/rollbacks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Column, MetaData, Table, event, inspect, text, update, delete
from sqlmodel import Session, SQLModel, create_engine, select

from models import Account, AccountShare, ExchangeRateSnapshot, Family, Transaction, Transfer, User
from routes.v1_accounts import get_account_realtime_balance
from services.account_balances import SNAPSHOT_FIELDS, rebuild_latest_balances, verify_latest_balances
from services.report_currency import ReportCurrency
from services.stats_engine import get_report_account_balances, get_grouped_account_balances

DAY = date(2026, 9, 1)


@pytest.fixture
def ledger(db):
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    family = Family(name='Balance snapshot verification')
    db.add(family); db.flush()
    alice.family_id = bob.family_id = family.id
    db.add_all([alice, bob]); db.flush()
    accounts = [Account(name=name, family_id=family.id, owner_id=alice.id,
                        account_type='checking', currency='CNY') for name in ['Cash', 'Other cash']]
    db.add_all(accounts); db.commit()
    return accounts, alice, bob


def activity(db, account, amount, kind='expense', **fields):
    txn = Transaction(account_id=account.id, amount=Decimal(str(amount)), currency=account.currency,
                      transaction_type=kind, transacted_at=DAY, occurred_at=datetime(2026, 9, 1, 12),
                      narration='Recorded activity', **fields)
    db.add(txn); db.commit()
    return txn


def check(db, account, expected, own=None, count=None):
    db.refresh(account)
    assert account.latest_balance == Decimal(str(expected))
    if own is not None:
        assert account.latest_own_balance == Decimal(str(own))
    if count is not None:
        assert account.latest_transaction_count == count
    assert account.balance_updated_at is not None
    assert get_account_realtime_balance(db, account.id) == Decimal(str(expected))
    assert not verify_latest_balances(db)


def cards(db, ledger, child_currency='CNY'):
    _, alice, bob = ledger
    master = Account(name='Master', account_type='credit_card', classification='liability',
                     family_id=alice.family_id, owner_id=alice.id)
    child = Account(name='Child', account_type='credit_card', classification='liability',
                    family_id=alice.family_id, owner_id=bob.id, currency=child_currency)
    db.add_all([master, child]); db.flush()
    db.add(AccountShare(account_id=child.id, user_id=alice.id, permission='read_only')); db.flush()
    child.parent_account_id = master.id
    db.add(child); db.commit()
    return master, child


def test_precise_income_expense_refund_transfer_and_reconciliation(db, ledger):
    account = ledger[0][0]
    check(db, account, 0, count=0)
    activity(db, account, 1000, 'income')
    activity(db, account, '250.1234')
    activity(db, account, '20.3333', 'refund')
    activity(db, account, '50.2222', 'transfer', extra={'direction': 'outflow'})
    activity(db, account, '20.0001', 'adjustment', extra={'direction': 'decrease'})
    check(db, account, '699.9876', own='699.9876', count=5)


def test_edit_type_move_account_and_delete_recompute_both_accounts(db, ledger):
    a, b = ledger[0]
    txn = activity(db, a, 30)
    check(db, a, -30)
    txn.amount = Decimal('42.1234'); txn.transaction_type = 'income'; db.add(txn); db.commit()
    check(db, a, '42.1234')
    txn.account_id = b.id; db.add(txn); db.commit()
    check(db, a, 0, count=0); check(db, b, '42.1234', count=1)
    db.delete(txn); db.commit()
    check(db, b, 0, count=0)


@pytest.mark.parametrize('account_type', ['checking', 'credit_card'])
def test_deleted_opening_activity_never_resurrects_the_old_base(auth_client_a, db, account_type):
    from uuid import UUID
    response = auth_client_a.post('/api/v1/accounts', json={
        'name': 'Opening verification', 'account_type': account_type, 'currency': 'CNY', 'balance': '100'})
    assert response.status_code == 200, response.text
    account = db.get(Account, UUID(response.json()['id']))
    for txn in db.exec(select(Transaction).where(Transaction.account_id == account.id)).all():
        db.delete(txn)
    db.commit()
    check(db, account, 0, count=0)
    rebuild_latest_balances(db)
    check(db, account, 0, count=0)
    response = auth_client_a.patch(f'/api/v1/accounts/{account.id}', json={'balance': '50'})
    assert response.status_code == 200, response.text
    check(db, account, 50, count=1)


def test_pending_flush_and_rollback_do_not_publish_uncommitted_balances(db, ledger):
    account = ledger[0][0]
    txn = activity(db, account, 20)
    db.refresh(account)
    version = account.balance_version
    txn.amount = Decimal(50); db.add(txn); db.flush()
    assert get_account_realtime_balance(db, account.id) == -50
    db.rollback()
    check(db, account, -20)
    assert account.balance_version == version


def test_failed_commit_leaves_the_previous_snapshot_and_ledger(db, ledger):
    account = ledger[0][0]
    activity(db, account, 20)
    db.refresh(account); version = account.balance_version
    db.add(Transaction(account_id=account.id, amount=Decimal(10), currency='CNY',
                       transaction_type='expense', transacted_at=DAY, narration='Recorded activity'))
    def fail(session):
        if session is db:
            raise RuntimeError('Simulated commit failure after snapshot preparation')
    event.listen(Session, 'before_commit', fail)
    try:
        with pytest.raises(RuntimeError, match='Simulated commit failure'):
            db.commit()
    finally:
        event.remove(Session, 'before_commit', fail)
    db.rollback()
    check(db, account, -20, count=1)
    assert account.balance_version == version


@pytest.mark.parametrize('rollback_inner', [True, False])
def test_savepoint_does_not_forget_outer_ledger_mutations(db, ledger, rollback_inner):
    account = ledger[0][0]
    first = Transaction(account_id=account.id, amount=Decimal(10), currency='CNY',
                        transaction_type='expense', transacted_at=DAY, narration='Outer activity')
    db.add(first); db.flush()
    try:
        with db.begin_nested():
            db.add(Transaction(account_id=account.id, amount=Decimal(20), currency='CNY',
                transaction_type='expense', transacted_at=DAY, narration='Nested activity'))
            db.flush()
            if rollback_inner:
                raise RuntimeError('Roll back only the nested activity')
    except RuntimeError:
        pass
    expected = -10 if rollback_inner else -30
    assert get_account_realtime_balance(db, account.id) == expected
    db.commit()
    check(db, account, expected, count=1 if rollback_inner else 2)


def test_pairing_and_unpairing_refreshes_both_direction_dependent_balances(db, ledger):
    a, b = ledger[0]
    outgoing = activity(db, a, 80, 'transfer')
    incoming = activity(db, b, 80, 'transfer')
    pair = Transfer(family_id=a.family_id, amount=Decimal(80), outflow_transaction_id=outgoing.id,
                    inflow_transaction_id=incoming.id)
    db.add(pair); db.flush()
    outgoing.transfer_id = incoming.transfer_id = pair.id
    db.add_all([outgoing, incoming]); db.commit()
    check(db, a, -80); check(db, b, 80)
    outgoing.extra = {'direction': 'outflow'}; incoming.extra = {'direction': 'inflow'}
    outgoing.transfer_id = incoming.transfer_id = None
    db.add_all([outgoing, incoming]); db.delete(pair); db.commit()
    check(db, a, -80); check(db, b, 80)


def test_repays_entire_card_group_and_stores_each_native_share(db, ledger):
    master, child = cards(db, ledger)
    activity(db, master, 300); activity(db, child, 200)
    check(db, master, 500, own=300); check(db, child, 200, own=200)
    payment = activity(db, master, 200, 'transfer', extra={'direction': 'inflow'})
    check(db, master, 300, own=180); check(db, child, 120, own=120)
    db.delete(payment); db.commit()
    check(db, master, 500, own=300); check(db, child, 200, own=200)
    activity(db, child, 600, 'income')
    check(db, master, -100, own=-100); check(db, child, 0, own=0)


def test_only_visible_child_contributes_its_own_debt(db, ledger, auth_client_b):
    master, child = cards(db, ledger)
    activity(db, master, 300); activity(db, child, 200)
    money = ReportCurrency(db, currency='CNY')
    assert get_report_account_balances(db, [master, child], money) == {master.id: 500, child.id: 0}
    assert get_report_account_balances(db, [child], money) == {child.id: 200}
    response = auth_client_b.get('/api/v1/accounts')
    assert response.status_code == 200, response.text
    items = response.json()['accounts']
    assert {row['id'] for row in items} == {str(child.id)}
    assert Decimal(items[0]['report_balance']) == 200
    assert Decimal(items[0]['report_own_balance']) == 200


def test_foreign_child_contribution_uses_fixed_settlement_not_todays_rate(db, ledger, auth_client_b):
    master, child = cards(db, ledger, child_currency='USD')
    activity(db, child, 100, master_account_id=master.id, master_settlement_amount=Decimal(700),
             master_settlement_currency='CNY', master_exchange_rate=Decimal(7))
    quote_day = date.today()
    db.add(ExchangeRateSnapshot(requested_date=quote_day, base_currency='EUR', effective_date=quote_day,
                               rates={'EUR':'1', 'USD':'1', 'CNY':'8'})); db.commit()
    money = ReportCurrency(db, currency='CNY')
    assert get_report_account_balances(db, [child], money)[child.id] == 700
    assert get_report_account_balances(db, [master, child], money) == {master.id:700, child.id:0}
    assert get_grouped_account_balances(db, [master, child], money) == {master.id:0, child.id:700}
    assert get_grouped_account_balances(db, [master], money) == {master.id:700}
    response = auth_client_b.get('/api/v1/accounts')
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()['accounts'] if row['id'] == str(child.id))
    assert Decimal(item['balance']) == 100
    assert Decimal(item['report_settlement_balance']) == 700
    assert Decimal(item['report_own_balance']) == 700


def test_account_list_reads_snapshots_without_scanning_transaction_rows(db, ledger, auth_client_a):
    master, child = cards(db, ledger)
    activity(db, master, 300); activity(db, child, 200)
    statements = []
    engine = db.get_bind()
    def record(conn, cursor, statement, params, context, many):
        statements.append(' '.join(statement.lower().split()))
    event.listen(engine, 'before_cursor_execute', record)
    try:
        response = auth_client_a.get('/api/v1/accounts')
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert response.status_code == 200, response.text
    assert not any('from transactions' in sql for sql in statements), statements
    assert next(row for row in response.json()['accounts'] if row['id'] == str(master.id))['transaction_count'] == 1


def test_long_lived_session_reads_another_workers_committed_snapshot(db, ledger):
    account = ledger[0][0]
    with Session(db.get_bind()) as worker:
        held = worker.get(Account, account.id)
        assert get_account_realtime_balance(worker, account.id) == 0
        activity(db, account, 99)
        assert get_account_realtime_balance(worker, account.id) == -99
        assert held.latest_balance == -99


@pytest.mark.parametrize('delete_in_worker', [False, True])
def test_long_lived_pending_worker_never_resurrects_a_deleted_opening(db, ledger, delete_in_worker):
    account, other = ledger[0]
    account.balance = Decimal(100); db.add(account); db.commit()
    with Session(db.get_bind()) as worker:
        held = worker.get(Account, account.id)
        assert held.ledger_initialized is False
        txn = activity(db, account, 20)
        if delete_in_worker:
            worker.delete(worker.get(Transaction, txn.id))
            worker.commit()
            check(worker, held, 0, count=0)
        else:
            db.delete(txn); db.commit()
            worker.add(Transaction(account_id=other.id, amount=Decimal(10), currency='CNY',
                transacted_at=DAY, narration='Pending unrelated payment', transaction_type='expense'))
            assert get_account_realtime_balance(worker, held.id) == 0
            worker.commit()
            check(worker, held, 0, count=0)


def test_rebuild_repairs_tampered_snapshot_without_changing_transactions(db, ledger):
    account = ledger[0][0]
    txn = activity(db, account, '12.3456')
    db.execute(Account.__table__.update().where(Account.id == account.id).values(latest_balance=999))
    db.commit()
    assert verify_latest_balances(db)[0]['account_id'] == str(account.id)
    assert rebuild_latest_balances(db) == 2
    check(db, account, '-12.3456')
    assert db.get(Transaction, txn.id).amount == Decimal('12.3456')
    assert len(db.exec(select(Transaction)).all()) == 1


def test_verification_locks_a_consistent_view_without_changing_ledger_or_version(db, ledger):
    account = ledger[0][0]
    txn = activity(db, account, '12.3456')
    db.refresh(account)
    version = account.balance_version
    statements = []
    engine = db.get_bind()
    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', record)
    try:
        with Session(engine) as reader:
            assert not verify_latest_balances(reader)
            assert reader.get(Account, account.id).balance_version == version
            assert reader.get(Transaction, txn.id).amount == Decimal('12.3456')
        assert 'BEGIN IMMEDIATE' in statements
        assert not any(sql.lstrip().upper().startswith(('UPDATE ', 'INSERT ', 'DELETE ')) for sql in statements)
    finally:
        event.remove(engine, 'before_cursor_execute', record)


def test_backfill_initializes_only_missing_snapshots_and_is_idempotent(db, ledger):
    a, b = ledger[0]
    activity(db, a, 20)
    db.refresh(a); version = a.balance_version
    db.execute(Account.__table__.update().where(Account.id == b.id).values(latest_balance=None, balance_updated_at=None))
    db.commit()
    assert rebuild_latest_balances(db, missing_only=True) == 1
    assert rebuild_latest_balances(db, missing_only=True) == 0
    db.refresh(a); assert a.balance_version == version
    check(db, a, -20); check(db, b, 0)


def test_bulk_transaction_update_move_and_delete_refresh_old_and_new_accounts(db, ledger):
    a, b = ledger[0]
    txn = activity(db, a, 10)
    db.execute(update(Transaction).where(Transaction.id == txn.id).values(amount=Decimal('42.1234'), account_id=b.id))
    db.commit()
    check(db, a, 0); check(db, b, '-42.1234')
    db.execute(delete(Transaction).where(Transaction.id == txn.id)); db.commit()
    check(db, b, 0, count=0)


def test_existing_sqlite_accounts_migrate_and_backfill_without_losing_data(tmp_path):
    from services.schema import sync_schema
    engine = create_engine(f'sqlite:///{tmp_path / "old-schema.db"}')
    excluded = set(SNAPSHOT_FIELDS) | {'balance_version'}
    legacy_metadata = MetaData()
    legacy = Table('accounts', legacy_metadata, *(Column(column.name, column.type,
        nullable=column.nullable, primary_key=column.primary_key,
        default=column.default._copy() if column.default is not None else None)
        for column in Account.__table__.columns if column.name not in excluded))
    legacy_metadata.create_all(engine)
    import uuid
    account_id, family_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(legacy.insert().values(id=account_id, family_id=family_id, name='Existing account',
            account_type='cash', classification='asset', currency='CNY', balance=Decimal('123.4567')))
    metadata = MetaData()
    Account.__table__.to_metadata(metadata)
    User.__table__.to_metadata(metadata)
    Family.__table__.to_metadata(metadata)
    try:
        statements = sync_schema(engine, metadata=metadata)
        assert len(statements) == len(excluded)
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            account = session.get(Account, account_id)
            assert account.name == 'Existing account' and account.balance == Decimal('123.4567')
            assert account.latest_balance is None and account.balance_version == 0
            assert rebuild_latest_balances(session, missing_only=True) == 1
            check(session, account, '123.4567', count=0)
        assert not sync_schema(engine, metadata=metadata)
    finally:
        engine.dispose()


def test_concurrent_sqlite_writers_do_not_lose_balance_updates(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "balance-race.db"}', connect_args={'check_same_thread': False, 'timeout': 15})
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            family = Family(name='Concurrency verification'); session.add(family); session.flush()
            account = Account(name='Concurrent account', family_id=family.id, account_type='cash')
            session.add(account); session.commit(); account_id = account.id
        def write(_):
            with Session(engine) as session:
                account = session.get(Account, account_id)
                activity(session, account, '1.2345')
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(write, range(12)))
        with Session(engine) as session:
            check(session, session.get(Account, account_id), '-14.8140', count=12)
    finally:
        engine.dispose()

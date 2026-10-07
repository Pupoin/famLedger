"""Opt-in PostgreSQL verification against an explicitly isolated test database.

Run with FAMLEDGER_TEST_PG_URL=postgresql+psycopg://.../fix104_verify.
Each test owns a random schema; neither the application DB nor its data is used.
"""
import asyncio
import json
import os
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import Boolean, Column, Integer, MetaData, Table, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Session, create_engine, select
from starlette.requests import Request

from models import (Account, Family, FamilyInvitation, PersonalDebt,
                    RefundAllocation, Transaction, User)


@pytest.fixture
def pg_engine(monkeypatch):
    url = os.getenv("FAMLEDGER_TEST_PG_URL")
    if not url:
        pytest.skip("Set FAMLEDGER_TEST_PG_URL to an isolated PostgreSQL test database")
    if make_url(url).database != "fix104_verify":
        pytest.fail("PostgreSQL verification is restricted to database fix104_verify")
    schema = "fix104_" + uuid.uuid4().hex
    control = create_engine(url)
    with control.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    import database
    monkeypatch.setattr(database, "is_sqlite", False)
    SQLModel.metadata.create_all(engine)
    try:
        yield engine, schema
    finally:
        engine.dispose()
        with control.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def seed_household(engine):
    with Session(engine) as session:
        family = Family(name="Isolated PostgreSQL household")
        session.add(family)
        session.flush()
        user = User(username="pg_owner", display_name="PG owner", family_id=family.id, role="owner")
        session.add(user)
        session.flush()
        account = Account(name="Wallet", family_id=family.id, owner_id=user.id, account_type="checking")
        session.add(account)
        session.commit()
        return family.id, user.id, account.id


def test_postgres_materialized_balances_serialize_concurrent_writers(pg_engine):
    from services.account_balances import verify_latest_balances
    engine, _ = pg_engine
    _, _, account_id = seed_household(engine)
    def write(_):
        with Session(engine) as session:
            session.add(Transaction(account_id=account_id, transacted_at=date(2026, 9, 1),
                amount=Decimal('1.2345'), currency='CNY', narration='Concurrent payment', transaction_type='expense'))
            session.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(12)))
    with Session(engine) as session:
        account = session.get(Account, account_id)
        assert account.latest_balance == Decimal('-14.8140')
        assert account.latest_transaction_count == 12
        assert not verify_latest_balances(session)


def test_postgres_materialized_balance_preserves_outer_savepoint_writes(pg_engine):
    from services.account_balances import verify_latest_balances
    engine, _ = pg_engine
    _, _, account_id = seed_household(engine)
    with Session(engine) as session:
        session.add(Transaction(account_id=account_id, transacted_at=date(2026, 9, 1), amount=Decimal(10),
                                currency='CNY', narration='Outer payment', transaction_type='expense'))
        session.flush()
        with pytest.raises(RuntimeError):
            with session.begin_nested():
                session.add(Transaction(account_id=account_id, transacted_at=date(2026, 9, 1), amount=Decimal(20),
                                        currency='CNY', narration='Canceled payment', transaction_type='expense'))
                session.flush()
                raise RuntimeError('Rollback savepoint')
        session.commit()
        account = session.get(Account, account_id)
        assert account.latest_balance == -10 and account.latest_transaction_count == 1
        assert not verify_latest_balances(session)


@pytest.mark.parametrize("endpoint,period", [
    ("dashboard", "monthly"),
    ("dashboard", "custom"),
    ("analytics", "monthly"),
    ("analytics", "custom"),
    ("budgets", "monthly"),
])
def test_postgres_financial_reports_use_date_parameters_and_keep_month_boundaries(pg_engine, endpoint, period):
    from routes.v1_dashboard import get_dashboard_summary
    from routes.analytics import get_comprehensive_report
    from routes.v1_budgets import get_budgets_summary
    from models import FamilyBudget

    engine, _ = pg_engine
    family_id, _, account_id = seed_household(engine)
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/dashboard/summary", "headers": []})
    with Session(engine) as session:
        session.add(FamilyBudget(family_id=family_id, settings={"total_budget": 100}))
        for day, amount in [(date(2026, 8, 31), 8), (date(2026, 9, 1), 11),
                            (date(2026, 9, 30), 13), (date(2026, 10, 1), 17)]:
            session.add(Transaction(account_id=account_id, transacted_at=day, amount=Decimal(amount),
                                    currency="CNY", narration="Boundary purchase", transaction_type="expense"))
        session.commit()
        kwargs = {"session": session, "user_or_ctx": "pg_owner"}
        if endpoint == "budgets":
            result = get_budgets_summary(month="2026-09", **kwargs)
            assert result["total_spent"] == 24
        else:
            kwargs.update(request=request, period=period, selected_month="2026-09",
                          start_date="2026-09-01", end_date="2026-09-30")
            if endpoint == "dashboard":
                result = get_dashboard_summary(account_id=None, user_filter=None, **kwargs)
                assert result["outflows"]["total"] == 24
                assert sum(cell["amount"] for week in result["spending_calendar"]["weeks"] for cell in week) == 24
                bars = {bar["ym"]: bar for bar in result["money_in_out"]["last_12_months"]}
                assert bars["2026-08"]["expense"] == 8
                assert bars["2026-09"]["expense"] == 24
            else:
                result = get_comprehensive_report(**kwargs)
                assert result["kpis"]["total_expense"] == 24


def test_postgres_standard_database_url_uses_installed_driver(pg_engine):
    engine, _ = pg_engine
    url = make_url(os.environ["FAMLEDGER_TEST_PG_URL"]).set(drivername="postgresql")
    env = dict(os.environ, DATABASE_URL=url.render_as_string(hide_password=False))
    result = subprocess.run([str(Path(__file__).resolve().parents[2] / ".venv/bin/python"), "-c",
                             "import database; from sqlalchemy import text; "
                             "assert database.engine.dialect.driver == 'psycopg'; "
                             "connection = database.engine.connect(); "
                             "assert connection.execute(text('SELECT 1')).scalar() == 1; "
                             "connection.close()"],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_postgres_schema_migration_boolean_defaults_and_version(pg_engine, monkeypatch):
    from services.schema import sync_schema, set_db_schema_version, get_db_schema_version, SCHEMA_VERSION
    engine, _ = pg_engine
    import database
    # A supplied engine must determine the dialect even when the app uses SQLite.
    monkeypatch.setattr(database, "is_sqlite", True)
    metadata = MetaData()
    Table("boolean_probe", metadata, Column("id", Integer, primary_key=True),
          Column("disabled", Boolean, nullable=False, default=False),
          Column("enabled", Boolean, nullable=False, default=True))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE boolean_probe(id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO boolean_probe(id) VALUES(1)"))
    statements = sync_schema(engine, metadata)
    assert len(statements) == 2
    with engine.connect() as connection:
        assert connection.execute(text("SELECT disabled, enabled FROM boolean_probe")).one() == (False, True)
    assert sync_schema(engine, metadata) == []
    set_db_schema_version(engine)
    set_db_schema_version(engine)
    assert get_db_schema_version(engine) == SCHEMA_VERSION


def test_postgres_pending_invitation_unique_constraint(pg_engine):
    engine, _ = pg_engine
    family_id, owner_id, _ = seed_household(engine)
    with Session(engine) as session:
        guest = User(username="pg_guest", display_name="Guest")
        session.add(guest)
        session.flush()
        guest_id = guest.id
        session.add(FamilyInvitation(family_id=family_id, inviter_user_id=owner_id, invitee_user_id=guest_id))
        session.commit()
        session.add(FamilyInvitation(family_id=family_id, inviter_user_id=owner_id, invitee_user_id=guest_id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(FamilyInvitation(family_id=family_id, inviter_user_id=owner_id,
                                     invitee_user_id=guest_id, status="canceled"))
        session.commit()
        assert len(session.exec(select(FamilyInvitation)).all()) == 2


def test_postgres_concurrent_repayments_preserve_remaining_amount(pg_engine):
    from routes.v1_debts import repay_personal_debt, PersonalDebtRepay
    engine, _ = pg_engine
    family_id, user_id, _ = seed_household(engine)
    with Session(engine) as session:
        debt = PersonalDebt(family_id=family_id, owner_id=user_id, counterparty="Partner", debt_type="borrow",
                            principal_amount=Decimal("100"), remaining_amount=Decimal("100"), borrowed_date=date.today())
        session.add(debt)
        session.commit()
        debt_id = debt.id
    barrier = threading.Barrier(2)
    def repay(_):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                repay_personal_debt(debt_id, PersonalDebtRepay(amount=Decimal("60")),
                                   session=session, user_or_ctx="pg_owner")
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(repay, range(2))) == [200, 400]
    with Session(engine) as session:
        assert session.get(PersonalDebt, debt_id).remaining_amount == Decimal("40")


def test_postgres_concurrent_refunds_do_not_exceed_original(pg_engine):
    from routes.v1_transactions import create_or_ingest_transaction
    engine, _ = pg_engine
    _, _, account_id = seed_household(engine)
    with Session(engine) as session:
        original = Transaction(account_id=account_id, amount=Decimal("100"), narration="Shop",
                               currency="CNY", transacted_at=date.today())
        session.add(original)
        session.commit()
        original_id = original.id
    barrier = threading.Barrier(2)
    def refund(_):
        body = json.dumps({"account": str(account_id), "amount": 60, "transaction_type": "refund",
                           "narration": "Shop refund", "refund_of_transaction_id": str(original_id)}).encode()
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        request = Request({"type": "http", "method": "POST", "path": "/api/v1/transactions", "headers": []}, receive)
        with Session(engine) as session:
            barrier.wait(timeout=10)
            return asyncio.run(create_or_ingest_transaction(request, session=session, user_or_ctx="pg_owner"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(refund, range(2)))) == 2
    with Session(engine) as session:
        allocations = session.exec(select(RefundAllocation)).all()
        assert sorted(row.allocated_amount for row in allocations) == [Decimal("40"), Decimal("60")]
        assert sum(row.allocated_amount for row in allocations) == Decimal("100")


def test_postgres_concurrent_invitations_have_one_family_winner(pg_engine):
    from routes.v1_family import accept_invitation
    engine, _ = pg_engine
    with Session(engine) as session:
        families = [Family(name="One"), Family(name="Two")]
        session.add_all(families)
        session.flush()
        owners = [User(username=f"pg_owner_{i}", display_name="Owner", role="owner", family_id=family.id)
                  for i, family in enumerate(families)]
        guest = User(username="pg_guest", display_name="Guest")
        session.add_all([*owners, guest])
        session.flush()
        invitations = [FamilyInvitation(family_id=family.id, inviter_user_id=owner.id, invitee_user_id=guest.id,
                                        expires_at=datetime.now(timezone.utc) + timedelta(days=1))
                       for family, owner in zip(families, owners)]
        session.add_all(invitations)
        session.commit()
        ids = [invitation.id for invitation in invitations]
    barrier = threading.Barrier(2)
    def accept(invitation_id):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                accept_invitation(invitation_id, session=session, user_or_ctx="pg_guest")
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(accept, ids)) == [200, 400]
    with Session(engine) as session:
        assert sorted(row.status for row in session.exec(select(FamilyInvitation)).all()) == ["accepted", "canceled"]


def test_postgres_dump_and_restore_real_data_and_foreign_keys(pg_engine, tmp_path, monkeypatch):
    """Exercise the actual BackupManager with a PG18 client, then restore only test data."""
    from services.backup import BackupManager
    import database
    engine, schema = pg_engine
    container = os.getenv("FAMLEDGER_TEST_PG_CONTAINER")
    if container != "famledger-fix104-pg-verification":
        pytest.skip("Real dump/restore needs the dedicated verification container")
    mount_root = Path(os.environ["FAMLEDGER_TEST_PG_MOUNT"]).resolve()
    tmp_path.resolve().relative_to(mount_root)
    _, _, account_id = seed_household(engine)
    with Session(engine) as session:
        session.add(Transaction(account_id=account_id, amount=Decimal("123.4567"), narration="Restore precision",
                                currency="CNY", transacted_at=date.today()))
        session.commit()
    # This wrapper only maps the dedicated test client's file and connection to its container.
    executable = tmp_path / "pg_dump"
    executable.write_text(
        "#!/usr/bin/env python3\nimport pathlib, subprocess, sys\n"
        f"args = sys.argv[1:]\nroot = pathlib.Path({str(mount_root)!r})\n"
        "if '--dbname' in args:\n    i = args.index('--dbname')\n"
        "    args[i+1] = 'postgresql://postgres@127.0.0.1:5432/fix104_verify'\n"
        "if '-f' in args:\n    i = args.index('-f')\n"
        "    args[i+1] = '/verify/' + str(pathlib.Path(args[i+1]).resolve().relative_to(root))\n"
        f"if '--version' not in args: args.extend(['--schema', {schema!r}])\n"
        f"sys.exit(subprocess.call(['docker', 'exec', {container!r}, 'pg_dump', *args]))\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "DATABASE_URL", os.environ["FAMLEDGER_TEST_PG_URL"])
    manager = BackupManager(db_path=tmp_path / "unused.db", audit_log_path=tmp_path / "absent_audit",
                            backup_dir=tmp_path / "isolated-dump")
    archive = manager.create_backup()
    sql_file = archive / "famledger.sql"
    assert sql_file.stat().st_size > 0
    restore_db = "fix104_restore_" + uuid.uuid4().hex
    source_url = make_url(os.environ["FAMLEDGER_TEST_PG_URL"])
    control = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    restored_engine = None
    try:
        with control.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{restore_db}"'))
        subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", restore_db,
                        "--set", "ON_ERROR_STOP=1", "--file", "/verify/" + str(sql_file.relative_to(mount_root))],
                       capture_output=True, text=True, check=True, timeout=60)
        restored_engine = create_engine(source_url.set(database=restore_db),
                                       connect_args={"options": f"-csearch_path={schema}"})
        with Session(restored_engine) as session:
            assert session.exec(select(Transaction)).one().amount == Decimal("123.4567")
            assert session.get(Account, account_id).name == "Wallet"
            session.add(Transaction(account_id=uuid.uuid4(), amount=Decimal("1"),
                                    narration="Foreign key probe", transacted_at=date.today()))
            with pytest.raises(IntegrityError) as error:
                session.commit()
            assert error.value.orig.sqlstate == "23503"
            session.rollback()
    finally:
        if restored_engine is not None:
            restored_engine.dispose()
        with control.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{restore_db}"'))
        control.dispose()


def test_postgres_concurrent_foreign_refund_native_quota(pg_engine):
    from routes.v1_transactions import ingest_transaction, TransactionIn
    engine, _ = pg_engine
    _, _, account_id = seed_household(engine)
    with Session(engine) as session:
        original = ingest_transaction(TransactionIn(account=str(account_id), amount='100', currency='USD',
            settlement_amount='700', settlement_currency='CNY', narration='Native purchase'), session, 'pg_owner')
        session.commit()
        original_id = original['id']
    barrier = threading.Barrier(2)
    def refund(_):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            result = ingest_transaction(TransactionIn(account=str(account_id), amount='60', currency='USD',
                settlement_amount='432', settlement_currency='CNY', narration='Native refund',
                transaction_type='refund', refund_of_transaction_id=original_id), session, 'pg_owner')
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(refund, range(2)))) == 2
    with Session(engine) as session:
        rows = session.exec(select(RefundAllocation)).all()
        assert sorted(r.allocated_amount for r in rows) == [40,60]
        assert sum(r.original_book_amount for r in rows) == 700
        assert sum(r.refund_original_amount for r in rows) == 100


def test_postgres_pending_push_and_confirmation_exactly_once(pg_engine, monkeypatch):
    import requests
    from models import PendingFxTransaction
    from routes.v1_transactions import ingest_transaction, TransactionIn
    from routes.v1_pending_fx import confirm_pending, SettlementConfirmation
    def offline(*args, **kwargs):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr('services.report_currency.requests.get', offline)
    engine, _ = pg_engine
    _, _, account_id = seed_household(engine)
    barrier = threading.Barrier(2)
    def push(_):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            result = ingest_transaction(TransactionIn(account=str(account_id), amount='100', currency='USD',
                external_id='single-source', narration='Pending purchase'), session, 'pg_owner')
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        pushes = list(pool.map(push, range(2)))
    assert pushes[0]['id'] == pushes[1]['id']
    row_id = uuid.UUID(pushes[0]['id'])
    barrier = threading.Barrier(2)
    def confirm(_):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            return confirm_pending(row_id, SettlementConfirmation(settlement_amount='705',settlement_currency='CNY'),
                                   session=session, user_or_ctx='pg_owner')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, range(2)))
    assert sorted(r['status'] for r in results) == ['created','posted']
    with Session(engine) as session:
        assert session.exec(select(Transaction)).one().amount == 705
        row = session.exec(select(PendingFxTransaction)).one()
        assert row.status == 'posted' and row.posted_transaction_id is not None

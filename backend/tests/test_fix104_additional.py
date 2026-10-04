"""Regressions for the eleven additionally requested bug104 issues."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from importlib.metadata import version

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient
from packaging.version import Version
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.requests import Request

from models import (Account, AccountShare, Category, Family, Loan, PersonalDebt,
                    RefundAllocation, Rule, Tag, Transaction, TransactionSplit, User)
from test_fix104_regressions import setup_accounts


def test_patched_parser_dependencies_and_file_ranges(tmp_path):
    assert Version(version('starlette')) >= Version('0.49.1')
    assert Version(version('python-multipart')) >= Version('0.0.27')
    path = tmp_path / 'asset.txt'
    path.write_bytes(b'0123456789')
    app = FastAPI()
    @app.get('/asset')
    def asset():
        return FileResponse(path)
    with TestClient(app) as client:
        response = client.get('/asset', headers={'Range': 'bytes=2-5'})
        assert response.status_code == 206 and response.content == b'2345'
        assert client.get('/asset', headers={'Range': 'bytes=100-200'}).status_code == 416


def test_avatar_rejects_auth_and_oversize_before_parsing(client, auth_client_a, monkeypatch):
    import auth
    def forbidden(*args, **kwargs):
        raise AssertionError('Multipart parser must not run')
    monkeypatch.setattr(Request, 'form', forbidden)
    assert client.post('/api/auth/avatar', content=b'unparsed').status_code == 401
    assert auth_client_a.post('/api/auth/avatar', content=b'unparsed',
        headers={'Content-Length': str(auth.MAX_FILE_SIZE + 65537)}).status_code == 413
    chunks = iter([b'x' * 1024] * ((auth.MAX_FILE_SIZE + 65536) // 1024 + 1))
    assert auth_client_a.post('/api/auth/avatar', content=chunks,
        headers={'Content-Type': 'multipart/form-data; boundary=x'}).status_code == 413


@pytest.mark.parametrize('endpoint', ['/api/v1/loans', '/api/v1/debts/loans'])
@pytest.mark.parametrize('opening', [1000, 700, 0])
def test_new_loan_preserves_opening_after_activity(auth_client_a, db, endpoint, opening):
    setup_accounts(db)
    result = auth_client_a.post(endpoint, json={'name': 'Loan baseline', 'original_principal': 1000,
        'current_balance': opening, 'start_date': date.today().isoformat()})
    assert result.status_code == 200, result.text
    from uuid import UUID
    account_id = UUID(result.json()['account_id'])
    initial = db.exec(select(Transaction).where(Transaction.account_id == account_id)).all()
    assert len(initial) == (1 if opening else 0)
    if initial:
        assert initial[0].amount == opening and initial[0].excluded_from_stats
        assert initial[0].extra['is_initial'] is True
    if opening:
        response = auth_client_a.post('/api/v1/transactions', json={'account': str(account_id),
            'amount': 100, 'transaction_type': 'income', 'narration': 'Loan repayment'})
        assert response.status_code == 200, response.text
        for _ in range(2):
            detail = auth_client_a.get(f'/api/v1/accounts/{account_id}')
            assert detail.status_code == 200, detail.text
            assert Decimal(detail.json()['account']['balance']) == opening - 100
        loans = auth_client_a.get('/api/v1/loans').json()['loans']
        loan = next(item for item in loans if item['account_id'] == str(account_id))
        assert Decimal(loan['current_balance']) == opening - 100
        assert len(db.exec(select(Transaction).where(Transaction.account_id == account_id)).all()) == 2


def make_cards(db):
    family, alice, bob, accounts = setup_accounts(db)
    primary, child = accounts
    for account in accounts:
        account.account_type = 'credit_card'
        account.classification = 'liability'
    child.parent_account_id = primary.id
    child.owner_id = bob.id
    primary.institution_name = 'Bank A'
    child.institution_name = 'Bank B'
    db.add_all(accounts)
    db.add(AccountShare(account_id=child.id, user_id=alice.id, permission='read_only'))
    db.add(Transaction(account_id=child.id, amount=Decimal('100'), currency='CNY',
        narration='Daily purchase', transaction_type='expense', transacted_at=date.today()))
    db.commit()
    return family, alice, bob, primary, child


def test_hidden_primary_still_counts_child(auth_client_b, db):
    make_cards(db)
    result = auth_client_b.get('/api/v1/dashboard/summary')
    assert result.status_code == 200, result.text
    assert result.json()['balance_sheet']['total_liabilities'] == 100
    analytics = auth_client_b.get('/api/v1/analytics/report')
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()['net_worth']['liabilities_total'] == 100
    card = auth_client_b.get('/api/v1/accounts').json()['accounts'][0]
    assert Decimal(card['report_own_balance']) == 100 and card['report_included']


def test_report_scope_and_bank_groups_count_own_ledgers(auth_client_a, db):
    _, _, _, primary, child = make_cards(db)
    result = auth_client_a.get('/api/v1/dashboard/summary').json()['balance_sheet']
    assert result['total_liabilities'] == 100
    banks = {group['name']: group['total'] for group in result['by_institution']['liabilities']['groups']}
    assert banks == {'Bank A': 0, 'Bank B': 100}
    child.exclude_from_reports = True
    db.add(child)
    db.commit()
    result = auth_client_a.get('/api/v1/dashboard/summary').json()['balance_sheet']
    assert result['total_liabilities'] == 0
    # Account detail continues to describe the entire visible master bill.
    detail = auth_client_a.get(f'/api/v1/accounts/{primary.id}').json()
    assert Decimal(detail['account']['balance']) == 100
    accounts = auth_client_a.get('/api/v1/accounts').json()['accounts']
    assert sum(Decimal(a['report_own_balance']) for a in accounts if a['report_included']) == 0


def test_manual_provenance_survives_rules(auth_client_a, db):
    from services.rules.actions import ActionExecutor
    family, _, _, accounts = setup_accounts(db)
    category = Category(family_id=family.id, name='Human category')
    replacement = Category(family_id=family.id, name='Rule category')
    db.add_all([category, replacement])
    db.flush()
    txn = Transaction(account_id=accounts[0].id, amount=Decimal('100'), narration='Imported', category_id=replacement.id, transacted_at=date.today())
    db.add(txn)
    db.commit()
    result = auth_client_a.patch(f'/api/v1/transactions/{txn.id}', json={'name': 'Human name', 'category_id': str(category.id)})
    assert result.status_code == 200, result.text
    db.refresh(txn)
    assert txn.merchant_source == txn.category_source == 'manual'
    changes = ActionExecutor.apply_actions([{'type':'set_merchant','value':'Rule name'},
        {'type':'set_category','value':str(replacement.id)}], txn, session=db)
    assert not changes and txn.narration == 'Human name' and txn.category_id == category.id
    result = auth_client_a.post(f'/api/v1/transactions/{txn.id}/split', json={'splits':[
        {'category_id':str(category.id), 'amount':60}, {'category_id':str(replacement.id),'amount':40}]})
    assert result.status_code == 200, result.text
    db.refresh(txn)
    assert txn.category_source == 'manual'


def test_manual_pair_and_candidates_use_transfer_direction(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    txns = [Transaction(account_id=accounts[index % 2].id, amount=Decimal('100'), narration='Transfer',
        transaction_type='transfer', currency='CNY', transacted_at=date.today(), extra={'direction': direction})
        for index, direction in enumerate(['outflow', 'outflow', 'inflow'])]
    # The incoming counterpart must live in a different account from the source.
    txns[2].account_id = accounts[1].id
    db.add_all(txns)
    db.commit()
    result = auth_client_a.post('/api/v1/transfers/manual-pair', json={
        'outflow_transaction_id': str(txns[0].id), 'inflow_transaction_id': str(txns[1].id)})
    assert result.status_code == 400, result.text
    candidates = auth_client_a.get(f'/api/v1/transfers/candidates?transaction_id={txns[0].id}').json()
    assert candidates['source_transaction']['is_outflow']
    assert [row['id'] for row in candidates['candidates']] == [str(txns[2].id)]
    detail = auth_client_a.get(f'/api/v1/transactions/{txns[2].id}').json()
    assert detail['funds_direction'] == 'inflow'
    result = auth_client_a.post('/api/v1/transfers/manual-pair', json={
        'outflow_transaction_id': str(txns[0].id), 'inflow_transaction_id': str(txns[2].id)})
    assert result.status_code == 200, result.text


def test_rule_final_type_drives_refund_matching(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    original = Transaction(account_id=accounts[0].id, amount=Decimal('100'), narration='Original', transacted_at=date.today())
    db.add(original)
    db.add(Rule(family_id=family.id, name='Refund is income', conditions={'field':'transaction_type','operator':'equals','value':'refund'},
        actions=[{'type':'set_transaction_type','value':'income'}]))
    db.commit()
    response = auth_client_a.post('/api/v1/transactions', json={'account':str(accounts[0].id), 'amount':50,
        'transaction_type':'refund', 'narration':'Original refund', 'refund_of_transaction_id':str(original.id)})
    assert response.status_code == 200, response.text
    from uuid import UUID
    saved = db.get(Transaction, UUID(response.json()['id']))
    assert saved.transaction_type == 'income' and saved.refund_of_transaction_id is None
    assert not db.exec(select(RefundAllocation)).all()


def test_rules_cannot_generate_undefined_adjustment(auth_client_a, db):
    setup_accounts(db)
    response = auth_client_a.post('/api/v1/rules', json={'name':'Bad adjustment',
        'conditions':{'field':'amount','operator':'>','value':0},
        'actions':[{'type':'set_transaction_type','value':'adjustment'}]})
    assert response.status_code == 400, response.text


def test_auto_pair_cannot_reverse_expense_using_direction_metadata(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    expense = Transaction(account_id=accounts[1].id, amount=Decimal('100'), narration='转入商品消费',
        transaction_type='expense', transacted_at=date.today(), extra={'direction':'inflow'})
    db.add(expense)
    db.commit()
    result = auth_client_a.post('/api/v1/transactions', json={'account':str(accounts[0].id),
        'amount':100, 'narration':'转出', 'transaction_type':'transfer', 'extra':{'direction':'outflow'}})
    assert result.status_code == 200, result.text
    db.refresh(expense)
    assert expense.transaction_type == 'expense' and expense.transfer_id is None


@pytest.mark.parametrize('action', ['create', 'leave', 'dissolve'])
def test_family_migration_is_atomic_even_after_seeding(db, monkeypatch, action):
    from routes import v1_family
    family, alice, bob, accounts = setup_accounts(db)
    if action != 'dissolve':
        bob.role = 'owner'
        alice.role = 'member'
        db.add_all([alice, bob])
        db.commit()
    before_ids = {f.id for f in db.exec(select(Family)).all()}
    real_migrate = v1_family.migrate_user_to_family
    calls = []
    def fail_late(*args, **kwargs):
        calls.append(1)
        if action != 'dissolve' or len(calls) == 2:
            raise RuntimeError('Injected migration failure')
        return real_migrate(*args, **kwargs)
    monkeypatch.setattr(v1_family, 'migrate_user_to_family', fail_late)
    with pytest.raises(RuntimeError, match='Injected migration'):
        if action == 'create':
            v1_family.create_family(v1_family.FamilyCreateRequest(name='Must roll back'), session=db, user_or_ctx='alice')
        elif action == 'leave':
            v1_family.leave_family(session=db, user_or_ctx='alice')
        else:
            v1_family.delete_family(session=db, user_or_ctx='alice')
    db.rollback()
    assert {f.id for f in db.exec(select(Family)).all()} == before_ids
    db.refresh(alice)
    db.refresh(bob)
    assert alice.family_id == bob.family_id == family.id
    assert all(db.get(Account, account.id).family_id == family.id for account in accounts)
    assert db.get(Family, family.id).status == 'active'


def test_invalid_first_account_does_not_commit_personal_space(db):
    from uuid import uuid4
    from routes.v1_accounts import AccountCreate, create_account
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    assert alice.family_id is None
    before = {f.id for f in db.exec(select(Family)).all()}
    with pytest.raises(HTTPException):
        create_account(AccountCreate(name='Invalid', account_type='checking', parent_account_id=str(uuid4())),
                       session=db, user_or_ctx='alice')
    db.rollback()
    db.refresh(alice)
    assert alice.family_id is None
    assert {f.id for f in db.exec(select(Family)).all()} == before


def test_category_migration_keeps_ancestors_and_distinct_paths(db):
    from services.tenant_migration import remap_categories_and_tags
    family, _, _, accounts = setup_accounts(db)
    target = Family(name='Destination')
    db.add(target)
    db.flush()
    parents = [Category(family_id=family.id, name=name, color='#112233') for name in ['Food', 'Travel']]
    db.add_all(parents)
    db.flush()
    children = [Category(family_id=family.id, name='Tickets', parent_id=parent.id, icon='T') for parent in parents]
    db.add_all(children)
    db.flush()
    txns = [Transaction(account_id=accounts[0].id, narration='Purchase', amount=Decimal('10'),
        transacted_at=date.today(), category_id=child.id, tags=['Old label']) for child in children]
    db.add_all(txns)
    db.add(Tag(family_id=family.id, name='Stable label', aliases=['Old label'], color='#abcdef', is_archived=True))
    db.commit()
    remap_categories_and_tags(db, [accounts[0].id], target.id, source_family_id=family.id)
    db.flush()
    mapped = [db.get(Category, txn.category_id) for txn in txns]
    assert mapped[0].id != mapped[1].id
    assert [db.get(Category, category.parent_id).name for category in mapped] == ['Food', 'Travel']
    assert all(db.get(Category, category.parent_id).color == '#112233' for category in mapped)
    copied_tag = db.exec(select(Tag).where(Tag.family_id == target.id)).one()
    assert copied_tag.color == '#abcdef' and copied_tag.aliases == ['Old label'] and copied_tag.is_archived
    assert all(txn.tags == ['Stable label'] for txn in txns)
    remap_categories_and_tags(db, [accounts[0].id], target.id, source_family_id=family.id)
    assert len(db.exec(select(Category).where(Category.family_id == target.id)).all()) == 4


@pytest.mark.parametrize('refund_amount', [50, 150])
def test_different_category_refunds_preserve_signed_totals(refund_amount):
    from services.stats_engine import compute_netted_category_distribution
    from uuid import uuid4
    dining = Category(id=uuid4(), name='餐饮美食')
    expenses = [Transaction(amount=Decimal('100'), category_id=dining.id, narration='Dinner')]
    refunds = [Transaction(amount=Decimal(str(refund_amount)), narration='Unlinked credit', transaction_type='refund')]
    rows, net, _, _ = compute_netted_category_distribution(expenses, refunds, {dining.id: dining})
    assert sum(item['amount'] for item in rows) == net == 100 - refund_amount
    assert sum(item['percentage'] for item in rows) == 100
    assert any(item['is_refund_credit'] and item['amount'] < 0 for item in rows)


def test_allocated_refund_uses_original_split_categories_across_periods(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    categories = [Category(family_id=family.id, name=name) for name in ['Custom A', 'Custom B']]
    db.add_all(categories)
    db.flush()
    original = Transaction(account_id=accounts[0].id, transacted_at=date(2020,1,1),
        narration='Old purchase', amount=Decimal('100'), is_split=True)
    refund = Transaction(account_id=accounts[0].id, transacted_at=date(2020,2,1),
        narration='Uncategorized refund', amount=Decimal('50'), transaction_type='refund')
    db.add_all([original, refund])
    db.flush()
    db.add_all([TransactionSplit(transaction_id=original.id, category_id=category.id, amount=Decimal(str(amount)))
        for category, amount in zip(categories, [60, 40])])
    db.add(RefundAllocation(refund_transaction_id=refund.id, original_transaction_id=original.id, allocated_amount=Decimal('50')))
    db.commit()
    query = '?period=custom&start_date=2020-02-01&end_date=2020-02-28'
    response = auth_client_a.get('/api/v1/dashboard/summary' + query)
    assert response.status_code == 200, response.text
    outflows = response.json()['outflows']
    assert outflows['total'] == -50
    assert {row['name']:row['amount'] for row in outflows['categories']} == {'Custom A':-30, 'Custom B':-20}
    response = auth_client_a.get('/api/v1/analytics/report' + query)
    assert response.status_code == 200, response.text
    assert response.json()['kpis']['total_expense'] == -50


def test_concurrent_debt_repayments_cannot_lose_updates(tmp_path):
    from routes.v1_debts import repay_personal_debt, PersonalDebtRepay
    engine = create_engine(f'sqlite:///{tmp_path / "repayments.db"}', connect_args={'check_same_thread':False,'timeout':10})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        family = Family(name='Concurrent household')
        session.add(family)
        session.flush()
        user = User(username='borrower', display_name='Borrower', role='owner', family_id=family.id)
        session.add(user)
        session.flush()
        debt = PersonalDebt(family_id=family.id, owner_id=user.id, counterparty='Partner', debt_type='borrow',
            principal_amount=Decimal('100'), remaining_amount=Decimal('100'), borrowed_date=date.today())
        session.add(debt)
        session.commit()
        debt_id = debt.id
    def repay(_):
        with Session(engine) as session:
            try:
                repay_personal_debt(debt_id, PersonalDebtRepay(amount=Decimal('60')), session=session, user_or_ctx='borrower')
                return 200
            except HTTPException as exc:
                return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(repay, [1,2])) == [200,400]
        with Session(engine) as session:
            assert session.get(PersonalDebt, debt_id).remaining_amount == 40
    finally:
        engine.dispose()


def test_password_reset_cli_uses_current_password_format(db, monkeypatch):
    import auth
    import cli_reset_password
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    old_version = alice.session_version
    monkeypatch.setattr(cli_reset_password, 'engine', db.get_bind())
    monkeypatch.setattr('builtins.input', lambda prompt: 'alice')
    monkeypatch.setattr(cli_reset_password.getpass, 'getpass', lambda prompt: '新密码' * 40)
    cli_reset_password.main()
    db.refresh(alice)
    assert auth._check_password('新密码' * 40, alice.password_hash)
    assert alice.session_version == old_version + 1


def test_concurrent_automatic_refunds_share_allocation_lock(tmp_path):
    from routes.v1_transactions import create_or_ingest_transaction
    import json
    engine = create_engine(f'sqlite:///{tmp_path / "refunds.db"}', connect_args={'check_same_thread':False,'timeout':10})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        family = Family(name='Concurrent refund household')
        session.add(family)
        session.flush()
        user = User(username='buyer', display_name='Buyer', role='owner', family_id=family.id)
        session.add(user)
        session.flush()
        account = Account(name='Wallet', family_id=family.id, owner_id=user.id, account_type='checking')
        session.add(account)
        session.flush()
        original = Transaction(account_id=account.id, amount=Decimal('100'), narration='Shop', transacted_at=date.today())
        session.add(original)
        session.commit()
        account_id, original_id = account.id, original.id
    def refund(_):
        body = json.dumps({'account':str(account_id), 'amount':60, 'transaction_type':'refund',
                           'narration':'Shop refund', 'refund_of_transaction_id':str(original_id)}).encode()
        async def receive():
            return {'type':'http.request','body':body,'more_body':False}
        request = Request({'type':'http','method':'POST','path':'/api/v1/transactions', 'headers':[]}, receive)
        with Session(engine) as session:
            return asyncio.run(create_or_ingest_transaction(request, session=session, user_or_ctx='buyer'))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert len(list(pool.map(refund, [1,2]))) == 2
        with Session(engine) as session:
            allocations = session.exec(select(RefundAllocation)).all()
            assert sorted(a.allocated_amount for a in allocations) == [40,60]
            assert sum(a.allocated_amount for a in allocations) == 100
    finally:
        engine.dispose()

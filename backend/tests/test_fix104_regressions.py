"""Security and accounting regression tests for the requested bug104 fixes."""
import base64
import io
import json
import sqlite3
import tarfile
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.requests import Request

import auth
from models import (Account, AccountShare, Category, ExchangeRateSnapshot, Family,
                    FamilyInvitation, RejectedTransfer, Transaction, TransactionSplit, Transfer, User, UserPreference)
from services.report_currency import ReportCurrency, persist_fx_cache
from services.report_period import resolve_period


def setup_accounts(db, currency='CNY'):
    family = Family(name='Regression household')
    db.add(family)
    db.flush()
    alice = db.exec(select(User).where(User.username == 'alice')).one()
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    alice.family_id = bob.family_id = family.id
    alice.role = 'owner'
    db.add_all([alice, bob])
    db.flush()
    accounts = [Account(name='Primary', family_id=family.id, owner_id=alice.id, currency=currency, account_type='checking'),
                Account(name='Secondary', family_id=family.id, owner_id=alice.id, currency=currency, account_type='checking')]
    db.add_all(accounts)
    db.commit()
    return family, alice, bob, accounts


def test_csrf_rejects_sibling_origin_and_simple_writes(auth_client_a):
    assert auth_client_a.put('/api/user-preferences', json={'currency':'CNY'},
                             headers={'Origin':'http://evil.testserver'}).status_code == 403
    del auth_client_a.headers['X-FamLedger-CSRF']
    assert auth_client_a.put('/api/user-preferences', json={'currency':'CNY'}).status_code == 403
    assert auth_client_a.put('/api/user-preferences', json={'currency':'CNY'},
                             headers={'Origin':'http://testserver'}).status_code == 200


@pytest.mark.parametrize('claims,info', [
    ({'iss':'https://evil.example'}, {}), ({'aud':'other-client'}, {}),
    ({'nonce':'wrong'}, {}), ({'exp':1}, {}), ({'sub':''}, {}),
    ({'aud':['client','other'], 'azp':'other'}, {}), ({'at_hash':'wrong'}, {}),
    ({}, {'sub':'someone-else'}),
])
def test_oidc_rejects_invalid_signed_identity(client, db, oidc_flow, claims, info):
    flow = oidc_flow(claims_update=claims, userinfo_update=info)
    result = client.get(flow.path, follow_redirects=False)
    assert result.status_code == 401, result.text
    assert db.exec(select(User).where(User.username == flow.username)).first() is None


def test_oidc_pkce_and_single_use(client, oidc_flow):
    flow = oidc_flow()
    assert flow.query['code_challenge_method'] == ['S256'] and flow.query['nonce']
    assert client.get(flow.path, follow_redirects=False).status_code == 302
    count = len(flow.calls)
    assert client.get(flow.path, follow_redirects=False).status_code == 400
    assert len(flow.calls) == count


def test_cookie_tracks_id_and_does_not_authorize_reused_username(db):
    user = db.exec(select(User).where(User.username == 'alice')).one()
    token = auth._make_token(user.username, user_id=user.id)
    old_id = user.id
    user.username = 'renamed'
    db.add(user)
    db.commit()
    db.add(User(username='alice', display_name='Replacement'))
    db.commit()
    assert auth._verify_token(token, db)['uid'] == str(old_id)
    assert auth._verify_token(token, db)['user'] == 'renamed'
    db.delete(user)
    db.commit()
    assert auth._verify_token(token, db) is None


def test_logout_revokes_refreshed_copies_only(auth_client_a, db):
    original = auth_client_a.cookies.get(auth.SESSION_COOKIE)
    data = auth._verify_token(original, db)
    refreshed = auth._make_token(data['user'], user_id=data['uid'], session_id=data['sid'])
    separate = auth._make_token(data['user'], user_id=data['uid'])
    assert auth_client_a.post('/api/auth/logout').status_code == 200
    assert auth._verify_token(original, db) is None
    assert auth._verify_token(refreshed, db) is None
    assert auth._verify_token(separate, db)


def test_long_unicode_password_distinguishes_suffixes():
    prefix = '长密码' * 30
    hashed = auth.hash_password(prefix+'one')
    assert auth._check_password(prefix+'one', hashed)
    assert not auth._check_password(prefix+'two', hashed)


def test_first_registration_is_atomic_across_connections(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "bootstrap.db"}', connect_args={'check_same_thread':False, 'timeout':10})
    SQLModel.metadata.create_all(engine)
    def register(index):
        request = Request({'type':'http', 'method':'POST', 'path':'/api/auth/register',
                           'headers':[], 'client':('127.0.0.1', 1)})
        with Session(engine) as session:
            data = auth.RegisterRequest(username=f'first_{index}', display_name=f'First {index}', password='Password123!',
                                        security_question='Question?', security_answer='answer')
            return auth.register(data, Response(), session)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(register, [1,2]))
        with Session(engine) as session:
            users = session.exec(select(User)).all()
            assert len(users) == 2
            assert sum(u.role == 'admin' for u in users) == 1
            assert sum(u.family_id is not None for u in users) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize('endpoint', ['/api/v1/transactions', '/api/v1/categories'])
@pytest.mark.parametrize('body', ['[1,2]', '{invalid', '{"name":123}'])
def test_manual_json_errors_are_422(auth_client_a, db, endpoint, body):
    setup_accounts(db)
    result = auth_client_a.post(endpoint, content=body, headers={'Content-Type':'application/json'})
    assert result.status_code == 422, result.text


@pytest.mark.parametrize('endpoint', ['/api/v1/dashboard/summary', '/api/v1/analytics/report'])
@pytest.mark.parametrize('query', ['selected_month=0000-01', 'period=custom&start_date=not-a-date',
                                  'period=custom&start_date=2026-09-20&end_date=2026-09-01'])
def test_reports_reject_invalid_dates(auth_client_a, endpoint, query):
    assert auth_client_a.get(endpoint+'?'+query).status_code == 422


def test_calendar_periods_and_history_before_2020(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    db.add_all([Transaction(narration='Test merchant', account_id=accounts[0].id, amount=Decimal('100'), transacted_at=date(2026,4,1)),
                Transaction(narration='Test merchant', account_id=accounts[0].id, amount=Decimal('25'), transacted_at=date(2019,12,31))])
    db.commit()
    dash = auth_client_a.get('/api/v1/dashboard/summary?period=6m&selected_month=2026-09').json()
    report = auth_client_a.get('/api/v1/analytics/report?period=6m&selected_month=2026-09').json()
    assert dash['period_dates'] == report['date_range'] == {'start':'2026-04-01', 'end':'2026-09-30'}
    assert dash['outflows']['total'] == report['kpis']['total_expense'] == 100
    assert auth_client_a.get('/api/v1/dashboard/summary?period=ALL').json()['outflows']['total'] == 125
    assert auth_client_a.get('/api/v1/analytics/report?period=ALL').json()['kpis']['total_expense'] == 125


def test_historical_fx_persists_and_database_hit_is_offline(db, monkeypatch):
    from services import report_currency
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        day = url.rsplit('/',1)[-1]
        amount = '8' if day == '2020-01-03' else '9'
        return SimpleNamespace(raise_for_status=lambda:None, json=lambda:{'base':'EUR','date':day,
                                                                          'rates':{'CNY':amount, 'USD':'1', 'HKD':'7'}})
    monkeypatch.setattr(report_currency.requests, 'get', get)
    money = ReportCurrency(db, currency='CNY')
    assert money.amount(100, 'USD', date(2020,1,3)) == 800
    assert money.amount(100, 'USD', date(2020,1,6)) == 900
    persist_fx_cache(db)
    assert calls == ['https://api.frankfurter.app/2020-01-03','https://api.frankfurter.app/2020-01-06']
    with Session(db.get_bind()) as fresh:
        offline = ReportCurrency(fresh, currency='CNY')
        assert offline.amount(100, 'USD', date(2020,1,3)) == 800
        assert offline.amount(100, 'HKD', date(2020,1,3)) == Decimal('800') / 7
    assert len(calls) == 2


def test_fx_weekend_retains_effective_day_and_never_uses_latest(db, monkeypatch):
    from services import report_currency
    monkeypatch.setattr(report_currency.requests, 'get', lambda url, **kwargs: SimpleNamespace(
        raise_for_status=lambda:None, json=lambda:{'base':'EUR','date':'2020-01-03','rates':{'USD':'1','CNY':'8'}}))
    money = ReportCurrency(db, currency='CNY')
    assert money.amount(10, 'USD', date(2020,1,4)) == 80
    persist_fx_cache(db)
    saved = db.get(ExchangeRateSnapshot, (date(2020,1,4),'EUR'))
    assert saved.effective_date == date(2020,1,3)


@pytest.mark.parametrize('rates', [{'USD':'0'}, {'USD':'NaN'}, {'USD':'Infinity'}, {'USD':'-1'}])
def test_bad_fx_quotes_are_not_saved(db, monkeypatch, rates):
    from services import report_currency
    monkeypatch.setattr(report_currency.requests, 'get', lambda url, **kwargs: SimpleNamespace(
        raise_for_status=lambda:None, json=lambda:{'base':'EUR','date':'2020-01-03','rates':rates}))
    with pytest.raises(HTTPException) as caught:
        ReportCurrency(db, currency='CNY').amount(10, 'USD', date(2020,1,3))
    assert caught.value.status_code == 502
    assert db.exec(select(ExchangeRateSnapshot)).all() == []


def test_reports_convert_splits_by_transaction_date_and_preserve_ledger(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db, 'USD')
    for day, cny in [(date(2020,1,3), '8'), (date.today(), '9')]:
        db.add(ExchangeRateSnapshot(requested_date=day, effective_date=day, rates={'EUR':'1','USD':'1','CNY':cny}))
    txn = Transaction(narration='Test merchant', account_id=accounts[0].id, amount=Decimal('100'), currency='USD', transacted_at=date(2020,1,3), is_split=True)
    db.add(txn)
    db.flush()
    db.add(TransactionSplit(transaction_id=txn.id, amount=Decimal('100')))
    db.commit()
    query = '?period=custom&start_date=2020-01-01&end_date=2020-01-31'
    dash = auth_client_a.get('/api/v1/dashboard/summary'+query)
    report = auth_client_a.get('/api/v1/analytics/report'+query)
    assert dash.status_code == report.status_code == 200, (dash.text, report.text)
    assert dash.json()['outflows']['total'] == report.json()['kpis']['total_expense'] == 800
    assert dash.json()['currency'] == report.json()['currency'] == 'CNY'
    db.refresh(txn)
    assert txn.currency == 'USD' and txn.amount == 100


def test_preference_does_not_change_collaborative_family_currency(auth_client_a, db):
    family, *_ = setup_accounts(db)
    assert auth_client_a.put('/api/user-preferences', json={'currency':'HKD'}).status_code == 200
    db.refresh(family)
    assert family.currency == 'CNY'


def test_edit_name_clear_category_and_rejected_pair_deletion(auth_client_a, db):
    family, _, _, accounts = setup_accounts(db)
    cat = Category(family_id=family.id, name='Child')
    db.add(cat); db.flush()
    first = Transaction(narration='Test merchant', account_id=accounts[0].id, category_id=cat.id, amount=Decimal('10'), transacted_at=date.today())
    second = Transaction(narration='Test merchant', account_id=accounts[1].id, amount=Decimal('11'), transacted_at=date.today())
    db.add_all([first,second]); db.flush()
    db.add(RejectedTransfer(outflow_transaction_id=first.id, inflow_transaction_id=second.id)); db.commit()
    response = auth_client_a.patch(f'/api/v1/transactions/{first.id}', json={'name':'Renamed','category_id':None})
    assert response.status_code == 200, response.text
    db.refresh(first)
    assert first.narration == 'Renamed' and db.get(Category, first.category_id).name == '其他'
    assert first.category_source == 'manual'
    response = auth_client_a.patch(f'/api/v1/transactions/{first.id}', json={'category_id':str(uuid.uuid4())})
    assert response.status_code == 400
    assert auth_client_a.delete(f'/api/v1/transactions/{first.id}').status_code == 200
    assert db.exec(select(RejectedTransfer)).all() == []


def test_nullable_category_parent_can_be_cleared(auth_client_a, db):
    family, *_ = setup_accounts(db)
    parent = Category(family_id=family.id,name='Parent'); db.add(parent); db.flush()
    child = Category(family_id=family.id,name='Child',parent_id=parent.id); db.add(child); db.commit()
    response = auth_client_a.patch(f'/api/v1/categories/{child.id}',json={'parent_id':None})
    assert response.status_code == 200, response.text
    db.refresh(child); assert child.parent_id is None


def test_legacy_join_route_is_removed(auth_client_a):
    assert auth_client_a.post('/api/v1/family/join',json={'family_name':'Anything'}).status_code == 404


def test_last_admin_cannot_escape_by_creating_family(auth_client_a, db):
    setup_accounts(db)
    response = auth_client_a.post('/api/v1/family/create',json={'name':'Escape','currency':'CNY'})
    assert response.status_code == 400, response.text


def test_invitation_rechecks_inviter_authority(client, db):
    from datetime import timedelta
    family, alice, bob, _ = setup_accounts(db)
    guest = User(username='guest',display_name='Guest'); db.add(guest); db.flush()
    inv = FamilyInvitation(family_id=family.id,inviter_user_id=alice.id,invitee_user_id=guest.id,
                           expires_at=datetime.now(timezone.utc)+timedelta(days=1))
    db.add(inv); db.commit()
    alice.role='member'; db.add(alice); db.commit()
    cookie = {auth.SESSION_COOKIE:auth._make_token(guest.username,user_id=guest.id)}
    assert client.post(f'/api/v1/family/invitations/{inv.id}/accept',cookies=cookie).status_code == 403
    db.refresh(guest); assert guest.family_id is None


def test_pending_invitation_unique_constraint(db):
    from datetime import timedelta
    family, alice, bob, _ = setup_accounts(db)
    values = dict(family_id=family.id,inviter_user_id=alice.id,invitee_user_id=bob.id,
                  expires_at=datetime.now(timezone.utc)+timedelta(days=1))
    db.add(FamilyInvitation(**values)); db.commit()
    db.add(FamilyInvitation(**values))
    with pytest.raises(IntegrityError): db.commit()
    db.rollback()


@pytest.mark.parametrize('condition', [{'operator':'and','rules':'bad'}, {'field':'amount','operator':'gt','value':'NaN'},
                                        {'field':'amount','operator':'between','value':[1]}, {'field':'amount','operator':'gt','value':'abc'}])
def test_malformed_rules_rejected_without_500(auth_client_a, db, condition):
    setup_accounts(db)
    result = auth_client_a.post('/api/v1/rules',json={'name':'Invalid','conditions':condition,'actions':[{'type':'set_note','value':'x'}]})
    assert result.status_code == 422, result.text


def test_sqlite_test_database_enforces_real_foreign_keys(db):
    assert db.execute(text('PRAGMA foreign_keys')).scalar() == 1
    db.add(Account(family_id=uuid.uuid4(),name='Invalid'))
    with pytest.raises(IntegrityError): db.commit()
    db.rollback()


def test_restore_rejects_missing_foreign_keys_even_without_declared_constraint():
    from services.data_integrity import sqlite_integrity_problems
    with sqlite3.connect(':memory:') as connection:
        connection.executescript('CREATE TABLE families(id TEXT PRIMARY KEY); CREATE TABLE accounts(id TEXT PRIMARY KEY,family_id TEXT); INSERT INTO accounts VALUES("a","missing");')
        assert sqlite_integrity_problems(connection)


@pytest.mark.parametrize('member_type', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_restore_rejects_links_and_devices(tmp_path, member_type):
    from services.portable import read_manifest
    archive=tmp_path/'malicious.tar'
    with tarfile.open(archive,'w') as handle:
        member=tarfile.TarInfo('uploads/evil'); member.type=member_type; member.linkname='../famledger.db'
        handle.addfile(member)
    with pytest.raises(RuntimeError): read_manifest(archive)


def test_personal_space_uses_explicit_current_schema_fields(db):
    family = Family(name='Personal space', is_solo=True, kind='personal')
    db.add(family); db.flush()
    user = User(username='personal', display_name='Personal', family_id=family.id)
    db.add(user); db.flush()
    family.personal_owner_user_id = user.id
    db.add(family); db.commit()
    assert family.kind == 'personal' and family.personal_owner_user_id == user.id


@pytest.mark.parametrize('client_major,success', [(17,False),(18,True),(19,True)])
def test_pg_dump_version_must_support_server(monkeypatch, client_major, success):
    from services import postgres_tools
    from contextlib import contextmanager
    @contextmanager
    def connect(): yield SimpleNamespace(execute=lambda query:SimpleNamespace(scalar=lambda:180001))
    monkeypatch.setattr(postgres_tools.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=f'pg_dump (PostgreSQL) {client_major}.1'))
    if success: postgres_tools.check_pg_dump_version('pg_dump',SimpleNamespace(connect=connect))
    else:
        with pytest.raises(RuntimeError): postgres_tools.check_pg_dump_version('pg_dump',SimpleNamespace(connect=connect))


def test_service_token_is_bound_to_configured_family_and_bill_capabilities(client, db, monkeypatch):
    family, _, _, accounts = setup_accounts(db)
    other = Family(name='Other household'); db.add(other); db.flush()
    foreign = Account(name='Private other',family_id=other.id,account_type='checking'); db.add(foreign); db.commit()
    monkeypatch.setattr(auth,'FAMLEDGER_API_TOKEN','production-bill-key')
    monkeypatch.setenv('FAMLEDGER_SERVICE_FAMILY_ID',str(family.id))
    headers={'X-Api-Key':'production-bill-key'}
    result=client.get('/api/v1/accounts',headers=headers)
    assert result.status_code == 200, result.text
    assert str(foreign.id) not in result.text
    assert client.get('/api/v1/auth/sso/admin/providers',headers=headers).status_code == 403
    assert client.delete(f'/api/v1/accounts/{accounts[0].id}',headers=headers).status_code == 403
    assert client.post('/api/v1/transactions',headers=headers,json={'account_id':str(foreign.id),'amount':'10',
                       'transacted_at':'2026-09-01','narration':'Attack','transaction_type':'expense'}).status_code == 403
    monkeypatch.delenv('FAMLEDGER_SERVICE_FAMILY_ID')
    assert client.get('/api/v1/accounts',headers=headers).status_code == 403


def test_transfer_historical_timestamp_and_same_account_edit(auth_client_a, db):
    _, _, _, accounts=setup_accounts(db)
    result=auth_client_a.post('/api/v1/transfers',json={'from_account_id':str(accounts[0].id),
        'to_account_id':str(accounts[1].id),'amount':'10','transacted_at':'2020-01-03','time':'01:30'})
    assert result.status_code == 200,result.text
    transfer=db.exec(select(Transfer)).one()
    out=db.get(Transaction,transfer.outflow_transaction_id)
    incoming=db.get(Transaction,transfer.inflow_transaction_id)
    assert out.transacted_at == date(2020,1,3)
    assert out.occurred_at.replace(tzinfo=None) == incoming.occurred_at.replace(tzinfo=None) == datetime(2020,1,2,17,30)
    response=auth_client_a.patch(f'/api/v1/transactions/{out.id}',json={'account_id':str(accounts[1].id)})
    assert response.status_code == 400,response.text
    bad=auth_client_a.post('/api/v1/transfers',json={'from_account_id':str(accounts[0].id),
        'to_account_id':str(accounts[1].id),'amount':'10','transacted_at':'not-a-date'})
    assert bad.status_code == 422


def test_opening_timestamp_is_stored_in_utc(db, monkeypatch):
    from routes import v1_accounts
    from zoneinfo import ZoneInfo
    _, _, _, accounts=setup_accounts(db)
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2020,1,3,1,30,tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(tz)
    monkeypatch.setattr(v1_accounts,'datetime',FixedDatetime)
    accounts[0].balance=Decimal('100'); db.add(accounts[0]); db.flush()
    v1_accounts._ensure_opening_balance_transaction(db,accounts[0]); db.commit()
    txn=db.exec(select(Transaction).where(Transaction.account_id==accounts[0].id)).one()
    assert txn.transacted_at == date(2020,1,3)
    assert txn.occurred_at.replace(tzinfo=None) == datetime(2020,1,2,17,30)


def test_export_honors_category_filter(auth_client_a, db):
    import openpyxl
    family,_,_,accounts=setup_accounts(db)
    categories=[Category(family_id=family.id,name='Food'),Category(family_id=family.id,name='Travel')]
    db.add_all(categories); db.flush()
    for index,cat in enumerate(categories):
        db.add(Transaction(account_id=accounts[0].id,narration=cat.name,category_id=cat.id,amount=Decimal('10'),transacted_at=date.today()))
    db.commit()
    result=auth_client_a.get(f'/api/export?category={categories[0].id}')
    assert result.status_code == 200,result.text
    workbook=openpyxl.load_workbook(io.BytesIO(result.content))
    rows=list(workbook.active.values)
    assert len(rows)==2 and rows[1][6]=='Food'


def test_tag_aliases_and_tombstones_resolve_private_history(auth_client_a, db):
    from models import Tag
    from services.tags import tag_resolver
    family,_,bob,accounts=setup_accounts(db)
    accounts[1].owner_id=bob.id; db.add(accounts[1]); db.flush()
    tag=Tag(family_id=family.id,name='Old'); db.add(tag); db.flush()
    txn=Transaction(account_id=accounts[1].id,narration='Private',amount=Decimal('10'),transacted_at=date.today(),tags=['Old'])
    db.add(txn); db.commit()
    response=auth_client_a.patch(f'/api/v1/tags/{tag.id}',json={'name':'New'})
    assert response.status_code == 200,response.text
    db.refresh(txn)
    db.refresh(tag)
    assert txn.tags==['Old']
    assert tag_resolver(db,family.id)(txn.tags)==['New']
    assert auth_client_a.delete(f'/api/v1/tags/{tag.id}').status_code==200
    db.refresh(tag)
    assert tag_resolver(db,family.id)(txn.tags)==[]


def test_anonymization_removes_debt_loan_and_split_personal_text(auth_client_a, db):
    from models import Loan, PersonalDebt
    family,alice,bob,accounts=setup_accounts(db)
    bob.role='owner'; db.add(bob)
    loan=Loan(account_id=accounts[0].id,original_amount=Decimal('100'),term_months=12,interest_rate=Decimal('0'),
              lender_name='SECRET BANK',start_date=date.today())
    debt=PersonalDebt(family_id=family.id,owner_id=alice.id,debt_type='lend',counterparty='SECRET NAME',
                       principal_amount=Decimal('50'),remaining_amount=Decimal('50'),borrowed_date=date.today(),notes='SECRET NOTE')
    txn=Transaction(account_id=accounts[0].id,narration='SECRET MERCHANT',amount=Decimal('10'),transacted_at=date.today())
    db.add_all([loan,debt,txn]); db.flush()
    split=TransactionSplit(transaction_id=txn.id,amount=Decimal('10'),notes='SECRET SPLIT'); db.add(split); db.commit()
    response=auth_client_a.request('DELETE','/api/auth/account',json={'password':'testpass_a','data_action':'anonymize'})
    assert response.status_code==200,response.text
    for record in [loan,debt,split]: db.refresh(record)
    assert loan.lender_name is None and debt.notes is None and debt.counterparty!='SECRET NAME' and split.notes is None


def test_admin_delete_cleans_primary_card_and_paired_transactions(admin_client_a, db):
    family,alice,bob,accounts=setup_accounts(db)
    alice.role='admin'; db.add(alice)
    accounts[0].owner_id=bob.id; accounts[0].account_type='credit_card'; accounts[0].classification='liability'
    accounts[1].account_type='credit_card'; accounts[1].classification='liability'; accounts[1].parent_account_id=accounts[0].id
    db.add_all(accounts); db.flush()
    out=Transaction(account_id=accounts[0].id,narration='Transfer out',amount=Decimal('10'),transacted_at=date.today(),transaction_type='transfer')
    incoming=Transaction(account_id=accounts[1].id,narration='Transfer in',amount=Decimal('10'),transacted_at=date.today(),transaction_type='transfer')
    db.add_all([out,incoming]); db.flush()
    transfer=Transfer(family_id=family.id,outflow_transaction_id=out.id,inflow_transaction_id=incoming.id,amount=Decimal('10'))
    db.add(transfer); db.flush(); out.transfer_id=incoming.transfer_id=transfer.id; db.add_all([out,incoming]); db.commit()
    response=admin_client_a.request('DELETE',f'/api/v1/family/members/{bob.id}',json={'admin_password':'testpass_a'})
    assert response.status_code==200,response.text
    db.refresh(accounts[1]); db.refresh(incoming)
    assert accounts[1].parent_account_id is None and incoming.transfer_id is None
    assert incoming.extra['direction']=='inflow' and incoming.transaction_type=='transfer'


def test_restoring_archive_respects_expanded_size_limit(tmp_path, monkeypatch):
    from services import portable
    monkeypatch.setattr(portable,'MAX_ARCHIVE_BYTES',16)
    archive=tmp_path/'large.tar'
    with tarfile.open(archive,'w') as handle:
        member=tarfile.TarInfo('uploads/large'); member.size=32; handle.addfile(member,io.BytesIO(b'x'*32))
    with pytest.raises(RuntimeError,match='limits'): portable.read_manifest(archive)


def test_report_fetches_missing_daily_rates_and_next_request_reads_database(auth_client_a, db, monkeypatch):
    from services import report_currency
    _,_,_,accounts=setup_accounts(db,'USD')
    db.add(Transaction(account_id=accounts[0].id,narration='Historic purchase',amount=Decimal('100'),
                       currency='USD',transacted_at=date(2020,1,3)))
    db.commit()
    calls=[]
    def get(url, **kwargs):
        calls.append(url)
        day=url.rsplit('/',1)[-1]
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'base':'EUR','date':day,
                    'rates':{'USD':'1','CNY':'8' if day=='2020-01-03' else '9'}})
    monkeypatch.setattr(report_currency.requests,'get',get)
    query='?period=custom&start_date=2020-01-01&end_date=2020-01-31'
    first=auth_client_a.get('/api/v1/dashboard/summary'+query)
    assert first.status_code==200,first.text
    assert first.json()['outflows']['total']==800
    assert first.json()['balance_sheet']['total_assets']==-900
    assert len(calls)==2
    assert len(db.exec(select(ExchangeRateSnapshot)).all())==2
    # Historical account valuation needs the month-end quote in addition to
    # transaction-date and today's quotes. Warm this distinct quote once.
    historical=auth_client_a.get('/api/v1/analytics/report'+query)
    assert historical.status_code==200,historical.text
    assert historical.json()['net_worth']['trend'][-1]['as_of']=='2020-01-31'
    assert len(calls)==3
    assert len(db.exec(select(ExchangeRateSnapshot)).all())==3
    def offline(*args,**kwargs): raise AssertionError('Cache hit must not make a network request')
    monkeypatch.setattr(report_currency.requests,'get',offline)
    second=auth_client_a.get('/api/v1/analytics/report'+query)
    assert second.status_code==200,second.text
    assert second.json()['kpis']['total_expense']==800
    assert second.json()['net_worth']['assets_total']==-900


def test_concurrent_accepts_have_one_winner_and_cancel_the_other_invitation(tmp_path):
    from datetime import timedelta
    from routes.v1_family import accept_invitation
    engine=create_engine(f'sqlite:///{tmp_path / "invitations.db"}', connect_args={'check_same_thread':False,'timeout':10})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        families=[Family(name='One'),Family(name='Two')]; session.add_all(families); session.flush()
        owners=[User(username=f'owner_{index}',display_name='Owner',role='owner',family_id=fam.id) for index,fam in enumerate(families)]
        guest=User(username='guest',display_name='Guest')
        session.add_all([*owners,guest]); session.flush()
        invitations=[FamilyInvitation(family_id=fam.id,inviter_user_id=owner.id,invitee_user_id=guest.id,
                         expires_at=datetime.now(timezone.utc)+timedelta(days=1)) for fam,owner in zip(families,owners)]
        session.add_all(invitations); session.commit()
        ids=[inv.id for inv in invitations]
    def accept(inv_id):
        with Session(engine) as session:
            try:
                accept_invitation(inv_id,session=session,user_or_ctx='guest')
                return 200
            except HTTPException as exc:
                return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(accept,ids))
        assert sorted(results)==[200,400]
        with Session(engine) as session:
            states=[inv.status for inv in session.exec(select(FamilyInvitation)).all()]
            assert sorted(states)==['accepted','canceled']
    finally: engine.dispose()


def test_development_lifespan_does_not_create_backups(monkeypatch):
    import asyncio
    import main
    monkeypatch.setenv('ENV','development')
    monkeypatch.setattr(main,'check_db_integrity',lambda:True)
    monkeypatch.setattr(main,'assert_schema_not_newer',lambda engine:None)
    monkeypatch.setattr(main,'create_db_and_tables',lambda:None)
    monkeypatch.setattr(main,'sync_schema',lambda engine:None)
    monkeypatch.setattr(main,'set_db_schema_version',lambda engine:None)
    monkeypatch.setattr('services.rules.defaults.initialize_existing_families',lambda session:None)
    def forbidden(*args,**kwargs): raise AssertionError('Development must not create backups')
    monkeypatch.setattr(main.BackupManager,'create_backup',forbidden)
    monkeypatch.setattr(main,'_assert_backup_mirror_usable',forbidden)
    async def run():
        async with main.lifespan(main.app): pass
    asyncio.run(run())


def test_old_password_hash_is_rejected_without_compatibility():
    import bcrypt
    legacy=bcrypt.hashpw(b'Password123!',bcrypt.gensalt()).decode()
    assert not auth._check_password('Password123!',legacy)
    assert auth._check_password('Password123!',auth.hash_password('Password123!'))


def test_invalid_transfer_timestamp_is_rejected(auth_client_a,db):
    _,_,_,accounts=setup_accounts(db)
    response=auth_client_a.post('/api/v1/transfers',json={'from_account_id':str(accounts[0].id),
        'to_account_id':str(accounts[1].id),'amount':'10','occurred_at':'not-a-time'})
    assert response.status_code==422,response.text

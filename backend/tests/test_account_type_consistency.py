"""Names do not classify accounts; reclassification cannot silently reverse money."""
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select
from models import Account, AccountShare, Transaction, User
from services.account_types import ACCOUNT_TYPES, repair_account_types


def create(client, kind='cash', balance='5400', name='贷款信用卡基金'):
    response = client.post('/api/v1/accounts', json={
        'name': name, 'account_type': kind, 'balance': str(balance),
        'currency': 'CNY', 'institution_name': 'Test bank',
    })
    assert response.status_code == 200, response.text
    return UUID(response.json()['id'])


def change(client, account_id, kind, entry='single', **extra):
    if entry == 'bulk':
        return client.patch('/api/v1/accounts/bulk/settings', json={
            'account_ids': [str(account_id)], 'account_type': kind, **extra,
        })
    return client.patch(f'/api/v1/accounts/{account_id}', json={'account_type': kind, **extra})


def balance(client, account_id):
    detail = client.get(f'/api/v1/accounts/{account_id}').json()
    row = next(row for row in client.get('/api/v1/accounts').json()['accounts'] if row['id'] == str(account_id))
    assert Decimal(row['balance']) == Decimal(detail['account']['balance'])
    return Decimal(row['balance'])


@pytest.mark.parametrize('kind,expected', [(' loan ', 'loan'), ('抵押贷款', 'loan'), ('借款', 'loan'),
    (' CREDIT ', 'credit_card'), ('微粒贷', 'loan'), ('其他负债', 'other_liability')])
def test_create_normalizes_type_and_opening_direction(auth_client_a, db, kind, expected):
    account_id = create(auth_client_a, kind)
    row = db.get(Account, account_id)
    assert row.account_type == expected and row.classification == 'liability'
    opening = db.exec(select(Transaction).where(Transaction.account_id == account_id)).one()
    assert opening.transaction_type == 'expense' and '期初欠款' in opening.narration
    assert balance(auth_client_a, account_id) == 5400


@pytest.mark.parametrize('entry', ['single', 'bulk'])
@pytest.mark.parametrize('amount', ['5400', '-5400'])
@pytest.mark.parametrize('source,target', [('cash', 'loan'), ('loan', 'cash')])
def test_reclassification_preserves_opening_balance(auth_client_a, db, entry, amount, source, target):
    account_id = create(auth_client_a, source, amount)
    result = change(auth_client_a, account_id, target, entry)
    assert result.status_code == 200, result.text
    assert balance(auth_client_a, account_id) == Decimal(amount)
    rows = db.exec(select(Transaction).where(Transaction.account_id == account_id)).all()
    assert len(rows) == 1 and rows[0].excluded_from_stats
    assert rows[0].transaction_type == ('expense' if (Decimal(amount) > 0) == (target == 'loan') else 'income')
    assert change(auth_client_a, account_id, target, entry).status_code == 200
    assert balance(auth_client_a, account_id) == Decimal(amount)


@pytest.mark.parametrize('entry', ['single', 'bulk'])
def test_real_flows_remain_unchanged_and_adjustment_is_excluded(auth_client_a, db, entry):
    account_id = create(auth_client_a)
    from datetime import date
    rows = [Transaction(account_id=account_id, transacted_at=date.today(), amount=Decimal(amount), currency='CNY',
                        transaction_type=kind, narration='真实流水', extra=extra)
            for kind, amount, extra in [('expense', '100', {}), ('refund', '20', {}),
                                      ('transfer', '50', {'direction': 'outflow'})]]
    db.add_all(rows); db.commit()
    expected = balance(auth_client_a, account_id)
    types = {row.id: row.transaction_type for row in rows}
    result = change(auth_client_a, account_id, 'loan', entry)
    assert result.status_code == 200, result.text
    assert balance(auth_client_a, account_id) == expected
    db.expire_all()
    assert all(db.get(Transaction, row_id).transaction_type == kind for row_id, kind in types.items())
    adjustments = db.exec(select(Transaction).where(Transaction.account_id == account_id,
                                                   Transaction.transaction_type == 'adjustment')).all()
    assert len(adjustments) == 1 and adjustments[0].excluded_from_stats
    assert adjustments[0].extra['source'] == 'account_type_change'
    assert change(auth_client_a, account_id, 'loan', entry).status_code == 200
    assert balance(auth_client_a, account_id) == expected


def test_type_and_explicit_balance_can_be_changed_together(auth_client_a):
    account_id = create(auth_client_a)
    result = change(auth_client_a, account_id, 'loan', balance='6000')
    assert result.status_code == 200, result.text
    assert balance(auth_client_a, account_id) == 6000


def test_nine_shared_accounts_can_be_reclassified_as_loans_without_losing_5400(auth_client_a, auth_client_b, db):
    amounts = [5400, 5400, 12000, 12000, 25000, 5400, 12000, 25000, 5400]
    ids = [create(auth_client_a, 'loan' if i in (0, 5) else 'cash', amount, f'贷款 {i}')
           for i, amount in enumerate(amounts)]
    bob = db.exec(select(User).where(User.username == 'bob')).one()
    bob.family_id = db.get(Account, ids[0]).family_id
    db.add(bob)
    for account_id in ids:
        db.add(AccountShare(account_id=account_id, user_id=bob.id, permission='read_only'))
    db.commit()
    result = auth_client_a.patch('/api/v1/accounts/bulk/settings', json={
        'account_ids': list(map(str, ids)), 'account_type': 'loan',
    })
    assert result.status_code == 200, result.text
    rows = auth_client_b.get('/api/v1/accounts').json()['accounts']
    assert len(rows) == 9 and all(row['account_type'] == 'loan' and row['classification'] == 'liability' for row in rows)
    assert sum(Decimal(row['report_own_balance']) for row in rows) == 107600
    dashboard = auth_client_b.get('/api/v1/dashboard/summary').json()['balance_sheet']
    report = auth_client_b.get('/api/v1/analytics/report').json()['net_worth']
    assert dashboard['total_liabilities'] == report['liabilities_total'] == 107600
    assert report['loan_total'] == 107600 and report['assets_total'] == 0


def test_names_do_not_change_investment_or_debt_totals(auth_client_a):
    cash_id = create(auth_client_a, 'cash', '1000', '国家开发银行贷款股票投资基金')
    create(auth_client_a, 'investment', '200', '现金贷款')
    for name in ['贷款', '基金', '现金']:
        assert auth_client_a.patch(f'/api/v1/accounts/{cash_id}', json={'name': name}).status_code == 200
        report = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
        overview = auth_client_a.get('/api/v1/dashboard/summary').json()
        assert report['cash_total'] == 1000 and report['invest_total'] == 200
        assert report['loan_total'] == report['liabilities_total'] == 0
        assert report['assets_total'] == 1200
        assert overview['investment']['total'] == 200


@pytest.mark.parametrize('kind', list(ACCOUNT_TYPES))
def test_metadata_edits_never_change_type_balance_or_report_totals(auth_client_a, db, kind):
    account_id = create(auth_client_a, kind, '1234', '日常账户')
    totals = ('assets_total', 'liabilities_total', 'cash_total', 'invest_total', 'credit_total', 'loan_total')
    before = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
    opening = db.exec(select(Transaction).where(Transaction.account_id == account_id)).one()
    opening_state = (opening.id, opening.transaction_type, opening.amount)

    result = auth_client_a.patch(f'/api/v1/accounts/{account_id}', json={
        'name': '贷款信用卡股票基金储蓄',
        'institution_name': '信用卡贷款投资银行',
        'external_identifier': 'credit_card loan investment:1234',
    })
    assert result.status_code == 200, result.text
    result = auth_client_a.patch('/api/v1/accounts/bulk/settings', json={
        'account_ids': [str(account_id)], 'institution_name': '现金借记卡储蓄银行',
    })
    assert result.status_code == 200, result.text

    db.expire_all()
    account = db.get(Account, account_id)
    assert account.account_type == kind
    assert account.classification == ACCOUNT_TYPES[kind]['classification']
    assert balance(auth_client_a, account_id) == Decimal('1234')
    after = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
    assert {key: after[key] for key in totals} == {key: before[key] for key in totals}
    overview = auth_client_a.get('/api/v1/dashboard/summary').json()
    assert overview['balance_sheet']['total_assets'] == before['assets_total']
    assert overview['balance_sheet']['total_liabilities'] == before['liabilities_total']
    assert overview['investment']['total'] == before['invest_total']
    rows = db.exec(select(Transaction).where(Transaction.account_id == account_id)).all()
    assert [(row.id, row.transaction_type, row.amount) for row in rows] == [opening_state]


def test_startup_repair_is_idempotent_and_never_uses_names(auth_client_a, db):
    bad_id = create(auth_client_a)
    untouched_id = create(auth_client_a, 'cash', '100', '贷款')
    bad = db.get(Account, bad_id)
    bad.account_type = ' 抵押贷款 '
    db.add(bad); db.commit()
    assert repair_account_types(db) == 1
    db.expire_all()
    assert db.get(Account, bad_id).classification == 'liability'
    assert balance(auth_client_a, bad_id) == 5400
    assert db.get(Account, untouched_id).account_type == 'cash'
    assert repair_account_types(db) == 0


def test_stale_classification_cannot_override_a_real_loan_type(auth_client_a, db):
    account_id = create(auth_client_a, 'loan', '5400', '现金基金')
    account = db.get(Account, account_id)
    account.classification = 'asset'
    db.add(account); db.commit()
    assert balance(auth_client_a, account_id) == 5400
    row = auth_client_a.get(f'/api/v1/accounts/{account_id}').json()['account']
    assert row['classification'] == 'liability'
    report = auth_client_a.get('/api/v1/analytics/report').json()['net_worth']
    assert report['assets_total'] == 0 and report['loan_total'] == 5400
    assert repair_account_types(db) == 1
    assert balance(auth_client_a, account_id) == 5400


@pytest.mark.parametrize('entry', ['create', 'single', 'bulk'])
def test_unknown_type_is_rejected_without_changing_money(auth_client_a, entry):
    account_id = create(auth_client_a)
    result = (auth_client_a.post('/api/v1/accounts', json={'name': '未知', 'account_type': 'invalid'})
              if entry == 'create' else change(auth_client_a, account_id, 'invalid', entry))
    assert result.status_code == 422
    assert balance(auth_client_a, account_id) == 5400

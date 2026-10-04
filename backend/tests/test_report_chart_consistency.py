from datetime import date, timedelta
from decimal import Decimal

from sqlmodel import select

from models import PersonalDebt, Transaction, User, UserPreference
from services.balance_sheet import ledger_net_worth_history
from services.report_currency import ReportCurrency
from test_fix104_regressions import setup_accounts


def debt(db, family, owner, amount, kind='borrow'):
    row = PersonalDebt(family_id=family.id, owner_id=owner.id if owner else None, debt_type=kind,
                       counterparty='same bank', principal_amount=Decimal(amount), remaining_amount=Decimal(amount),
                       currency='CNY', borrowed_date=date.today() - timedelta(days=1))
    db.add(row)
    return row


def test_dashboard_report_same_authorized_debt_balance(auth_client_a, auth_client_b, db):
    family, alice, bob, accounts = setup_accounts(db)
    alice.role = 'member'
    db.add(alice)
    debt(db, family, alice, '50')
    debt(db, family, bob, '5000')
    debt(db, family, None, '20', 'lend')
    accounts[0].balance = Decimal(100)
    db.add(accounts[0]); db.commit()
    query = '?period=monthly&selected_month=' + date.today().strftime('%Y-%m')
    overview = auth_client_a.get('/api/v1/dashboard/summary' + query)
    report = auth_client_a.get('/api/v1/analytics/report' + query)
    assert overview.status_code == report.status_code == 200, (overview.text, report.text)
    o, r = overview.json()['balance_sheet'], report.json()['net_worth']
    assert o['total_assets'] == r['assets_total'] == 120
    assert o['total_liabilities'] == r['liabilities_total'] == 50
    assert o['net_worth'] == r['current'] == 70
    filtered = auth_client_a.get('/api/v1/dashboard/summary' + query + '&user=bob').json()['balance_sheet']
    assert filtered['total_liabilities'] == 0


def test_historical_curve_uses_openings_and_adjustments_at_cutoff(db):
    _, alice, _, accounts = setup_accounts(db)
    day = date.today() - timedelta(days=3)
    def add(amount, kind, offset=0, **extra):
        row = Transaction(account_id=accounts[0].id, amount=Decimal(amount), currency='CNY',
                          transaction_type=kind, transacted_at=day + timedelta(days=offset), narration='recorded activity', **extra)
        db.add(row)
    add('1000', 'income', excluded_from_stats=True, extra={'is_initial': True})
    add('100', 'expense', 1)
    add('50', 'adjustment', 2, extra={'direction': 'increase'})
    add('20', 'refund', 2)
    add('9999', 'expense', 3)  # must not contaminate an earlier cutoff
    db.commit()
    history = ledger_net_worth_history(db, accounts, ReportCurrency(db, alice),
                                      [('before', day-timedelta(days=1)), ('opening', day), ('later', day+timedelta(days=2))])
    assert [p['value'] for p in history] == [0, 1000, 970]


def test_detail_exposes_read_only_source_id(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    payload = {'account':str(accounts[0].id), 'amount':'12.34', 'currency':'CNY', 'narration':'source audit',
               'external_id':'bank-reference-123', 'transacted_at':date.today().isoformat()}
    posted = auth_client_a.post('/api/v1/transactions', json=payload).json()
    detail = auth_client_a.get('/api/v1/transactions/' + posted['id']).json()
    assert detail['id'] == posted['id'] and detail['external_id'] == payload['external_id']
    repeated = auth_client_a.post('/api/v1/transactions', json=payload).json()
    assert repeated['status'] == 'duplicate' and repeated['id'] == posted['id']
    assert len(db.exec(select(Transaction)).all()) == 1

"""Missing bank metadata must stay missing across all account read paths."""
import uuid
from datetime import datetime, timezone

from models import Account


def _post_transaction(client, account):
    response = client.post('/api/v1/transactions', json={
        'account': account, 'narration': 'Institution regression check',
        'amount': '10', 'currency': 'CNY', 'transaction_type': 'expense',
        'occurred_at': datetime.now(timezone.utc).isoformat(), 'external_id': str(uuid.uuid4()),
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_missing_institution_is_preserved_in_accounts_transactions_and_reports(auth_client_a, db):
    created = auth_client_a.post('/api/v1/accounts', json={
        'name': 'Investment without institution', 'account_type': 'investment',
        'currency': 'CNY', 'balance': '100',
    })
    assert created.status_code == 200, created.text
    account_id = created.json()['id']
    assert created.json()['institution_name'] is None
    assert db.get(Account, uuid.UUID(account_id)).institution_name is None
    _post_transaction(auth_client_a, account_id)

    listed = auth_client_a.get('/api/v1/accounts')
    assert listed.status_code == 200, listed.text
    assert next(a for a in listed.json()['items'] if a['id'] == account_id)['institution_name'] is None
    detail = auth_client_a.get(f'/api/v1/accounts/{account_id}')
    assert detail.status_code == 200, detail.text
    assert detail.json()['account']['institution_name'] is None
    options = auth_client_a.get('/api/v1/transactions/filter-options')
    assert options.status_code == 200, options.text
    assert next(a for a in options.json()['accounts'] if a['id'] == account_id)['institution_name'] == ''
    transactions = auth_client_a.get(f'/api/v1/transactions?account_id={account_id}')
    assert transactions.status_code == 200, transactions.text
    assert transactions.json()['items'][0]['institution_name'] is None

    overview = auth_client_a.get('/api/v1/dashboard/summary')
    assert overview.status_code == 200, overview.text
    groups = overview.json()['balance_sheet']['by_institution']['assets']['groups']
    assert any(g['name'] == '其他机构' and any(a['id'] == account_id for a in g['accounts']) for g in groups)
    assert next(a for g in groups for a in g['accounts'] if a['id'] == account_id)['institution_name'] is None
    report = auth_client_a.get('/api/v1/analytics/report')
    assert report.status_code == 200, report.text
    assert next(a for a in report.json()['investments']['accounts'] if a['id'] == account_id)['institution'] is None


def test_automatic_account_creation_does_not_invent_a_bank(auth_client_a, db):
    result = _post_transaction(auth_client_a, '信用卡:4455')
    account = db.get(Account, uuid.UUID(result['account_id']))
    assert account.institution_name is None
    assert account.name == '信用卡:4455'
    assert account.external_identifier == '信用卡:4455'
    assert _post_transaction(auth_client_a, '信用卡:4455')['account_id'] == str(account.id)

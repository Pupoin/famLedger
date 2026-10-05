"""The Other tile opens its actual expenses, using the chart's scope and FX ranking."""
from datetime import date
from decimal import Decimal

from models import Account, AccountShare, ExchangeRateSnapshot, Family, Transaction
from test_fix104_regressions import setup_accounts


def test_other_merchants_match_chart_amount_and_exclude_private_or_nonspending(auth_client_a, db):
    family, alice, bob, accounts = setup_accounts(db)
    day = date(2026, 10, 1)
    for quote_day in {day, date.today()}:
        db.add(ExchangeRateSnapshot(requested_date=quote_day, effective_date=quote_day,
                                   rates={'EUR':'1', 'USD':'1', 'CNY':'8'}))
    foreign_family = Family(name='Other family')
    db.add(foreign_family); db.flush()
    usd = Account(name='USD', family_id=family.id, owner_id=alice.id, currency='USD', account_type='checking')
    private = Account(name='Private', family_id=family.id, owner_id=bob.id, currency='CNY', account_type='checking')
    hidden_report = Account(name='Report excluded', family_id=family.id, owner_id=alice.id,
                            currency='CNY', account_type='checking', exclude_from_reports=True)
    shared_excluded = Account(name='Shared excluded', family_id=family.id, owner_id=bob.id,
                              currency='CNY', account_type='checking')
    foreign = Account(name='Foreign', family_id=foreign_family.id, owner_id=bob.id, currency='CNY', account_type='checking')
    db.add_all([usd, private, hidden_report, shared_excluded, foreign]); db.flush()
    db.add_all([AccountShare(account_id=shared_excluded.id, user_id=alice.id, include_in_finances=False),
                AccountShare(account_id=foreign.id, user_id=alice.id, include_in_finances=True)])
    rows = [Transaction(account_id=usd.id, transacted_at=day, narration='USD top', amount=Decimal(100), currency='USD')]
    for i, amount in enumerate([900, 700, 600, 500, 400, 300]):
        rows.append(Transaction(account_id=accounts[0].id, transacted_at=day,
                                narration=f'Top {i}', amount=Decimal(amount), currency='CNY'))
    remaining = [Transaction(account_id=accounts[0].id, transacted_at=day,
                             narration=name, amount=Decimal(amount), currency='CNY')
                 for name, amount in [('Corner, Market 100%', '180.00'), ('其他', '36.13')]]
    rows += remaining
    for account in [private, hidden_report, shared_excluded, foreign]:
        rows.append(Transaction(account_id=account.id, transacted_at=day,
                                narration='Corner, Market 100%', amount=Decimal(99999), currency='CNY'))
    rows += [Transaction(account_id=accounts[0].id, transacted_at=day, narration='Corner, Market 100%',
                         amount=Decimal(9), currency='CNY', transaction_type=kind)
             for kind in ['income', 'refund', 'transfer', 'adjustment']]
    rows.append(Transaction(account_id=accounts[0].id, transacted_at=day, narration='Corner, Market 100%',
                            amount=Decimal(999), currency='CNY', excluded_from_stats=True))
    rows.append(Transaction(account_id=accounts[0].id, transacted_at=date(2026, 9, 30),
                            narration='Corner, Market 100%', amount=Decimal(999), currency='CNY'))
    db.add_all(rows); db.commit()
    params = {'start_date':'2026-10-01', 'end_date':'2026-10-31'}
    response = auth_client_a.get('/api/v1/dashboard/summary', params={**params, 'period':'custom'})
    assert response.status_code == 200, response.text
    tiles = response.json()['merchants']['treemap']
    assert len(tiles) == 8
    other = next(t for t in tiles if t.get('is_other'))
    assert other['amount'] == 216.13
    assert next(i for i,t in enumerate(tiles) if t['name'] == 'USD top') == 1
    response = auth_client_a.get('/api/v1/transactions', params={**params, 'merchant_group':'other'})
    assert response.status_code == 200, response.text
    items = response.json()['items']
    assert {t['id'] for t in items} == {str(t.id) for t in remaining}
    assert sum(Decimal(t['amount']) for t in items) == Decimal('216.13')
    assert all(t['transaction_type'] == 'expense' for t in items)
    assert not auth_client_a.get('/api/v1/transactions', params={**params, 'merchant_group':'other', 'user':'bob'}).json()['items']


def test_other_merchants_have_stable_ties_and_paginate_inside_the_group(auth_client_a, db):
    _, _, _, accounts = setup_accounts(db)
    for name in reversed('ABCDEFGHI'):
        db.add(Transaction(account_id=accounts[0].id, transacted_at=date(2026, 10, 1),
                           narration=name, amount=Decimal(100), currency='CNY'))
    db.commit()
    params = {'start_date':'2026-10-01', 'end_date':'2026-10-31', 'merchant_group':'other', 'limit':1}
    first = auth_client_a.get('/api/v1/transactions', params=params).json()
    second = auth_client_a.get('/api/v1/transactions', params={**params, 'cursor':first['next_cursor']}).json()
    assert first['total_count'] == second['total_count'] == 2
    assert first['has_more'] and not second['has_more']
    assert {first['items'][0]['narration'], second['items'][0]['narration']} == {'H','I'}


def test_other_merchants_empty_for_small_or_no_family_groups(auth_client_a, db):
    assert not auth_client_a.get('/api/v1/transactions?merchant_group=other').json()['items']
    _, _, _, accounts = setup_accounts(db)
    db.add(Transaction(account_id=accounts[0].id, transacted_at=date(2026, 10, 1), narration='Only merchant', amount=Decimal(1)))
    db.commit()
    assert not auth_client_a.get('/api/v1/transactions?merchant_group=other').json()['items']
    assert auth_client_a.get('/api/v1/transactions?merchant_group=invalid').status_code == 422

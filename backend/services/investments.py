"""Dated investment values are ledger anchors, not extra cash income."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlmodel import select

from models import Account, Transaction, Transfer
from services.account_types import account_type_is
from services.booking_money import money

SOURCE = 'investment_valuation'
RETURN_SOURCE = 'investment_return'
LOCAL = timezone(timedelta(hours=8))
ZERO = Decimal(0)


def is_valuation(row):
    return row.transaction_type == 'adjustment' and (row.extra or {}).get('source') == SOURCE


def is_investment_return(row):
    return row.transaction_type == 'adjustment' and (row.extra or {}).get('source') in {SOURCE, RETURN_SOURCE}


def enforce_return_fields(row):
    """Investment performance has no spending category or reimbursement status."""
    row.category_id, row.category_source = None, 'manual'
    row.excluded_from_stats, row.is_reimbursable = True, False
    row.reimbursement_status = None
    row.extra = {key: value for key, value in (row.extra or {}).items()
                 if key not in {'classification', 'reimbursement_type', 'counterparty'}}


def clock(row):
    value = row.occurred_at
    if value:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return value.astimezone(LOCAL).time().replace(tzinfo=None, microsecond=0)
    return time.min


def order(row):
    return row.transacted_at, clock(row), is_valuation(row), str(row.id)


def signed(row, pairs):
    if row.transaction_type in ('income', 'refund'):
        return Decimal(row.amount)
    if row.transaction_type == 'expense':
        return -Decimal(row.amount)
    if row.transaction_type == 'adjustment':
        decrease = row.extra.get('direction') == 'decrease' if row.extra else '(-' in (row.narration or '')
        return Decimal(row.amount) * (-1 if decrease else 1)
    if row.transaction_type == 'transfer':
        pair = pairs.get(row.transfer_id)
        if pair:
            return Decimal(row.amount) * (1 if pair.inflow_transaction_id == row.id else -1)
        from services.transaction_direction import transaction_direction
        return Decimal(row.amount) * (1 if transaction_direction(row) == 'inflow' else -1)
    return ZERO


def load_pairs(session, rows):
    ids = {row.transfer_id for row in rows if row.transfer_id}
    return {pair.id: pair for pair in session.exec(select(Transfer).where(Transfer.id.in_(ids))).all()} if ids else {}


def replay_valuations(session, account_ids):
    """Called after ledger writes and before materializing latest balances."""
    if not account_ids:
        return
    ids = set(session.exec(select(Transaction.account_id).where(
        Transaction.account_id.in_(account_ids), Transaction.transaction_type == 'adjustment',
        Transaction.extra['source'].as_string() == SOURCE)).all())
    if not ids:
        return
    rows = session.exec(select(Transaction).where(Transaction.account_id.in_(ids))).all()
    pairs = load_pairs(session, rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.account_id].append(row)
    for activities in grouped.values():
        openings = [order(row)[:2] for row in activities if (row.extra or {}).get('source') == 'account_opening']
        if openings and any(is_valuation(row) and order(row)[:2] < max(openings) for row in activities):
            raise HTTPException(422, '市值日期早于账户期初记录，请先核对期初日期')
        running, basis = ZERO, False
        for row in sorted(activities, key=order):
            if not is_valuation(row):
                running += signed(row, pairs)
                basis = basis or bool(row.amount)
                continue
            target = money((row.extra or {}).get('target_balance'))
            if target < 0:
                raise HTTPException(422, '投资市值不能为负数')
            diff = money(target - running)
            extra = {**row.extra, 'diff': str(diff), 'previous_balance': str(money(running)),
                     'direction': 'decrease' if diff < 0 else 'increase', 'valuation_baseline': not basis}
            if row.amount != abs(diff) or row.extra != extra or not row.excluded_from_stats:
                row.amount = row.original_amount = abs(diff)
                row.original_currency = row.currency
                row.exchange_rate, row.exchange_rate_date = Decimal(1), row.transacted_at
                row.exchange_rate_source = 'investment_valuation'
                row.extra = extra
                row.excluded_from_stats = True
                session.add(row)
            running, basis = target, True


def valuation_time(value=None, day=None, local_time=None):
    from routes.v1_transactions import clean_to_utc, get_local_date
    if value:
        result = clean_to_utc(value)
    else:
        try:
            result = datetime.combine(day or datetime.now(LOCAL).date(),
                time.fromisoformat(local_time) if local_time else datetime.now(LOCAL).time(), LOCAL).astimezone(timezone.utc)
        except ValueError as exc:
            raise HTTPException(422, '市值记录时间无效') from exc
    if result > datetime.now(timezone.utc):
        raise HTTPException(422, '不能记录未来的投资市值')
    if day and get_local_date(result) != day:
        raise HTTPException(422, '市值日期与精确时间不一致')
    return result.replace(tzinfo=None, microsecond=0), get_local_date(result)


def set_valuation(session, account, target, occurred_at, day, name=None, existing=None, notes=None):
    if not account_type_is(account.account_type, 'investment'):
        raise HTTPException(400, '只有投资类型账户可以记录投资盈亏')
    target = money(target)
    if target < 0:
        raise HTTPException(422, '投资市值不能为负数')
    # The valuation editor records seconds. Cash postings in that same second
    # precede the value, including automatically generated opening microseconds.
    occurred_at = occurred_at.replace(microsecond=0)
    rows = session.exec(select(Transaction).where(Transaction.account_id == account.id)).all()
    # An opening is a dated financial fact. Backdating a value before it must
    # not add that opening a second time after the value anchor.
    if any((row.extra or {}).get('source') == 'account_opening'
           and (row.transacted_at, clock(row)) > (day, (occurred_at.replace(tzinfo=timezone.utc).astimezone(LOCAL)).time().replace(tzinfo=None))
           for row in rows):
        raise HTTPException(422, '市值日期早于账户期初记录，请先核对期初日期')
    same_time = [row for row in rows if is_valuation(row) and row.occurred_at == occurred_at
                 and (existing is None or row.id != existing.id)]
    if existing and same_time:
        raise HTTPException(409, '该时刻已有市值记录，请修改已有记录')
    row = existing or (same_time[0] if same_time else None)
    if row is None:
        row = Transaction(account_id=account.id, amount=ZERO, currency=account.currency,
            transacted_at=day, occurred_at=occurred_at, narration=name or '投资市值更新',
            transaction_type='adjustment', status='cleared', category_source='manual',
            reconciled=True, excluded_from_stats=True)
    row.transacted_at, row.occurred_at = day, occurred_at
    row.extra = {**(row.extra or {}), 'source': SOURCE, 'target_balance': str(target)}
    if name is not None:
        row.narration = name
    if notes is not None:
        row.notes = notes
    session.add(row)
    session.flush()
    replay_valuations(session, {account.id})
    session.flush()
    return row


def investment_summary(session, accounts, start, end, converter):
    accounts = [account for account in accounts if account_type_is(account.account_type, 'investment')]
    ids = {account.id for account in accounts}
    end = min(end, datetime.now(LOCAL).date())
    rows = session.exec(select(Transaction).where(Transaction.account_id.in_(ids),
        Transaction.transacted_at <= end)).all() if ids else []
    converter.prepare(rows)
    pairs = load_pairs(session, rows)
    pair_account_ids = {}
    if pairs:
        txn_ids = {key for pair in pairs.values() for key in (pair.inflow_transaction_id, pair.outflow_transaction_id)}
        pair_account_ids = dict(session.exec(select(Transaction.id, Transaction.account_id).where(Transaction.id.in_(txn_ids))).all())
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.account_id].append(row)
    totals = {key: ZERO for key in ('opening_value', 'portfolio_value', 'period_deposit', 'period_withdrawal',
                                   'period_gain', 'period_gross_gain', 'period_gross_loss', 'cash_income', 'cash_cost', 'recorded_return', 'total_return')}
    complete, observed, values = True, [], {}
    for account in accounts:
        balance = ZERO
        activities = sorted(grouped[account.id], key=order)
        anchors = [row for row in activities if is_investment_return(row)]
        period_anchors = [row for row in anchors if row.transacted_at >= start]
        ready = bool(period_anchors) and not any((row.extra or {}).get('valuation_baseline') for row in period_anchors)
        complete = complete and ready
        if anchors:
            observed.append(anchors[-1].transacted_at)
        for row in activities:
            value = signed(row, pairs)
            if row.transacted_at < start:
                balance += value
                continue
            if row.transaction_type == 'transfer':
                pair = pairs.get(row.transfer_id)
                internal = pair and pair_account_ids.get(pair.inflow_transaction_id) in ids and pair_account_ids.get(pair.outflow_transaction_id) in ids
                if not internal:
                    key = 'period_deposit' if value >= 0 else 'period_withdrawal'
                    totals[key] += converter.amount(abs(value), account.currency, row.transacted_at)
            if is_investment_return(row) and not (row.extra or {}).get('valuation_baseline'):
                gain = converter.amount(value, account.currency, row.transacted_at)
                totals['period_gain'] += gain
                totals['period_gross_gain' if gain >= 0 else 'period_gross_loss'] += abs(gain)
            elif not row.excluded_from_stats and row.transaction_type in ('income', 'refund', 'expense'):
                totals['cash_income' if value >= 0 else 'cash_cost'] += converter.amount(abs(value), account.currency, row.transacted_at)
        opening = balance
        balance += sum((signed(row, pairs) for row in activities if row.transacted_at >= start), ZERO)
        if not activities and not account.ledger_initialized and account.created_at.date() <= end:
            balance = account.balance
            if account.created_at.date() < start:
                opening = account.balance
        opening_day = max(date(1900, 1, 1), start - timedelta(days=1)) if start > date.min else end
        totals['opening_value'] += converter.amount(opening, account.currency, min(opening_day, end))
        final = converter.amount(balance, account.currency, end)
        totals['portfolio_value'] += final
        values[str(account.id)] = float(round(final, 2))
        for row in activities:
            if ((is_investment_return(row) and not (row.extra or {}).get('valuation_baseline'))
                    or (not row.excluded_from_stats and row.transaction_type in ('income', 'refund', 'expense'))):
                totals['total_return'] += converter.amount(signed(row, pairs), account.currency, row.transacted_at)
    totals['recorded_return'] = totals['period_gain'] + totals['cash_income'] - totals['cash_cost']
    result = {key: float(round(value, 2)) for key, value in totals.items()}
    from services.investment_rates import performance
    performance_data = performance(session, accounts, rows, pairs, converter, start, end)
    measured = (performance_data or {}).get('period', {}).get('gain')
    period_return = measured if (performance_data or {}).get('configured_accounts') else result['recorded_return'] if complete and accounts else None
    # Reconcile to the same dated portfolio return, including report-currency
    # FX effects and an explicitly declared capital basis, without adding cash
    # dividends/fees twice.
    composition = {'valuation_gain': round(period_return - result['cash_income'] + result['cash_cost'], 2)
                   if period_return is not None else None,
                   'cash_income': result['cash_income'], 'cash_cost': result['cash_cost'], 'total': period_return}
    return {**result, 'period_return': result['recorded_return'] if complete and accounts else None,
            'total_return': result['total_return'] if observed else None, 'has_accounts': bool(accounts),
            'valuation_complete': bool(accounts) and complete,
            'as_of': min(observed).isoformat() if observed else None,
            'period_start': start.isoformat(), 'period_end': end.isoformat(),
            'currency': converter.currency, 'currency_symbol': converter.symbol, 'account_values': values,
            'performance': performance_data, 'composition': composition,
            'account_ids': sorted(str(key) for key in ids)}

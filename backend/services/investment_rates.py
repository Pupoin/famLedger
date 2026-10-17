"""Portfolio performance with explicit estimates for unobserved range boundaries.

XIRR uses actual dates (365-day convention). Dietz is explicitly an estimate.
Exact TWR requires valuations at external-flow instants; no price interpolation.
"""
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from models import InvestmentSetting, Transaction
from sqlmodel import select

from services.investments import LOCAL, ZERO, is_valuation, is_investment_return, signed, order

METHODS = ('mwr', 'xirr', 'dietz', 'twr', 'twr_annual', 'simple_annual')


def instant(row):
    if row.occurred_at:
        value = row.occurred_at
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.replace(microsecond=0)
    return datetime.combine(row.transacted_at, time.min, LOCAL).astimezone(timezone.utc)


def local_day(value):
    return value.astimezone(LOCAL).date()


def capital_instant(profile):
    value = profile.capital_occurred_at
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).replace(microsecond=0)


def opening(row):
    return bool((row.extra or {}).get('is_initial') or (row.extra or {}).get('source') == 'account_opening')


def xirr_log(cashflows):
    """Return log(1 + annual IRR), or a reason. Same-date flows are netted.

    Search in log-rate space to handle negative and large positive returns.
    For non-conventional cashflows inspect stationary points as well as NPV
    sign changes, so nearby roots (e.g. 10% and 20%) are not silently selected.
    """
    grouped = defaultdict(float)
    for day, amount in cashflows:
        grouped[day] += float(amount)
    rows = [(day, value) for day, value in sorted(grouped.items()) if abs(value) > 1e-10]
    if not rows or not any(value < 0 for _, value in rows) or not any(value > 0 for _, value in rows):
        return None, 'no_solution'
    if rows[-1][0] == rows[0][0]:
        return None, 'too_short'
    scale = max(abs(value) for _, value in rows)
    terms = [((day - rows[0][0]).days / 365, value / scale) for day, value in rows]

    def evaluate(y, derivative=False):
        powers = [-y * duration for duration, value in terms]
        shift = max(powers)
        values = [value * (-duration if derivative else 1) * math.exp(power - shift)
                  for (duration, value), power in zip(terms, powers)]
        norm = math.fsum(abs(value) for value in values)
        return math.fsum(values) / norm if norm else 0.0

    def bisect(fn, left, right):
        a = fn(left)
        for _ in range(90):
            middle = (left + right) / 2
            b = fn(middle)
            if abs(b) < 1e-13 or right - left < 1e-12:
                return middle
            if (a < 0) != (b < 0):
                right = middle
            else:
                left, a = middle, b
        return (left + right) / 2

    changes = sum((a[1] < 0) != (b[1] < 0) for a, b in zip(rows, rows[1:]))
    bounds = [-32.0, 32.0]
    if changes > 1:
        grid = [index / 8 for index in range(-256, 257)]
        derivative = lambda y: evaluate(y, True)
        for left, right in zip(grid, grid[1:]):
            if derivative(left) * derivative(right) < 0:
                bounds.append(bisect(derivative, left, right))
        bounds.extend(grid)
    bounds = sorted(set(bounds))
    roots = []
    for left, right in zip(bounds, bounds[1:]):
        a, b = evaluate(left), evaluate(right)
        if a * b < 0:
            roots.append(bisect(evaluate, left, right))
        elif abs(a) < 1e-12:
            roots.append(left)
    unique = []
    for root in sorted(roots):
        if not unique or abs(root - unique[-1]) > 1e-7:
            unique.append(root)
    if len(unique) != 1:
        return None, 'multiple_solutions' if unique else 'no_solution'
    return unique[0], None


def percent(value):
    if value is None or not math.isfinite(float(value)):
        return None
    result = float(value) * 100
    return round(result, 6) if math.isfinite(result) else None


class Portfolio:
    def __init__(self, accounts, profiles, rows, pairs, converter):
        self.accounts = {account.id: account for account in accounts}
        self.converter = converter
        self.positions, self.flows, self.problems = {}, defaultdict(Decimal), []
        self.references = {}
        grouped = defaultdict(list)
        known = {row.id: row for row in rows}
        cutoffs = {}
        for account_id, profile in profiles.items():
            baseline = known.get(profile.baseline_transaction_id)
            if profile.mode == 'baseline' and baseline and baseline.account_id == account_id and is_valuation(baseline):
                cutoffs[account_id] = order(baseline)
        # Neutralize only transfers whose two legs are actually tracked. A leg
        # before another account's chosen baseline is outside its return scope.
        def tracked(row):
            profile = profiles.get(row.account_id)
            if profile and profile.mode == 'capital':
                at = capital_instant(profile)
                return at is not None and instant(row) >= at and not opening(row)
            return row.account_id not in cutoffs or order(row) > cutoffs[row.account_id]
        transaction_accounts = {row.id: row.account_id for row in rows if tracked(row)}
        for row in rows:
            grouped[row.account_id].append(row)
        self.capital = {'initial_value': ZERO, 'capital_basis': ZERO, 'contributions': ZERO, 'withdrawals': ZERO}
        for account in accounts:
            activities = sorted(grouped[account.id], key=order)
            profile = profiles.get(account.id)
            if profile is None:
                self.problems.append('not_initialized')
                continue
            baseline = next((row for row in activities if row.id == profile.baseline_transaction_id and is_valuation(row)), None)
            if profile.mode == 'baseline' and baseline is None:
                self.problems.append('baseline_deleted')
                continue
            configured_capital = profile.mode == 'capital'
            capital_at = capital_instant(profile) if configured_capital else None
            if configured_capital and (capital_at is None or profile.capital_amount is None or profile.capital_amount <= 0):
                self.problems.append('missing_contributions')
                continue
            capital_rows = [row for row in activities if opening(row) or row.transaction_type == 'transfer']
            if profile.mode == 'history' and not capital_rows:
                self.problems.append('missing_contributions')
                continue
            start_row = baseline if profile.mode == 'baseline' else min(activities, key=order) if activities else None
            started = capital_at if configured_capital else instant(start_row)
            balance = Decimal(profile.capital_amount) if configured_capital else Decimal(baseline.extra['target_balance']) if baseline else ZERO
            snapshots = {started: balance} if baseline or configured_capital else {}
            events, corrections = [], []
            if baseline or configured_capital:
                value = converter.amount(balance, account.currency, local_day(started))
                self.flows[started] += value
                self.capital['capital_basis' if configured_capital else 'initial_value'] += value
            ledger_balance, basis_observed = ZERO, False
            if configured_capital and not activities and not account.ledger_initialized:
                # Legacy accounts may still hold an unmaterialized opening in
                # account metadata. Read it at its real creation date without
                # manufacturing a ledger row or exposing it to earlier ranges.
                observed_at = account.created_at
                observed_at = observed_at.replace(tzinfo=timezone.utc) if observed_at.tzinfo is None else observed_at.astimezone(timezone.utc)
                observed_at = observed_at.replace(microsecond=0)
                snapshots[observed_at] = Decimal(account.balance or 0)
                basis_observed = observed_at == started
            for row in activities:
                value = signed(row, pairs)
                ledger_balance += value
                if configured_capital and instant(row) < started:
                    # Keep earlier observed prices for a carried closing value,
                    # but never treat pre-basis deposits as new contributions.
                    events.append((instant(row), value))
                    if opening(row) or is_valuation(row):
                        snapshots[instant(row)] = ledger_balance
                    continue
                if baseline and order(row) <= order(baseline):
                    continue
                at = instant(row)
                if configured_capital and (opening(row) or is_valuation(row)):
                    # The account opening is an observed book value, not new
                    # cash on top of the separately declared earlier capital.
                    observed = Decimal(row.extra['target_balance']) if is_valuation(row) else ledger_balance
                    events.append((at, observed - balance))
                    balance = observed
                    snapshots[at] = balance
                    basis_observed |= at == started
                else:
                    balance += value
                    events.append((at, value))
                    if is_investment_return(row):
                        snapshots[at] = balance
                        if (row.extra or {}).get('valuation_baseline'):
                            corrections.append(at)
                    elif row.transaction_type == 'adjustment':
                        corrections.append(at)
                external = opening(row) and not configured_capital
                if row.transaction_type == 'transfer':
                    pair = pairs.get(row.transfer_id)
                    internal = pair and transaction_accounts.get(pair.inflow_transaction_id) in self.accounts and transaction_accounts.get(pair.outflow_transaction_id) in self.accounts
                    external = not internal
                if external:
                    amount = converter.amount(value, account.currency, row.transacted_at)
                    self.flows[at] += amount
                    self.capital['contributions' if amount >= 0 else 'withdrawals'] += abs(amount)
            self.positions[account.id] = dict(start=started, snapshots=snapshots, events=events,
                corrections=corrections, currency=account.currency,
                capital_basis_at=started if configured_capital else None, basis_observed=basis_observed)
        self.flows = dict(sorted((at, value) for at, value in self.flows.items() if value))
        self.origin = min((value['start'] for value in self.positions.values()), default=None)

    def value(self, day=None, at=None):
        """Observed values only, especially at exact TWR cash-flow boundaries."""
        total = ZERO
        for position in self.positions.values():
            if at is not None and position['start'] > at or day is not None and local_day(position['start']) > day:
                continue
            candidates = [(point, value) for point, value in position['snapshots'].items()
                          if point == at] if at is not None else [
                              (point, value) for point, value in position['snapshots'].items() if local_day(point) == day]
            if not candidates:
                return None
            point, value = max(candidates)
            # A cash posting after a value means the end of this day has not
            # been observed yet. Require another valuation instead of guessing.
            if day is not None and any(point < event and local_day(event) == day and amount for event, amount in position['events']):
                return None
            total += self.converter.amount(value, position['currency'], day or local_day(at))
        return total

    def reference(self, day):
        """Last known value plus later booked activities, without inventing prices.

        A missing calendar-date observation is not missing capital history.
        Carry native market values forward, apply recorded cash movements, then
        use the requested day's FX. Such boundaries are explicitly estimates.
        History mode can start from its recorded contributions before the first
        valuation, but must never borrow a later valuation for an earlier date.
        """
        if day in self.references:
            return self.references[day]
        total, estimated, dates, cash_only = ZERO, False, set(), False
        for position in self.positions.values():
            if local_day(position['start']) > day:
                continue
            candidates = [(at, value) for at, value in position['snapshots'].items()
                          if local_day(at) <= day]
            observed = [(at, value) for at, value in candidates
                        if at != position['capital_basis_at'] or position['basis_observed']]
            if observed:
                candidates = observed
            if candidates:
                point, value = max(candidates)
                later = [(at, amount) for at, amount in position['events']
                         if point < at and local_day(at) <= day]
                value += sum((amount for _, amount in later), ZERO)
                estimated |= local_day(point) != day or any(amount for _, amount in later)
                if point == position['capital_basis_at'] and not position['basis_observed']:
                    estimated = cash_only = True
            else:
                # Initialization already verified that this is complete-history
                # mode with real contributions. No inferred principal is added.
                point = position['start']
                value = sum((amount for at, amount in position['events'] if local_day(at) <= day), ZERO)
                estimated = cash_only = True
            dates.add(local_day(point).isoformat())
            total += self.converter.amount(value, position['currency'], day)
        result = dict(value=total, estimated=bool(estimated), dates=sorted(dates), from_cashflows=cash_only)
        self.references[day] = result
        return result

    def twr(self, start, end, initial, flows, ending):
        factor, previous = 1.0, float(initial)
        for at, amount in flows:
            after = self.value(at=at)
            if previous == 0 and after is None and all(
                    value['start'] >= at for value in self.positions.values()):
                after = amount  # first capital entering an empty portfolio
            if after is None:
                return None, 'missing_flow_valuation'
            before = float(after - amount)
            if previous == 0:
                if abs(before) > 1e-7:
                    return None, 'zero_base'
            elif before < 0:
                return None, 'zero_base'
            else:
                factor *= before / previous
            previous = float(after)
        if previous == 0 and ending == 0:
            return factor - 1, None
        if previous <= 0:
            return None, 'zero_base'
        return factor * float(ending) / previous - 1, None

    def evaluate(self, start, end, inception=False):
        empty = {method: None for method in METHODS}
        reason = self.problems[0] if self.problems else None
        if self.origin is None:
            reason = reason or 'not_initialized'
        origin_day = local_day(self.origin) if self.origin else end
        beginning = max(origin_day, start - timedelta(days=1)) if start > date.min else origin_day
        from_origin = inception or beginning <= origin_day
        beginning = origin_day if inception else beginning
        opening_reference = dict(value=ZERO, estimated=False, dates=[], from_cashflows=False) if from_origin else self.reference(beginning)
        closing_reference = self.reference(end)
        initial, ending = opening_reference['value'], closing_reference['value']
        if end < beginning:
            reason = reason or 'before_start'
        elif initial is None:
            reason = reason or 'missing_opening_valuation'
        elif ending is None:
            reason = reason or 'missing_closing_valuation'
        flows = [(at, amount) for at, amount in self.flows.items()
                 if (local_day(at) >= beginning if from_origin else local_day(at) > beginning) and local_day(at) <= end]
        if any((from_origin or local_day(at) > beginning) and local_day(at) <= end
               for value in self.positions.values() for at in value['corrections']):
            reason = reason or 'balance_correction'
        days = (end - beginning).days
        base = dict(rates=empty.copy(), reasons={method: reason for method in METHODS}, start=beginning.isoformat(),
                    end=end.isoformat(), days=max(days, 0), gain=None, opening_value=None, closing_value=None,
                    estimated=opening_reference['estimated'] or closing_reference['estimated'],
                    opening_estimated=opening_reference['estimated'], closing_estimated=closing_reference['estimated'],
                    opening_reference_dates=opening_reference['dates'], closing_reference_dates=closing_reference['dates'],
                    opening_from_cashflows=opening_reference['from_cashflows'], closing_from_cashflows=closing_reference['from_cashflows'])
        if reason:
            return base
        total_flows = sum((amount for _, amount in flows), ZERO)
        gain = ending - initial - total_flows
        base.update(gain=float(round(gain, 2)), opening_value=float(round(initial, 2)), closing_value=float(round(ending, 2)))
        if days <= 0:
            base['reasons'] = {method: 'too_short' for method in METHODS}
            if days == 0 and gain == 0 and ending > 0:
                for method in ('mwr', 'twr', 'dietz'):
                    base['rates'][method], base['reasons'][method] = 0.0, None
                for method in ('xirr', 'twr_annual', 'simple_annual'):
                    base['reasons'][method] = 'under_one_year'
            return base
        cash = [(beginning, -initial)] + [(local_day(at), -amount) for at, amount in flows] + [(end, ending)]
        log_rate, irr_error = xirr_log(cash)
        if log_rate is not None:
            try:
                base['rates']['mwr'] = percent(math.expm1(log_rate * days / 365))
                base['rates']['xirr'] = percent(math.expm1(log_rate)) if days >= 365 else None
            except OverflowError:
                irr_error = 'no_solution'
        base['reasons']['mwr'] = irr_error
        base['reasons']['xirr'] = irr_error or ('under_one_year' if days < 365 else None)
        if ending == 0 and any(amount < 0 for _, amount in cash) and not any(amount > 0 for _, amount in cash):
            # Total loss is a valid holding-period result, while XIRR has no
            # finite solution without a positive investor cashflow.
            base['rates']['mwr'], base['reasons']['mwr'] = -100.0, None
        weighted = float(initial) + math.fsum(float(amount) * (end - local_day(at)).days / days for at, amount in flows)
        if weighted > 1e-12:
            base['rates']['dietz'] = percent(float(gain) / weighted)
        else:
            base['reasons']['dietz'] = 'zero_base'
        twr, twr_error = self.twr(beginning, end, initial, flows, ending)
        base['rates']['twr'], base['reasons']['twr'] = percent(twr), twr_error
        if twr is not None and twr >= -1 and days >= 365:
            base['rates']['twr_annual'] = percent(math.expm1(math.log1p(twr) * 365 / days)) if twr > -1 else -100
        base['reasons']['twr_annual'] = twr_error or ('under_one_year' if days < 365 else None)
        # Simple annual return is meaningful here only for a single opening
        # investment with no later additions/withdrawals. Never divide by net
        # contributions (which may be zero or negative after taking profits).
        contributions = [amount for at, amount in flows if local_day(at) == beginning]
        later = [amount for at, amount in flows if local_day(at) > beginning]
        simple_base = initial + sum(contributions, ZERO)
        if days >= 365 and simple_base > 0 and not later:
            base['rates']['simple_annual'] = percent(float(gain / simple_base) * 365 / days)
        else:
            base['reasons']['simple_annual'] = 'under_one_year' if days < 365 else 'zero_base' if simple_base <= 0 else 'cashflows_require_weighting'
        return base


def performance(session, accounts, rows, pairs, converter, start, end):
    if not accounts:
        return None
    profiles = {row.account_id: row for row in session.exec(select(InvestmentSetting).where(
        InvestmentSetting.account_id.in_([account.id for account in accounts]))).all()}
    # A baseline outside a historical selection is not a deleted record, and
    # an investment that has not started must not block the older portfolio.
    known = {row.id: row for row in rows}
    missing = {profile.baseline_transaction_id for profile in profiles.values()
               if profile.baseline_transaction_id and profile.baseline_transaction_id not in known}
    references = {row.id: row for row in session.exec(select(Transaction).where(Transaction.id.in_(missing))).all()} if missing else {}
    active_ids = {row.account_id for row in rows}
    eligible = []
    for account in accounts:
        profile = profiles.get(account.id)
        if profile and profile.mode == 'capital' and capital_instant(profile):
            if local_day(capital_instant(profile)) <= end:
                eligible.append(account)
            continue
        baseline = known.get(profile.baseline_transaction_id) or references.get(profile.baseline_transaction_id) if profile else None
        if baseline and local_day(instant(baseline)) > end:
            continue
        if account.id not in active_ids and local_day(account.created_at.replace(tzinfo=timezone.utc) if account.created_at.tzinfo is None else account.created_at) > end:
            continue
        eligible.append(account)
    if not eligible:
        return dict(period={'rates':{key:None for key in METHODS},'reasons':{key:'before_start' for key in METHODS},'gain':None,'start':start.isoformat(),'end':end.isoformat()},
                    inception={'rates':{key:None for key in METHODS},'reasons':{key:'before_start' for key in METHODS},'gain':None,'start':start.isoformat(),'end':end.isoformat()},
                    period_series=[],inception_series=[],capital={},configured_accounts=0,account_count=0,currency=converter.currency)
    accounts = eligible
    profiles = {key:profile for key,profile in profiles.items() if key in {account.id for account in accounts}}
    portfolio = Portfolio(accounts, profiles, rows, pairs, converter)
    same_origin = portfolio.origin is not None and (start <= local_day(portfolio.origin) + timedelta(days=1))
    current = portfolio.evaluate(start, end)
    inception = current if same_origin else portfolio.evaluate(start, end, inception=True)
    candidates = sorted({local_day(at) for value in portfolio.positions.values() for at in value['snapshots']
                         if start <= local_day(at) <= end})
    # Retain actual observations, cap chart work independently of ledger size.
    if len(candidates) > 120:
        candidates = sorted({candidates[round(index * (len(candidates) - 1) / 119)] for index in range(120)})
    period_series, inception_series = [], []
    for day in candidates:
        value = portfolio.evaluate(start, day)
        all_time = value if same_origin else portfolio.evaluate(start, day, inception=True)
        period_series.append({'date': day.isoformat(), 'estimated': value['estimated'], **value['rates']})
        inception_series.append({'date': day.isoformat(), 'estimated': all_time['estimated'], **all_time['rates']})
    capital = {key: float(round(value, 2)) for key, value in portfolio.capital.items()}
    capital['net_contributions'] = round(capital['contributions'] - capital['withdrawals'], 2)
    return dict(period=current, inception=inception, period_series=period_series, inception_series=inception_series,
                capital=capital, configured_accounts=len(profiles), account_count=len(accounts), currency=converter.currency)


def investment_group_ytd_returns(session, groups, converter, today=None):
    """Batch observed YTD portfolio returns for explicitly authorized groups."""
    from services.investments import LOCAL, load_pairs

    today = today or datetime.now(LOCAL).date()
    start = date(today.year, 1, 1)
    accounts = {account.id: account for group in groups.values() for account in group}
    if not accounts:
        return {}
    ids = list(accounts)
    rows = session.exec(select(Transaction).where(Transaction.account_id.in_(ids),
        Transaction.transacted_at <= today)).all()
    profiles = {row.account_id: row for row in session.exec(select(InvestmentSetting).where(
        InvestmentSetting.account_id.in_(ids))).all()}
    converter.prepare(rows)
    pairs = load_pairs(session, rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.account_id].append(row)
    result = {}
    for key, members in groups.items():
        members = list({account.id: account for account in members}.values())
        activities = [row for account in members for row in grouped[account.id]]
        portfolio = Portfolio(members, profiles, activities, pairs, converter)
        dates = sorted({row.transacted_at for row in activities
                        if is_investment_return(row) and row.transacted_at >= start
                        and (portfolio.origin is None or row.transacted_at >= local_day(portfolio.origin))}, reverse=True)
        observations = {account_id: {local_day(at) for at in position['snapshots']}
                        for account_id, position in portfolio.positions.items()}
        # A group value must use a shared observed date. Accounts that started
        # later did not yet contribute to the earlier portfolio's market value.
        as_of = next((day for day in dates if all(local_day(position['start']) > day
            or day in observations[account_id] for account_id, position in portfolio.positions.items())), None)
        value = portfolio.evaluate(start, as_of or today)
        result[key] = dict(year=today.year, rate=value['rates']['mwr'],
            reason=value['reasons']['mwr'], as_of=as_of.isoformat() if as_of else None,
            start=value['start'], method='mwr', currency=converter.currency,
            estimated=value['estimated'], opening_estimated=value['opening_estimated'],
            closing_estimated=value['closing_estimated'],
            opening_reference_dates=value['opening_reference_dates'], closing_reference_dates=value['closing_reference_dates'],
            opening_from_cashflows=value['opening_from_cashflows'], closing_from_cashflows=value['closing_from_cashflows'])
    return result


def account_ytd_returns(session, accounts, converter, today=None):
    """One observed YTD money-weighted return per authorized investment account.

    Financial rows are batched and only one cutoff is evaluated, with no chart
    series. Transfers remain external to each individual investment account.
    """
    from services.account_types import account_type_is
    groups = {str(account.id): [account] for account in accounts
              if account_type_is(account.account_type, 'investment')}
    return investment_group_ytd_returns(session, groups, converter, today)

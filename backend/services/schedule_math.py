"""Decimal loan projections and calendar-anchored recurrence; no ledger writes."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ZERO = Decimal(0)


def rounded(value, currency):
    unit = Decimal('1') if currency in {'JPY', 'KRW'} else Decimal('0.01')
    return Decimal(value).quantize(unit, rounding=ROUND_HALF_UP)


def add_months(anchor, months):
    year, month = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
    month += 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def scheduled_date(plan, number):
    """The regular recurrence, without a final-payment override."""
    stages = getattr(plan, 'config', {}).get('recurrence_stages', [])
    stage = next((s for s in reversed(stages) if s['from_period'] <= number), None)
    anchor = date.fromisoformat(stage['start_date']) if stage else plan.start_date
    frequency = stage['frequency'] if stage else plan.frequency
    interval = stage['interval'] if stage else plan.interval
    count = (number - (stage['from_period'] if stage else 1)) * interval
    if frequency == 'weekly':
        return anchor + timedelta(weeks=count)
    return add_months(anchor, count * {'monthly': 1, 'quarterly': 3, 'yearly': 12}[frequency])


def occurrence_date(plan, number):
    due = scheduled_date(plan, number)
    if getattr(plan, 'kind', None) == 'loan' and number == plan.occurrence_limit:
        loan = getattr(plan, 'loan', None)
        final_date = loan.final_payment_date if loan is not None else plan.config.get('loan', {}).get('final_payment_date')
        if final_date is not None:
            return date.fromisoformat(final_date) if isinstance(final_date, str) else final_date
        day = loan.final_payment_day if loan is not None else plan.config.get('loan', {}).get('final_payment_day')
        if day is not None:
            return due.replace(day=min(day, calendar.monthrange(due.year, due.month)[1]))
    return due


def scheduled_period_days(plan, number):
    previous = scheduled_date(plan, number - 1) if number > 1 else add_months(plan.start_date, -1)
    return (scheduled_date(plan, number) - previous).days


class RateStage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    effective_date: date
    annual_rate: Decimal = Field(ge=0, le=100, max_digits=10, decimal_places=6)


class RepaymentStage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    from_period: int = Field(ge=1, le=1200)
    method: Literal['equal_installment', 'equal_principal', 'interest_only', 'principal_only', 'custom']
    amount: Decimal | None = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    interest_treatment: Literal['waive', 'defer', 'capitalize'] | None = None

    @model_validator(mode='after')
    def check_amount(self):
        if self.method in {'principal_only', 'custom'} and self.amount is None:
            raise ValueError('该还款方式必须指定每期金额')
        if self.method == 'principal_only' and self.interest_treatment is None:
            raise ValueError('只还本金必须明确利息处理方式')
        if self.method != 'principal_only' and self.interest_treatment is not None:
            raise ValueError('利息处理选项仅适用于只还本金阶段')
        return self


class InterestFreePeriod(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start_date: date
    end_date: date

    @model_validator(mode='after')
    def valid_range(self):
        if self.end_date < self.start_date:
            raise ValueError('免息结束日期不能早于开始日期')
        return self


class InterestOnlyPeriod(InterestFreePeriod):
    @model_validator(mode='after')
    def valid_range(self):
        if self.end_date < self.start_date:
            raise ValueError('仅还利息结束日期不能早于开始日期')
        return self


class LoanConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    term_months: int = Field(ge=1, le=1200)
    interest_start_date: date
    final_payment_day: int | None = Field(default=None, ge=1, le=31, strict=True)
    final_payment_date: date | None = None
    rates: list[RateStage] = Field(min_length=1, max_length=100)
    phases: list[RepaymentStage] = Field(min_length=1, max_length=100)
    day_count: Literal['monthly', 'actual_365', 'actual_360'] = 'monthly'
    fee: Decimal = Field(default=0, ge=0, max_digits=19, decimal_places=4)
    interest_free_periods: list[InterestFreePeriod] = Field(default_factory=list, max_length=100)
    interest_only_periods: list[InterestOnlyPeriod] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def ordered(self):
        if self.final_payment_day is not None and self.final_payment_date is not None:
            raise ValueError('最后一期只能选择日号或完整日期其中一种')
        self.rates.sort(key=lambda r: r.effective_date)
        self.phases.sort(key=lambda p: p.from_period)
        self.interest_free_periods.sort(key=lambda p: p.start_date)
        if any(right.start_date <= left.end_date for left, right in zip(self.interest_free_periods, self.interest_free_periods[1:])):
            raise ValueError('免息时间段不能重叠')
        self.interest_only_periods.sort(key=lambda p: p.start_date)
        if any(right.start_date <= left.end_date for left, right in zip(self.interest_only_periods, self.interest_only_periods[1:])):
            raise ValueError('仅还利息时间段不能重叠')
        if self.interest_only_periods and any(p.method == 'interest_only' for p in self.phases):
            raise ValueError('设置仅还利息时间段时，常规还款方式不能也是仅还利息')
        if self.rates[0].effective_date > self.interest_start_date:
            raise ValueError('利率阶段必须覆盖计息起始日期')
        if len({r.effective_date for r in self.rates}) != len(self.rates):
            raise ValueError('利率阶段生效日期不能重复')
        if self.phases[0].from_period != 1 or self.phases[-1].from_period > self.term_months:
            raise ValueError('还款阶段必须从第1期开始并处于贷款期限内')
        if len({p.from_period for p in self.phases}) != len(self.phases):
            raise ValueError('还款阶段不能重复')
        return self


def check_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('无效时区')
    return value


def active_rate(config, when):
    if any(p.start_date <= when <= p.end_date for p in config.interest_free_periods):
        return ZERO
    return next(r.annual_rate for r in reversed(config.rates) if r.effective_date <= when)


def next_rate_change(config, when):
    boundaries = {r.effective_date for r in config.rates}
    for period in config.interest_free_periods:
        boundaries.add(period.start_date)
        if period.end_date < date.max:
            boundaries.add(period.end_date + timedelta(days=1))
    current = active_rate(config, max(when, config.interest_start_date))
    for day in sorted(d for d in boundaries if d > when):
        rate = active_rate(config, max(day, config.interest_start_date))
        if rate != current:
            return {'effective_date': day.isoformat(), 'annual_rate': str(rate)}
    return None


def interest_for(config, principal, start, end, period_days=None):
    if end <= start:
        return ZERO
    boundaries = {start, end, *[r.effective_date for r in config.rates if start < r.effective_date < end]}
    for period in config.interest_free_periods:
        if start < period.start_date < end:
            boundaries.add(period.start_date)
        if period.end_date < date.max and start < period.end_date + timedelta(days=1) < end:
            boundaries.add(period.end_date + timedelta(days=1))
    boundaries = sorted(boundaries)
    weighted = sum((active_rate(config, left) * Decimal((right - left).days)
                    for left, right in zip(boundaries, boundaries[1:])), ZERO)
    if config.day_count == 'monthly':
        # A complete scheduled month is one monthly accrual; changes within it
        # are weighted by actual days rather than applied retroactively.
        denominator = period_days or (add_months(start, 1) - start).days
        return principal * weighted / Decimal(denominator) / Decimal(1200)
    return principal * weighted / Decimal(100 * (365 if config.day_count == 'actual_365' else 360))


def repayment_phase(config, number, due):
    phase = next(p for p in reversed(config.phases) if p.from_period <= number)
    if any(p.start_date <= due <= p.end_date for p in config.interest_only_periods):
        return phase.model_copy(update={'method': 'interest_only', 'amount': None, 'interest_treatment': None})
    if any(p.end_date < due for p in config.interest_only_periods) and phase.method in {'principal_only', 'interest_only'}:
        raise ValueError('仅还利息期结束后需选择本金加利息的常规还款方式')
    return phase


def installment(config, number, due, previous_due, principal, deferred, currency, override=None, period_days=None, phase_date=None):
    # A bank's actual payment date affects accrual, but the contractual due
    # date decides whether this installment belongs to an interest-only window.
    phase = repayment_phase(config, number, phase_date or due)
    rate = active_rate(config, due)
    interest = rounded(interest_for(config, principal, previous_due, due, period_days), currency)
    remaining = config.term_months - number + 1
    accrued = capitalized = ZERO
    if phase.method == 'principal_only':
        paid_principal = min(principal, rounded(phase.amount, currency))
        if phase.interest_treatment == 'waive':
            interest = ZERO
        elif phase.interest_treatment == 'defer':
            accrued, interest = interest, ZERO
        else:
            capitalized, interest = interest, ZERO
    elif phase.method == 'interest_only':
        paid_principal = ZERO
    elif phase.method == 'equal_principal':
        paid_principal = rounded(principal / remaining, currency)
    else:
        if phase.method == 'custom':
            payment = rounded(phase.amount, currency)
        elif override and str(rate) == override.get('rate') and phase.from_period == override.get('phase'):
            payment = Decimal(override['amount'])
        else:
            monthly = rate / Decimal(1200)
            payment = rounded(principal / remaining if not monthly else
                              principal * monthly / (1 - (1 + monthly) ** -remaining), currency)
        if payment < interest and number != config.term_months:
            raise ValueError('每期还款金额不足以支付当期利息')
        paid_principal = min(principal, max(ZERO, payment - interest))
    # Balloon and rounding residuals are explicit in the final installment.
    if number == config.term_months:
        paid_principal = principal
        interest += deferred + accrued
        accrued = ZERO
        if capitalized:
            interest += capitalized
            capitalized = ZERO
    deferred_after = deferred + accrued
    if number == config.term_months:
        deferred_after = ZERO
    total = paid_principal + interest + rounded(config.fee, currency)
    return {k: str(v) for k, v in dict(principal=paid_principal, interest=interest,
            fee=rounded(config.fee, currency), total=total, accrued=accrued, capitalized=capitalized,
            deferred_paid=deferred if number == config.term_months else ZERO,
            remaining_principal=max(ZERO, principal - paid_principal + capitalized),
            deferred_interest=deferred_after, annual_rate=rate).items()} | {
            'method': phase.method, 'interest_treatment': phase.interest_treatment}

"""Preference-currency detail amounts, without changing fixed ledger money."""
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException

from services.booking_money import RATE, money, money_text
from services.report_currency import ReportCurrency


def transaction_display_money(session, txn, user=None, splits=()):
    converter = ReportCurrency(session, user=user, cache_independently=True)
    fields = {
        "display_amount": None,
        "display_currency": converter.currency,
        "display_exchange_rate": None,
        "display_exchange_rate_base_currency": txn.currency,
        "display_exchange_rate_date": None,
        "display_exchange_rate_source": None,
        "display_money_error": None,
        "splits": [
            {"id": str(s.id), "category_id": str(s.category_id) if s.category_id else None,
             "amount": money_text(s.amount), "currency": txn.currency, "notes": s.notes,
             "display_amount": None, "display_currency": converter.currency}
            for s in splits
        ],
    }
    try:
        # Use the actual booked amount, including any bank settlement. Only
        # this display value changes when the user changes their preference.
        amount = converter.amount(txn.amount, txn.currency, txn.transacted_at)
        rate = converter.amount(Decimal(1), txn.currency, txn.transacted_at)
        effective_day = txn.transacted_at
        source = "same_currency"
        if txn.currency != converter.currency:
            _, effective_day = converter._quotes[txn.transacted_at]
            source = "frankfurter"
        displayed_splits = [money(converter.amount(s.amount, txn.currency, txn.transacted_at)) for s in splits]
        if displayed_splits and sum((s.amount for s in splits), Decimal(0)) == txn.amount:
            # The last complete split absorbs display rounding, so the displayed
            # children add up to the displayed parent without altering book money.
            remaining = money(amount)
            for i in range(len(displayed_splits) - 1):
                displayed_splits[i] = min(displayed_splits[i], remaining)
                remaining -= displayed_splits[i]
            displayed_splits[-1] = remaining
        fields.update(
            display_amount=money_text(money(amount)),
            display_exchange_rate=str(rate.quantize(RATE, rounding=ROUND_HALF_UP)),
            display_exchange_rate_date=effective_day.isoformat(),
            display_exchange_rate_source=source,
        )
        for row, value in zip(fields["splits"], displayed_splits):
            row["display_amount"] = money_text(value)
    except HTTPException as exc:
        if exc.status_code not in (422, 502):
            raise
        # Keep the authorized detail readable when historical FX is unavailable.
        # A missing conversion is never presented as a number in another currency.
        fields["display_money_error"] = str(exc.detail)
    return fields

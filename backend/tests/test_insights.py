"""Tests for the Smart Insights endpoint."""

from datetime import date, timedelta
from decimal import Decimal

from conftest import set_mode, USER_A, USER_B
from models import Expense


# ── Empty database ─────────────────────────────────────────────────────


def test_insights_empty_db(auth_client_a):
    data = auth_client_a.get("/api/insights").json()
    assert data["recurring_expenses"] == []
    assert data["recurring_alerts"] == []
    ww = data["weekend_vs_weekday"]
    assert ww["your_expense"]["weekday"]["total"] == 0
    assert ww["your_expense"]["weekend"]["total"] == 0
    assert ww["shared_expense"]["weekday"]["total"] == 0
    assert ww["shared_expense"]["weekend"]["total"] == 0
    assert data["anomalies"] == []
    assert data["forecast"]["total_forecast"] == 0
    assert data["top_growing_categories"] == []
    assert data["mode"] == "shared"


def test_insights_requires_auth(client):
    resp = client.get("/api/insights")
    assert resp.status_code == 401


# ── Mode in response ─────────────────────────────────────────────────


def test_mode_in_response(auth_client_a, db):
    set_mode(db, "personal")
    data = auth_client_a.get("/api/insights").json()
    assert data["mode"] == "personal"

    set_mode(db, "blended")
    data = auth_client_a.get("/api/insights").json()
    assert data["mode"] == "blended"


# ── Payload caching ─────────────────────────────────────────────────────


def test_insights_cache_hit_avoids_recomputation(auth_client_a, monkeypatch):
    """A second identical /insights call must be served from cache, not
    recompute recurring detection from scratch -- the entire point of
    this bucket's item 1."""
    import routes.insights as insights_mod
    calls = {"n": 0}
    original = insights_mod._detect_recurring

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(insights_mod, "_detect_recurring", counting)

    auth_client_a.get("/api/insights")
    auth_client_a.get("/api/insights")
    assert calls["n"] == 1


# ── Payment/Reimbursement exclusion ────────────────────────────────────


# ── Weekend vs Weekday ─────────────────────────────────────────────────


# ── Recurring detection ────────────────────────────────────────────────


# ── Recurring change alerts ────────────────────────────────────────────


# ── Price-step alerts, new-subscription alerts, and dismiss (bucket 10) ─


def test_dismiss_alert_rejects_invalid_alert_type(auth_client_a):
    resp = auth_client_a.post(
        "/api/insights/alerts/dismiss",
        json={"series_key": "Subscription::Netflix", "alert_type": "bogus"},
    )
    assert resp.status_code == 400


# ── Anomaly detection ──────────────────────────────────────────────────


def test_anomaly_leave_one_out_excludes_candidate_from_its_own_baseline():
    """The candidate's own amount must not appear in the median/MAD it's
    compared against -- otherwise the "usual" figure reported alongside the
    anomaly is itself pulled toward the outlier. With baseline [10, 20, 30,
    40] (median 25) and a $1000 candidate, including the candidate in its
    own baseline (5 values) shifts the computed median to 30 -- a real,
    observable bias -- whereas excluding it (leave-one-out, 4 values)
    correctly reports the true baseline median of 25."""
    from routes.insights import _detect_anomalies

    today = date.today()
    expenses = []
    exp_id = 1
    for amt in ("10.00", "20.00", "30.00", "40.00"):
        expenses.append(Expense(
            id=exp_id, date=today - timedelta(days=exp_id + 2), description=f"Shopping trip {exp_id}",
            amount=Decimal(amt), category="Shopping", paid_by=USER_A, split_method="Personal",
        ))
        exp_id += 1
    expenses.append(Expense(
        id=exp_id, date=today, description="Huge shopping spree",
        amount=Decimal("1000.00"), category="Shopping", paid_by=USER_A, split_method="Personal",
    ))

    anomalies = _detect_anomalies(expenses, USER_A, USER_B)
    big = next(a for a in anomalies if a["amount"] == 1000.0)
    # Leave-one-out: median/MAD of [10, 20, 30, 40] only -- NOT the
    # naive/inclusive median of 30 that including the $1000 itself would give.
    assert big["category_median"] == 25.0
    assert big["category_mad"] == 10.0


# ── Category trend alerts (bucket 10, item 3: prorate + attribution) ───


def test_category_trend_prorates_by_day_of_month():
    """Direct, exact-value check of the fix: MTD is compared against the
    median spend through the *same day-of-month* in the prior 3 months, not
    a full-month average. The bug this replaces: on the 12th you're only
    ~40% through the month, so a category on pace to nearly double its usual
    spend still reads "down" against a full-month baseline (150 vs 160 here)
    -- comparing prorated-to-prorated instead correctly reads it as "up".
    """
    from routes.insights import _category_trend_alerts

    frozen_today = date(2026, 3, 12)
    expenses = []
    exp_id = 1
    # Prior 3 months (Dec, Jan, Feb): $70 by the 12th, $160 by month end.
    for month in (12, 1, 2):
        year = 2025 if month == 12 else 2026
        for day, amt in ((5, "40.00"), (10, "30.00"), (20, "90.00")):
            expenses.append(Expense(
                id=exp_id, date=date(year, month, day), description=f"Dinner {year}-{month}-{day}",
                amount=Decimal(amt), category="Dining", paid_by=USER_A, split_method="Personal",
            ))
            exp_id += 1
    # Current month (March) MTD by the 12th: $150 -- more than double the
    # usual $70 pace, but nowhere near the $160 full-month average.
    for day, amt in ((5, "80.00"), (10, "70.00")):
        expenses.append(Expense(
            id=exp_id, date=date(2026, 3, day), description=f"Dinner current-{day}",
            amount=Decimal(amt), category="Dining", paid_by=USER_A, split_method="Personal",
        ))
        exp_id += 1

    alerts = _category_trend_alerts(expenses, USER_A, USER_B, anomalies=[], price_step_alerts=[], today=frozen_today)
    dining = next(a for a in alerts if a["category"] == "Dining")
    assert dining["current_month_amount"] == 150.0
    assert dining["three_month_avg"] == 70.0
    assert dining["three_month_full_avg"] == 160.0
    assert dining["change_pct"] == round((150.0 - 70.0) / 70.0 * 100, 1)
    assert dining["direction"] == "up"


def test_category_trend_attribution_suppresses_when_anomaly_explains_excess():
    """If a category's MTD excess is already explained by an anomaly this
    month, the trend alert must be suppressed -- one insight, not two, for
    the same root cause."""
    from routes.insights import _category_trend_alerts

    frozen_today = date(2026, 3, 12)
    expenses = []
    exp_id = 1
    for month in (12, 1, 2):
        year = 2025 if month == 12 else 2026
        expenses.append(Expense(
            id=exp_id, date=date(year, month, 5), description=f"Dinner {year}-{month}",
            amount=Decimal("50.00"), category="Dining", paid_by=USER_A, split_method="Personal",
        ))
        exp_id += 1
    expenses.append(Expense(
        id=exp_id, date=date(2026, 3, 5), description="Normal dinner",
        amount=Decimal("50.00"), category="Dining", paid_by=USER_A, split_method="Personal",
    ))
    exp_id += 1
    expenses.append(Expense(
        id=exp_id, date=date(2026, 3, 8), description="Huge one-off dinner",
        amount=Decimal("500.00"), category="Dining", paid_by=USER_A, split_method="Personal",
    ))

    anomalies = [{"category": "Dining", "date": "2026-03-08", "my_portion": 500.0}]
    alerts = _category_trend_alerts(expenses, USER_A, USER_B, anomalies=anomalies, price_step_alerts=[], today=frozen_today)
    assert not any(a["category"] == "Dining" for a in alerts)

    # Without the anomaly to attribute against, the identical spend WOULD
    # fire -- proving the suppression above is doing real work, not
    # vacuously true because the alert wouldn't have fired anyway.
    alerts_unattributed = _category_trend_alerts(expenses, USER_A, USER_B, anomalies=[], price_step_alerts=[], today=frozen_today)
    assert any(a["category"] == "Dining" for a in alerts_unattributed)


def test_category_trend_attribution_suppresses_when_price_step_explains_excess():
    """Same idea as the anomaly case, but attributed to a detected
    recurring price-step alert (item 2) instead."""
    from routes.insights import _category_trend_alerts

    frozen_today = date(2026, 3, 12)
    expenses = []
    exp_id = 1
    for month in (12, 1, 2):
        year = 2025 if month == 12 else 2026
        expenses.append(Expense(
            id=exp_id, date=date(year, month, 5), description=f"Bill {year}-{month}",
            amount=Decimal("50.00"), category="Dining", paid_by=USER_A, split_method="Personal",
        ))
        exp_id += 1
    expenses.append(Expense(
        id=exp_id, date=date(2026, 3, 5), description="Bill current",
        amount=Decimal("150.00"), category="Dining", paid_by=USER_A, split_method="Personal",
    ))

    price_step_alerts = [{"category": "Dining", "my_current_amount": 150.0, "my_previous_avg": 50.0}]
    alerts = _category_trend_alerts(expenses, USER_A, USER_B, anomalies=[], price_step_alerts=price_step_alerts, today=frozen_today)
    assert not any(a["category"] == "Dining" for a in alerts)

    alerts_unattributed = _category_trend_alerts(expenses, USER_A, USER_B, anomalies=[], price_step_alerts=[], today=frozen_today)
    assert any(a["category"] == "Dining" for a in alerts_unattributed)


# ── Forecast ───────────────────────────────────────────────────────────


def _month_ago(base: date, n: int) -> date:
    """n calendar months before base, same day-of-month (15th, always valid)."""
    y, m = base.year, base.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 15)


def _no_fuzzy_clustering(monkeypatch):
    """Force exact-description-match only (no embedding-similarity
    merging), so a test can use several distinct one-off descriptions
    within one category and be certain none of them accidentally cluster
    into a 3+-occurrence "recurring" series -- deterministic regardless of
    the real embedding model's similarity scores (same rationale as
    test_suggestions.py's `cluster_descriptions` monkeypatch, bucket 08)."""
    import routes.insights as insights_mod
    monkeypatch.setattr(
        insights_mod, "cluster_descriptions_all",
        lambda descs, threshold=0.85: [[i] for i in range(len(descs))],
    )


def test_forecast_empty_db(auth_client_a):
    data = auth_client_a.get("/api/insights").json()
    forecast = data["forecast"]
    assert forecast["total_forecast"] == 0
    assert forecast["by_category"] == []
    assert forecast["scheduled_bills"] == []
    assert forecast["upcoming_bills"] == []
    assert forecast["range"] is None


def test_annual_bill_appears_only_in_its_due_month(auth_client_a):
    """Direct unit-level check (bypassing the API so `today` can be frozen
    precisely, independent of when this test happens to run): an annual
    series' scheduled amount must appear in the forecast only for the
    calendar month containing its projected due date, not the months
    before or after."""
    from routes.insights import _detect_recurring, _forecast

    expenses = [
        Expense(id=1, date=date(2023, 3, 15), description="Car Insurance", amount=Decimal("600.00"),
                category="Car Insurance", paid_by=USER_A, split_method="Personal"),
        Expense(id=2, date=date(2024, 3, 15), description="Car Insurance", amount=Decimal("600.00"),
                category="Car Insurance", paid_by=USER_A, split_method="Personal"),
        Expense(id=3, date=date(2025, 3, 15), description="Car Insurance", amount=Decimal("600.00"),
                category="Car Insurance", paid_by=USER_A, split_method="Personal"),
    ]

    # "Today" = Feb 1 2026 -> target month = March 2026, which contains the
    # projected next_due (2025-03-15 + ~365 days ~= 2026-03-15).
    frozen_today = date(2026, 2, 1)
    recurring, member_ids = _detect_recurring(expenses, USER_A, USER_B, today=frozen_today)
    car = next(r for r in recurring if r["description"] == "Car Insurance")
    assert car["frequency"] == "Annual"

    forecast_hit = _forecast(expenses, recurring, member_ids, USER_A, USER_B, today=frozen_today)
    assert forecast_hit["recurring_total"] == 600.0
    assert forecast_hit["scheduled_bills"] == [{
        "description": "Car Insurance",
        "category": "Car Insurance",
        "due_date": "2026-03-15",
        "amount": 600.0,
        "my_amount": 600.0,
    }]

    # A different "today" (April 2026) -> target month = May 2026, which
    # does NOT contain the annual due date -> the bill must not appear.
    frozen_today_2 = date(2026, 4, 1)
    recurring2, member_ids2 = _detect_recurring(expenses, USER_A, USER_B, today=frozen_today_2)
    forecast_miss = _forecast(expenses, recurring2, member_ids2, USER_A, USER_B, today=frozen_today_2)
    assert forecast_miss["recurring_total"] == 0
    assert forecast_miss["scheduled_bills"] == []


# ── Top growing categories ─────────────────────────────────────────────


# ── Personal mode ─────────────────────────────────────────────────────


# ── Income insights ───────────────────────────────────────────────────


def test_income_insights_none_shared(auth_client_a):
    """In shared mode, income_insights should be None."""
    data = auth_client_a.get("/api/insights").json()
    assert data["income_insights"] is None


def test_income_insights_no_income_data(auth_client_a, db):
    """In blended mode with no income entries, income_insights should be None."""
    set_mode(db, "blended")
    data = auth_client_a.get("/api/insights").json()
    assert data["income_insights"] is None

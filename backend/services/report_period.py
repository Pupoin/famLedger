"""One calendar contract for dashboards and financial reports."""
import calendar
import datetime as dt
import re
from fastapi import HTTPException


def month_shift(day, months):
    index = day.year * 12 + day.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


def resolve_period(period="monthly", selected_month=None, start_date=None, end_date=None, today=None):
    today = today or dt.date.today()
    try:
        if selected_month and not re.fullmatch(r"\d{4}-\d{2}", selected_month):
            raise ValueError("月份必须为 YYYY-MM")
        y, m = map(int, (selected_month or today.strftime("%Y-%m")).split("-"))
        if not 1900 <= y <= 2100 or not 1 <= m <= 12:
            raise ValueError("月份超出支持范围")
        first = dt.date(y, m, 1)
        last = dt.date(y, m, calendar.monthrange(y, m)[1])
        normalized = (period or "monthly").lower()
        if normalized in {"monthly", "mtd"}:
            start, end = first, last
            prev_start = month_shift(first, -1)
            prev_end = first - dt.timedelta(days=1)
        elif normalized == "quarterly":
            start = dt.date(y, (m - 1) // 3 * 3 + 1, 1)
            end = month_shift(start, 3) - dt.timedelta(days=1)
            prev_start, prev_end = month_shift(start, -3), start - dt.timedelta(days=1)
        elif normalized == "6m":
            start, end = month_shift(first, -5), last
            prev_start, prev_end = month_shift(start, -6), start - dt.timedelta(days=1)
        elif normalized == "ytd":
            start, end = dt.date(y, 1, 1), last
            prev_start = dt.date(y - 1, 1, 1)
            prev_end = dt.date(y - 1, m, calendar.monthrange(y - 1, m)[1])
        elif normalized == "all":
            start, end = dt.date.min, today
            # All-history has no preceding comparable period.
            prev_start = prev_end = dt.date.min
        elif normalized == "30d":
            start, end = today - dt.timedelta(days=29), today
            prev_end = start - dt.timedelta(days=1)
            prev_start = prev_end - dt.timedelta(days=29)
        elif normalized == "custom":
            start = dt.date.fromisoformat(start_date) if start_date else first
            end = dt.date.fromisoformat(end_date) if end_date else last
            if start > end or start.year < 1900 or end.year > 2100:
                raise ValueError("日期范围无效")
            prev_end = start - dt.timedelta(days=1)
            prev_start = prev_end - (end - start)
        else:
            raise ValueError("不支持的统计周期")
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return start, end, prev_start, prev_end, y, m

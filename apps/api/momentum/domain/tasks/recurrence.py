"""S4.4.2: pure date math for `tasks.recurrence` (no DB access — see `service.py` for the part
that actually spawns the next task). The stored shape is `{freq, interval, by_weekday?,
workdays_only?, day_of_month?, week_of_month?, mode?, text?}`, validated by
`service._check_recurrence`. `day_of_month` pins a monthly or yearly series to its day (set
automatically on the first spawn), so short months clamp without drifting."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

MAX_SEARCH_DAYS = 400  # a generous bound so a bad rule can't loop forever


def _add_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """`n` is 1-4 for the nth such weekday, or -1 for the last one in the month."""
    last_day = calendar.monthrange(year, month)[1]
    if n == -1:
        d = date(year, month, last_day)
        return d - timedelta(days=(d.weekday() - weekday) % 7)
    first = date(year, month, 1)
    day = 1 + (weekday - first.weekday()) % 7 + (n - 1) * 7
    if day > last_day:
        day -= 7  # the month doesn't have a 5th occurrence: fall back to the 4th
    return date(year, month, day)


def _next_weekly(after: date, days: list[int], interval: int) -> date:
    anchor_week = after - timedelta(days=after.weekday())
    d = after + timedelta(days=1)
    for _ in range(MAX_SEARCH_DAYS):
        week_start = d - timedelta(days=d.weekday())
        weeks_since = (week_start - anchor_week).days // 7
        if weeks_since % interval == 0 and d.weekday() in days:
            return d
        d += timedelta(days=1)
    raise ValueError("no matching weekday found within the search window")


def _next_daily(after: date, interval: int, workdays_only: bool) -> date:
    d = after + timedelta(days=interval)
    if workdays_only:
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d


def _next_monthly(after: date, recur: dict[str, Any], interval: int) -> date:
    base = _add_months(date(after.year, after.month, 1), interval)
    if recur.get("day_of_month") is not None:
        dom = recur["day_of_month"]
        last_day = calendar.monthrange(base.year, base.month)[1]
        day = last_day if dom == -1 else min(dom, last_day)
        return date(base.year, base.month, day)
    if recur.get("week_of_month") is not None:
        weekday = (recur.get("by_weekday") or [after.weekday()])[0]
        return _nth_weekday_of_month(base.year, base.month, weekday, recur["week_of_month"])
    return _add_months(after, interval)


def _next_yearly(after: date, interval: int, day: int | None = None) -> date:
    """Same month, `interval` years on; `day` (the series' day, e.g. 29 for a Feb 29 task) is
    clamped to the month's length, so Feb 29 is Feb 28 in common years and Feb 29 again in leap
    years."""
    year = after.year + interval
    last = calendar.monthrange(year, after.month)[1]
    want = last if day == -1 else (day if day is not None and day > 0 else after.day)
    return date(year, after.month, min(want, last))


def next_occurrence(after: date, recur: dict[str, Any]) -> date:
    """The next date strictly after `after` that satisfies the recurrence rule."""
    interval = recur.get("interval", 1)
    freq = recur["freq"]
    if freq == "daily":
        return _next_daily(after, interval, bool(recur.get("workdays_only")))
    if freq == "weekly":
        days = sorted(recur.get("by_weekday") or [after.weekday()])
        return _next_weekly(after, days, interval)
    if freq == "monthly":
        return _next_monthly(after, recur, interval)
    if freq == "yearly":
        return _next_yearly(after, interval, recur.get("day_of_month"))
    raise ValueError(f"Unknown recurrence freq {freq!r}")

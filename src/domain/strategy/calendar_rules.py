"""Domain Strategy: Calendar anomalies and VN holiday rules.
Pure Python standard library only (no pandas, no numpy).
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

# Official closed trading days on HOSE / HNX (2017 - 2027)
VN_CLOSED_DAYS: frozenset[date] = frozenset(
    date.fromisoformat(d)
    for d in (
        "2017-01-02 2017-01-26 2017-01-27 2017-01-30 2017-01-31 2017-02-01 2017-02-02 "
        "2017-04-06 2017-05-01 2017-05-02 2017-09-04 "
        "2018-12-31 2018-01-01 2018-02-14 2018-02-15 2018-02-16 2018-02-19 2018-02-20 "
        "2018-04-25 2018-04-30 2018-05-01 2018-09-03 "
        "2019-01-01 2019-02-04 2019-02-05 2019-02-06 2019-02-07 2019-02-08 "
        "2019-04-15 2019-04-29 2019-04-30 2019-05-01 2019-09-02 "
        "2020-01-01 2020-01-23 2020-01-24 2020-01-27 2020-01-28 2020-01-29 "
        "2020-04-02 2020-04-30 2020-05-01 2020-09-02 "
        "2021-01-01 2021-02-10 2021-02-11 2021-02-12 2021-02-15 2021-02-16 "
        "2021-04-21 2021-04-30 2021-05-03 2021-09-02 2021-09-03 "
        "2022-01-03 2022-01-31 2022-02-01 2022-02-02 2022-02-03 2022-02-04 "
        "2022-04-11 2022-05-02 2022-05-03 2022-09-01 2022-09-02 "
        "2023-01-02 2023-01-20 2023-01-23 2023-01-24 2023-01-25 2023-01-26 "
        "2023-05-01 2023-05-02 2023-05-03 2023-09-01 2023-09-04 "
        "2024-01-01 2024-02-08 2024-02-09 2024-02-12 2024-02-13 2024-02-14 "
        "2024-04-18 2024-04-29 2024-04-30 2024-05-01 2024-09-02 2024-09-03 "
        "2025-01-01 2025-01-27 2025-01-28 2025-01-29 2025-01-30 2025-01-31 "
        "2025-04-07 2025-04-30 2025-05-01 2025-05-02 2025-09-01 2025-09-02 "
        "2026-01-01 2026-02-16 2026-02-17 2026-02-18 2026-02-19 2026-02-20 "
        "2026-01-02 2026-04-27 2026-04-30 2026-05-01 2026-08-31 2026-09-01 2026-09-02 "
        "2027-01-01 2027-02-05 2027-02-08 2027-02-09 2027-02-10 2027-02-11 "
        "2027-04-16 2027-04-30 2027-05-03 2027-09-02 2027-09-03"
    ).split()
)


def is_trading_day(d: date) -> bool:
    """True if Monday-Friday and not an official closed holiday."""
    return d.weekday() < 5 and d not in VN_CLOSED_DAYS


def next_trading_day(d: date) -> date:
    """Find next open trading session skipping weekends and public holidays."""
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def is_pre_holiday(d: date) -> bool:
    """True if this is the last session before an extended holiday break."""
    if not is_trading_day(d):
        return False
    nxt = next_trading_day(d)
    calendar_gap = (nxt - d).days
    normal_gap = 3 if d.weekday() == 4 else 1  # Friday usually has 3-day gap until Monday
    return calendar_gap > normal_gap


def is_expiry_thursday(d: date) -> bool:
    """Whether ``d`` is the VN30F last trading day for its contract month.

    The nominal date is the third Thursday.  When that is an exchange closure,
    the last trading day moves to the immediately preceding trading day.
    """

    month_cal = calendar.monthcalendar(d.year, d.month)
    thursdays = [week[calendar.THURSDAY] for week in month_cal if week[calendar.THURSDAY] != 0]
    nominal = date(d.year, d.month, thursdays[2])
    while not is_trading_day(nominal):
        nominal -= timedelta(days=1)
    return d == nominal


def business_day_index_in_month(d: date) -> int:
    """Count how many trading days have occurred in month before d (0-indexed)."""
    count = 0
    cur = date(d.year, d.month, 1)
    while cur < d:
        if is_trading_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count


def is_start_of_month(d: date) -> bool:
    """True for the first 2 trading days of the calendar month (SOM2)."""
    return is_trading_day(d) and business_day_index_in_month(d) < 2


def is_regular_monday(d: date) -> bool:
    """True if regular Monday (not SOM2 and not immediately before a holiday)."""
    return d.weekday() == 0 and is_trading_day(d) and not is_start_of_month(d) and not is_pre_holiday(d)


def is_calendar_long_day(
    d: date,
    *,
    use_som2: bool = True,
    use_preholiday: bool = True,
    use_tue_wed: bool = True,
) -> bool:
    """Checks if date is a core Calendar Long day."""
    if not is_trading_day(d):
        return False
    if use_som2 and is_start_of_month(d):
        return True
    if use_preholiday and is_pre_holiday(d):
        return True
    if use_tue_wed and d.weekday() in (1, 2):  # Tuesday=1, Wednesday=2
        return True
    return False

"""Calendar rules used by the live HybridGated runtime.

This module is dependency-free but intentionally mirrors
``alphas/PS_V30_Vien_hybrid_gated/hybrid_signal.py``.  In particular, SOM2
means the first two *actual HOSE trading sessions* of a month and the next
session skips both weekends and the explicit holiday table.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

HCM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
AFTERNOON_DECISION_START = time(14, 24, 0)
AFTERNOON_DECISION_END = time(14, 29, 45)
MORNING_DECISION_START = time(9, 16, 0)
MORNING_DECISION_END = time(9, 29, 45)
NO_NEW_ORDER_AFTER = time(14, 30, 0)
ROLLOVER_TIME = time(15, 0, 0)

_CLOSED_TEXT = """
2017-01-02 2017-01-26 2017-01-27 2017-01-30 2017-01-31 2017-02-01 2017-02-02
2017-04-06 2017-05-01 2017-05-02 2017-09-04
2018-12-31 2018-01-01 2018-02-14 2018-02-15 2018-02-16 2018-02-19 2018-02-20
2018-04-25 2018-04-30 2018-05-01 2018-09-03
2019-01-01 2019-02-04 2019-02-05 2019-02-06 2019-02-07 2019-02-08
2019-04-15 2019-04-29 2019-04-30 2019-05-01 2019-09-02
2020-01-01 2020-01-23 2020-01-24 2020-01-27 2020-01-28 2020-01-29
2020-04-02 2020-04-30 2020-05-01 2020-09-02
2021-01-01 2021-02-10 2021-02-11 2021-02-12 2021-02-15 2021-02-16
2021-04-21 2021-04-30 2021-05-03 2021-09-02 2021-09-03
2022-01-03 2022-01-31 2022-02-01 2022-02-02 2022-02-03 2022-02-04
2022-04-11 2022-05-02 2022-05-03 2022-09-01 2022-09-02
2023-01-02 2023-01-20 2023-01-23 2023-01-24 2023-01-25 2023-01-26
2023-05-01 2023-05-02 2023-05-03 2023-09-01 2023-09-04
2024-01-01 2024-02-08 2024-02-09 2024-02-12 2024-02-13 2024-02-14
2024-04-18 2024-04-29 2024-04-30 2024-05-01 2024-09-02 2024-09-03
2025-01-01 2025-01-27 2025-01-28 2025-01-29 2025-01-30 2025-01-31
2025-04-07 2025-04-30 2025-05-01 2025-09-01 2025-09-02
2026-01-01 2026-02-16 2026-02-17 2026-02-18 2026-02-19 2026-02-20
2026-04-27 2026-04-30 2026-05-01 2026-08-31 2026-09-01 2026-09-02
2027-01-01 2027-02-05 2027-02-08 2027-02-09 2027-02-10 2027-02-11
2027-04-16 2027-04-30 2027-05-03 2027-09-02 2027-09-03
"""

CLOSED_DATES = frozenset(date.fromisoformat(value) for value in _CLOSED_TEXT.split())
HOLIDAY_COVERED_TO = date(2027, 12, 31)
_CONTRACT_RE = re.compile(r"^(?P<exchange>[A-Z0-9]+):VN30F(?P<yy>\d{2})(?P<mm>\d{2})$")


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in CLOSED_DATES


def next_trading_day(day: date) -> date:
    candidate = day + timedelta(days=1)
    for _ in range(14):
        if is_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError(f"Cannot resolve next trading day after {day}")


def trading_session_index_in_month(day: date) -> int:
    """Zero-based ordinal among real HOSE sessions in ``day``'s month."""
    cursor = day.replace(day=1)
    ordinal = 0
    while cursor < day:
        if is_trading_day(cursor):
            ordinal += 1
        cursor += timedelta(days=1)
    return ordinal


def is_pre_holiday(day: date) -> bool:
    if not is_trading_day(day):
        return False
    gap = (next_trading_day(day) - day).days
    normal_gap = 3 if day.weekday() == 4 else 1
    return gap > normal_gap


def core_long_reasons(
    day: date,
    *,
    long_dows: tuple[int, ...] = (1, 2),
    use_month_start: bool = True,
    use_preholiday: bool = True,
) -> tuple[str, ...]:
    if not is_trading_day(day):
        return ()
    reasons: list[str] = []
    if day.weekday() in long_dows:
        reasons.append("tue_wed")
    if use_month_start and trading_session_index_in_month(day) < 2:
        reasons.append("som2")
    if use_preholiday and is_pre_holiday(day):
        reasons.append("pre_holiday")
    return tuple(reasons)


def is_regular_monday(day: date) -> bool:
    return (
        is_trading_day(day)
        and day.weekday() == 0
        and trading_session_index_in_month(day) >= 2
        and not is_pre_holiday(day)
    )


def third_thursday(year: int, month: int) -> date:
    first_weekday, _ = calendar.monthrange(year, month)
    return date(year, month, 1 + (3 - first_weekday) % 7 + 14)


def is_expiry_session(day: date) -> bool:
    return day == third_thursday(day.year, day.month)


def is_post_expiry_friday(day: date) -> bool:
    if not is_trading_day(day) or day.weekday() != 4:
        return False
    return is_expiry_session(day - timedelta(days=1))


def is_post_expiry_monday(day: date) -> bool:
    if not is_trading_day(day) or day.weekday() != 0:
        return False
    return is_post_expiry_friday(day - timedelta(days=3))


def in_morning_decision_window(local_now: datetime) -> bool:
    local_now = local_now.astimezone(HCM_TZ)
    return (
        is_trading_day(local_now.date())
        and MORNING_DECISION_START <= local_now.time() <= MORNING_DECISION_END
    )


def in_afternoon_decision_window(local_now: datetime) -> bool:
    local_now = local_now.astimezone(HCM_TZ)
    return (
        is_trading_day(local_now.date())
        and AFTERNOON_DECISION_START <= local_now.time() <= AFTERNOON_DECISION_END
    )


def market_is_open(local_now: datetime) -> bool:
    local_now = local_now.astimezone(HCM_TZ)
    if not is_trading_day(local_now.date()):
        return False
    current = local_now.time()
    return time(9, 0) <= current <= time(11, 30) or time(13, 0) <= current <= time(14, 45)


def order_submission_allowed(local_now: datetime) -> bool:
    local_now = local_now.astimezone(HCM_TZ)
    return market_is_open(local_now) and local_now.time() < NO_NEW_ORDER_AFTER


def add_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def active_contract_month(local_now: datetime) -> tuple[int, int]:
    local_now = local_now.astimezone(HCM_TZ)
    year, month = local_now.year, local_now.month
    expiry = third_thursday(year, month)
    if local_now.date() > expiry or (
        local_now.date() == expiry and local_now.time() >= ROLLOVER_TIME
    ):
        year, month = add_month(year, month)
    return year, month


def front_month_symbol(local_now: datetime, exchange: str = "HNXDS") -> str:
    year, month = active_contract_month(local_now)
    return f"{exchange}:VN30F{year % 100:02d}{month:02d}"


def contract_expiry(symbol: str) -> date:
    match = _CONTRACT_RE.fullmatch(symbol)
    if match is None:
        raise ValueError(f"Unsupported VN30 futures symbol: {symbol!r}")
    year = 2000 + int(match.group("yy"))
    month = int(match.group("mm"))
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid contract month in {symbol!r}")
    return third_thursday(year, month)


def next_decision_plan(local_now: datetime) -> tuple[datetime, date, tuple[str, ...]]:
    local_now = local_now.astimezone(HCM_TZ)
    decision_day = local_now.date()
    if not is_trading_day(decision_day) or local_now.time() > AFTERNOON_DECISION_END:
        decision_day = next_trading_day(decision_day)
    decision_at = datetime.combine(decision_day, AFTERNOON_DECISION_START, tzinfo=HCM_TZ)
    signal_day = next_trading_day(decision_day)
    return decision_at, signal_day, core_long_reasons(signal_day)

"""Pure-calendar schedule shared by the PaperTrade calendar runtime.

The signal intentionally mirrors ``PS_V30_Vien_calendar``: Tue/Wed, the
first two weekdays of a month, and the final trading session before a listed
Vietnamese exchange holiday.  It never derives holidays from market data.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from alphas.market_schedule import (
    CLOSED_DATES,
    HCM_TZ,
    HOLIDAY_COVERED_TO,
    active_contract_month,
    add_month,
    contract_expiry,
    front_month_symbol,
    is_pre_holiday,
    is_trading_day,
    market_is_open,
    next_trading_day,
    third_thursday,
)

DECISION_START = time(14, 24, 0)
DECISION_END = time(14, 29, 45)
MONDAY_DECISION_START = time(9, 16, 0)
MONDAY_DECISION_END = time(9, 30, 0)
ROLLOVER_TIME = time(15, 0, 0)


def next_weekday(day: date) -> date:
    """Mirror the backtest's next-weekday arithmetic (holidays not skipped)."""
    return day + timedelta(days=3 if day.weekday() == 4 else 1)


def weekday_index_in_month(day: date) -> int:
    """Zero-based Mon-Fri ordinal, matching the original pandas helper."""
    cursor = day.replace(day=1)
    count = -1
    while cursor <= day:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def is_regular_monday(day: date, min_session_index: int = 3) -> bool:
    """Check if day is a regular Monday (not SOM3, not pre-holiday)."""
    if not is_trading_day(day) or day.weekday() != 0:
        return False
    if weekday_index_in_month(day) < min_session_index:
        return False
    if is_pre_holiday(day):
        return False
    return True


def in_monday_decision_window(local_now: datetime) -> bool:
    """Morning window right after ATO (09:16 - 09:30 ICT) on regular Mondays."""
    local_now = local_now.astimezone(HCM_TZ)
    return (
        is_regular_monday(local_now.date())
        and MONDAY_DECISION_START <= local_now.time() <= MONDAY_DECISION_END
    )


def monday_short_target(gap: float, monday_max_gap: float = 0.0) -> int:
    """Return -1 if ATO gap <= monday_max_gap, else 0."""
    return -1 if gap <= monday_max_gap else 0


def target_reasons(
    day: date,
    *,
    use_tue_wed: bool = True,
    use_month_start: bool = True,
    use_preholiday: bool = True,
    use_expiry_thursday: bool = True,
) -> tuple[str, ...]:
    if not is_trading_day(day):
        return ()
    reasons: list[str] = []
    if use_tue_wed and day.weekday() in (1, 2):
        reasons.append("tue_wed")
    if use_month_start and weekday_index_in_month(day) < 2:
        reasons.append("som2")
    if use_preholiday and is_pre_holiday(day):
        reasons.append("pre_holiday")
    if use_expiry_thursday and day == third_thursday(day.year, day.month):
        reasons.append("expiry_thursday")
    return tuple(reasons)


def decision_target(local_now: datetime, symbol: str) -> tuple[int, date, tuple[str, ...]]:
    """Return desired unit position for the next calendar weekday.

    The expiring contract is always flattened in its final decision window;
    the supervisor changes to the next contract after 15:00 ICT.
    """
    local_now = local_now.astimezone(HCM_TZ)
    signal_day = next_weekday(local_now.date())
    reasons = target_reasons(signal_day)
    if local_now.date() == contract_expiry(symbol):
        return 0, signal_day, ("expiry_flatten",)
    return (1 if reasons else 0), signal_day, reasons


def next_decision_plan(
    local_now: datetime,
    symbol: str,
) -> tuple[datetime, int, date, tuple[str, ...]]:
    """Describe the current or next decision window without reading market data."""
    local_now = local_now.astimezone(HCM_TZ)
    session_day = local_now.date()
    if not is_trading_day(session_day) or local_now.time() > DECISION_END:
        session_day = next_trading_day(session_day)
    decision_at = datetime.combine(session_day, DECISION_START, tzinfo=HCM_TZ)
    target, signal_day, reasons = decision_target(decision_at, symbol)
    return decision_at, target, signal_day, reasons


def in_decision_window(local_now: datetime) -> bool:
    local_now = local_now.astimezone(HCM_TZ)
    return (
        is_trading_day(local_now.date())
        and DECISION_START <= local_now.time() <= DECISION_END
    )

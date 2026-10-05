"""Calendar rules used by the live HybridGated runtime.

This module is dependency-free but intentionally mirrors
``alphas/PS_V30_Vien_hybrid_gated/hybrid_signal.py``.  In particular, SOM2
means the first two *actual HOSE trading sessions* of a month and the next
session skips both weekends and the explicit holiday table.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from alphas.market_schedule import (
    CLOSED_DATES,
    HCM_TZ,
    HOLIDAY_COVERED_TO,
    ROLLOVER_TIME,
    active_contract_month,
    add_month,
    contract_expiry,
    front_month_symbol,
    is_expiry_session,
    is_post_expiry_friday,
    is_post_expiry_monday,
    is_pre_holiday,
    is_regular_monday,
    is_trading_day,
    market_is_open,
    next_trading_day,
    third_thursday,
    trading_session_index_in_month,
)

AFTERNOON_DECISION_START = time(14, 24, 0)
AFTERNOON_DECISION_END = time(14, 29, 45)
MORNING_DECISION_START = time(9, 16, 0)
MORNING_DECISION_END = time(9, 29, 45)
NO_NEW_ORDER_AFTER = time(14, 30, 0)


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


def order_submission_allowed(local_now: datetime) -> bool:
    local_now = local_now.astimezone(HCM_TZ)
    return market_is_open(local_now) and local_now.time() < NO_NEW_ORDER_AFTER


def next_decision_plan(local_now: datetime) -> tuple[datetime, date, tuple[str, ...]]:
    local_now = local_now.astimezone(HCM_TZ)
    decision_day = local_now.date()
    if not is_trading_day(decision_day) or local_now.time() > AFTERNOON_DECISION_END:
        decision_day = next_trading_day(decision_day)
    decision_at = datetime.combine(decision_day, AFTERNOON_DECISION_START, tzinfo=HCM_TZ)
    signal_day = next_trading_day(decision_day)
    return decision_at, signal_day, core_long_reasons(signal_day)

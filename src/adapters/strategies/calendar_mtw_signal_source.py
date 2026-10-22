"""Calendar MTW sleeve on 10-minute VN30F1M bars.

Ported from calendar-mtw-vn30f (``research/calendar-mtw/signals.py``), keeping
only the alpha chosen there in steps 4-5: M3 + W0X1 with the optimised
parameters (``ib_bars = 3``, Monday window to 13:00, W0 entry 14:20, X1 exit
10:00).

- Monday short (M3): every Monday, short at the first bar in the window after
  the initial balance (IB) whose close is below the IB low; exit at the close
  of Monday 14:20.
- Tuesday-Wednesday long (W0X1): long at the close of 14:20 of the session
  right before Tuesday; exit at the close of 10:00 of the session after
  Wednesday.

The stream excludes the ATC bar, so the last bar of a session is 14:20.
Position[t] is the position held after the close of bar t: a leg holds its
side from its entry bar up to, not including, its exit bar.  Legs are summed
and capped at one contract, as both trade one account.  A missing entry or
signal bar skips the leg; a missing exit bar moves the exit to the next bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd

from src.domain.strategy.calendar_rules import is_trading_day, next_trading_day

OPEN_BAR = time(9, 0)
LAST_BAR = time(14, 20)
ATC_BAR = time(14, 45)
MONDAY, TUESDAY = 0, 1


@dataclass(frozen=True)
class CalendarMtwParams:
    """Parameters locked by the calendar-mtw-vn30f step-5 optimisation."""

    ib_bars: int = 3
    monday_window_end: time = time(13, 0)
    w0_entry: time = LAST_BAR
    x1_exit: time = time(10, 0)


@dataclass(frozen=True)
class Leg:
    name: str
    side: int
    entry: pd.Timestamp
    exit_target: pd.Timestamp


@dataclass(frozen=True)
class Skip:
    name: str
    session: date
    reason: str


def drop_atc(bars: pd.DataFrame) -> pd.DataFrame:
    """10-minute bars without the ATC bar; the last bar of a session is 14:20."""
    stamps = pd.to_datetime(bars["Datetime"])
    kept = bars.loc[stamps.dt.time != ATC_BAR].copy()
    kept["Datetime"] = pd.to_datetime(kept["Datetime"])
    return kept.sort_values("Datetime").reset_index(drop=True)


def previous_trading_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def _at(d: date, t: time) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(d, t))


def _bar_after_open(bars: int) -> time:
    return (datetime.combine(date.min, OPEN_BAR) + timedelta(minutes=10 * bars)).time()


def add_ib_low(bars: pd.DataFrame, params: CalendarMtwParams = CalendarMtwParams()) -> pd.DataFrame:
    """Add IBLow, known from the first bar after the IB. Sessions missing an IB bar get NaN."""
    out = bars.reset_index(drop=True).copy()
    session = out["Datetime"].dt.normalize()
    tod = out["Datetime"].dt.time
    in_ib = tod.isin(tuple(_bar_after_open(i) for i in range(params.ib_bars)))
    ib = out[in_ib].groupby(session[in_ib])["Low"].agg(["size", "min"])
    ib_low = ib["min"].where(ib["size"] == params.ib_bars)
    out["IBLow"] = session.map(ib_low).where(tod >= _bar_after_open(params.ib_bars))
    return out


def _calendar_sessions(bars: pd.DataFrame, weekday: int) -> list[date]:
    first, last = bars["Datetime"].dt.date.min(), bars["Datetime"].dt.date.max()
    return [
        d.date() for d in pd.date_range(first, last)
        if d.weekday() == weekday and is_trading_day(d.date())
    ]


def monday_legs(
    bars: pd.DataFrame, params: CalendarMtwParams = CalendarMtwParams()
) -> tuple[list[Leg], list[Skip]]:
    """M3 short legs. ``bars`` must come from ``add_ib_low``."""
    by_day = dict(tuple(bars.groupby(bars["Datetime"].dt.date)))
    legs: list[Leg] = []
    skips: list[Skip] = []
    for day in _calendar_sessions(bars, MONDAY):
        if day not in by_day:
            skips.append(Skip("M3", day, "Monday session missing"))
            continue
        session = by_day[day]
        tod = session["Datetime"].dt.time
        window = session[(tod >= _bar_after_open(params.ib_bars)) & (tod <= params.monday_window_end)]
        if window["IBLow"].isna().all():
            skips.append(Skip("M3", day, "IB bars missing"))
            continue
        hit = window[window["Close"] < window["IBLow"]]
        if not hit.empty:
            legs.append(Leg("M3", -1, hit["Datetime"].iloc[0], _at(day, LAST_BAR)))
    return legs, skips


def midweek_legs(
    bars: pd.DataFrame, params: CalendarMtwParams = CalendarMtwParams()
) -> tuple[list[Leg], list[Skip]]:
    """W0X1 long legs."""
    by_time = bars.set_index("Datetime")
    by_day = dict(tuple(bars.groupby(bars["Datetime"].dt.date)))
    legs: list[Leg] = []
    skips: list[Skip] = []
    for day in _calendar_sessions(bars, TUESDAY):
        wednesday = day + timedelta(days=1)
        if not is_trading_day(wednesday):
            skips.append(Skip("W0X1", day, "Wednesday is a holiday"))
            continue
        if day not in by_day or wednesday not in by_day:
            skips.append(Skip("W0X1", day, "Tuesday or Wednesday session missing"))
            continue
        entry_at = _at(previous_trading_day(day), params.w0_entry)
        if entry_at not in by_time.index:
            skips.append(Skip("W0X1", day, f"no {entry_at:%Y-%m-%d %H:%M} entry bar"))
            continue
        exit_at = _at(next_trading_day(wednesday), params.x1_exit)
        legs.append(Leg("W0X1", 1, entry_at, exit_at))
    return legs, skips


def build_positions(bars: pd.DataFrame, legs: list[Leg]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Spread legs over the bar stream. Returns the Datetime/Close/Position stream and a leg table."""
    times = bars["Datetime"].to_numpy()
    position = pd.Series(0.0, index=bars.index)
    rows = []
    for leg in sorted(legs, key=lambda item: item.entry):
        start = int(times.searchsorted(leg.entry.to_datetime64()))
        stop = int(times.searchsorted(leg.exit_target.to_datetime64()))
        if stop >= len(times):
            continue
        position.iloc[start:stop] += leg.side
        rows.append({
            "Leg": leg.name,
            "Side": leg.side,
            "Entry": bars.at[start, "Datetime"],
            "EntryClose": bars.at[start, "Close"],
            "ExitTarget": leg.exit_target,
            "Exit": bars.at[stop, "Datetime"],
            "ExitClose": bars.at[stop, "Close"],
        })
    stream = bars[["Datetime", "Close"]].assign(Position=position.clip(-1.0, 1.0))
    return stream, pd.DataFrame(rows)


def calendar_mtw_stream(
    bars: pd.DataFrame,
    params: CalendarMtwParams = CalendarMtwParams(),
) -> tuple[pd.DataFrame, pd.DataFrame, list[Skip]]:
    """Position stream of the Calendar MTW sleeve on 10-minute bars without the ATC bar."""
    prepared = add_ib_low(bars, params)
    monday, monday_skips = monday_legs(prepared, params)
    midweek, midweek_skips = midweek_legs(prepared, params)
    stream, table = build_positions(prepared, monday + midweek)
    return stream, table, monday_skips + midweek_skips

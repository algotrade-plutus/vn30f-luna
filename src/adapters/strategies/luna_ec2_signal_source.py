"""Causal target generator matching the active EC2 HybridGated signal logic.

The production service evaluates quotes continuously.  Research data are
available as completed five-minute bars, so the two intrabar decisions are
represented at 09:20 (first complete bar after 09:16) and 14:25 (inside the
14:24--14:29:45 decision window).  No target change is exposed for execution
at or after 14:30.
"""
from __future__ import annotations

import calendar
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from src.domain.entities.bar import Bar
from src.domain.strategy.calendar_rules import VN_CLOSED_DAYS
from src.domain.strategy.t2_momentum import T2MomentumEngine


# These two dates exist in the local research calendar but not in the calendar
# embedded in the inspected EC2 release.  This module intentionally reproduces
# the remote code; the discrepancy is reported by the runner.
EC2_CLOSED_DAYS = frozenset(
    day
    for day in VN_CLOSED_DAYS
    if day not in {date(2025, 5, 2), date(2026, 1, 2)}
)
_CONTRACT_RE = re.compile(r"^VN30F(?P<yy>\d{2})(?P<mm>\d{2})$")


@dataclass(frozen=True)
class Ec2LunaReplayParameters:
    quantity: int = 8
    monday_max_gap_pct: float = 0.0
    use_fomo_gatekeeper: bool = True
    max_ret_5bar: float = 0.011
    max_ret_2bar: float = 0.010
    ma120_threshold: float = 4.77
    use_t2_momentum: bool = True
    t2_long_thresh: float = 0.008
    t2_short_thresh: float = -0.010

    def __post_init__(self) -> None:
        if not 1 <= self.quantity <= 10:
            raise ValueError("quantity must be in [1, 10]")


@dataclass(frozen=True)
class Ec2LunaTargets:
    targets: dict[datetime, int]
    diagnostics: dict[str, Any]


@dataclass
class _AggregateBar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    first_component: datetime

    def update(self, *, high: float, low: float, close: float, volume: int) -> None:
        self.high = max(self.high, high)
        self.low = min(self.low, low)
        self.close = close
        self.volume += volume

    def to_domain(self, symbol: str) -> Bar:
        return Bar(
            symbol=symbol,
            timestamp=self.start,
            open=Decimal(str(self.open)),
            high=Decimal(str(self.high)),
            low=Decimal(str(self.low)),
            close=Decimal(str(self.close)),
            volume=self.volume,
        )


def _is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in EC2_CLOSED_DAYS


def _next_trading_day(day: date) -> date:
    candidate = day + timedelta(days=1)
    for _ in range(14):
        if _is_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError(f"Cannot resolve next trading day after {day}")


def _session_index(day: date) -> int:
    cursor = day.replace(day=1)
    result = 0
    while cursor < day:
        if _is_trading_day(cursor):
            result += 1
        cursor += timedelta(days=1)
    return result


def _is_pre_holiday(day: date) -> bool:
    if not _is_trading_day(day):
        return False
    gap = (_next_trading_day(day) - day).days
    return gap > (3 if day.weekday() == 4 else 1)


def _core_long_reasons(day: date) -> tuple[str, ...]:
    if not _is_trading_day(day):
        return ()
    reasons: list[str] = []
    if day.weekday() in (1, 2):
        reasons.append("tue_wed")
    if _session_index(day) < 2:
        reasons.append("som2")
    if _is_pre_holiday(day):
        reasons.append("pre_holiday")
    return tuple(reasons)


def _is_regular_monday(day: date) -> bool:
    return (
        _is_trading_day(day)
        and day.weekday() == 0
        and _session_index(day) >= 2
        and not _is_pre_holiday(day)
    )


def _third_thursday(year: int, month: int) -> date:
    first_weekday, _ = calendar.monthrange(year, month)
    return date(year, month, 1 + (3 - first_weekday) % 7 + 14)


def _is_expiry_session(day: date) -> bool:
    return day == _third_thursday(day.year, day.month)


def _contract_expiry(symbol: str) -> date:
    match = _CONTRACT_RE.fullmatch(symbol)
    if match is None:
        raise ValueError(f"Unsupported VN30F contract: {symbol!r}")
    return _third_thursday(2000 + int(match.group("yy")), int(match.group("mm")))


def _is_post_expiry_friday(day: date) -> bool:
    return _is_trading_day(day) and day.weekday() == 4 and _is_expiry_session(
        day - timedelta(days=1)
    )


def _bucket_start(stamp: datetime) -> datetime:
    current = stamp.time()
    if current == time(11, 30):
        return stamp.replace(hour=11, minute=0, second=0, microsecond=0)
    minute = 30 if stamp.minute >= 30 else 0
    return stamp.replace(minute=minute, second=0, microsecond=0)


class _Ec2SignalReplay:
    def __init__(self, params: Ec2LunaReplayParameters) -> None:
        self.params = params
        self.t2 = T2MomentumEngine(
            fast_bars=20,
            slow_bars=50,
            macro_bars=120,
            macro_trend_bars=200,
            long_threshold=params.t2_long_thresh,
            short_threshold=params.t2_short_thresh,
        )
        self.completed_bars: list[Bar] = []
        self.aggregate: _AggregateBar | None = None
        self.aggregate_symbol: str | None = None
        self.current_day: date | None = None
        self.previous_session_close: float | None = None
        self._prior_day_close: float | None = None
        self.daily_open: float | None = None
        self.calendar_target = 0
        self.calendar_hard_flat = False
        self.calendar_reasons: tuple[str, ...] = ("startup",)
        self.effective_day: date | None = None
        self.blocked_execution_day: date | None = None
        self.desired_units = 0
        self.execution_units = 0
        self.reason_counts: Counter[str] = Counter()
        self.morning_days: set[date] = set()
        self.afternoon_days: set[date] = set()
        self.fomo_blocks = 0
        self.incomplete_gate_blocks = 0

    def _record(self, reasons: tuple[str, ...]) -> None:
        self.reason_counts.update(reasons)

    def _compose(self) -> None:
        if self.calendar_hard_flat:
            desired = 0
        elif self.calendar_target != 0:
            desired = self.calendar_target
        elif self.params.use_t2_momentum:
            desired = self.t2.state
        else:
            desired = 0
        self.desired_units = int(desired)

    def _finalize_aggregate(self) -> None:
        if self.aggregate is None or self.aggregate_symbol is None:
            return
        bar = self.aggregate.to_domain(self.aggregate_symbol)
        self.completed_bars.append(bar)
        if len(self.completed_bars) > 4000:
            self.completed_bars.pop(0)
        previous_state = self.t2.state
        self.t2.update(bar)
        if self.t2.last_reason and self.t2.state != previous_state:
            self.reason_counts[self.t2.last_reason] += 1
        self.aggregate = None
        self.aggregate_symbol = None
        self._compose()

    def _bootstrap_day(self, day: date) -> None:
        if self.effective_day == day or (
            self.effective_day is not None and self.effective_day > day
        ):
            self._compose()
            return
        reasons = _core_long_reasons(day)
        if self.blocked_execution_day == day:
            self.calendar_target = 0
            self.calendar_hard_flat = True
            self.calendar_reasons = ("gatekeeper_blocked_execution",)
        elif reasons and _is_post_expiry_friday(day):
            self.calendar_target = 0
            self.calendar_hard_flat = False
            self.calendar_reasons = ("post_expiry_friday_veto",)
        elif reasons:
            self.calendar_target = 1
            self.calendar_hard_flat = False
            self.calendar_reasons = reasons
        else:
            self.calendar_target = 0
            self.calendar_hard_flat = False
            self.calendar_reasons = ("calendar_flat",)
        self.effective_day = day
        self._record(self.calendar_reasons)
        self._compose()

    def begin_row(self, stamp: datetime, symbol: str, row_open: float) -> int:
        day_changed = self.current_day != stamp.date()
        bucket = _bucket_start(stamp)
        if self.aggregate is not None and self.aggregate.start != bucket:
            self._finalize_aggregate()

        if day_changed:
            self.current_day = stamp.date()
            self.daily_open = row_open
            self._bootstrap_day(stamp.date())
            # Any T+2 transition after 14:30 becomes executable on the first
            # quote of the next session, just like the EC2 reconciler.
            self.execution_units = self.desired_units
        elif stamp.time() < time(14, 30):
            self.execution_units = self.desired_units
        return self.execution_units * self.params.quantity

    def observe_row(
        self,
        *,
        stamp: datetime,
        symbol: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: int,
    ) -> None:
        bucket = _bucket_start(stamp)
        if self.aggregate is None:
            self.aggregate = _AggregateBar(
                start=bucket,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                first_component=stamp,
            )
            self.aggregate_symbol = symbol
        else:
            self.aggregate.update(high=high, low=low, close=close, volume=volume)

        self.previous_session_close = close
        if stamp.time() == time(9, 15):
            self._morning_decision(stamp.date())
            self.execution_units = self.desired_units
        elif stamp.time() == time(14, 20):
            self._afternoon_decision(stamp.date(), symbol)
            self.execution_units = self.desired_units

    def _morning_decision(self, today: date) -> None:
        if today in self.morning_days:
            return
        self.morning_days.add(today)
        if self.calendar_hard_flat or self.calendar_target != 0:
            return
        if _is_regular_monday(today):
            if (
                self.previous_session_close is None
                or self.daily_open is None
                or self.previous_session_close <= 0
            ):
                self.calendar_reasons = ("monday_missing_gap",)
            else:
                # previous_session_close currently contains the latest 09:15
                # close, so use the last completed daily close retained below.
                previous = self._prior_day_close
                if previous is None or previous <= 0:
                    self.calendar_reasons = ("monday_missing_gap",)
                else:
                    gap = (self.daily_open - previous) / previous
                    if gap <= self.params.monday_max_gap_pct:
                        self.calendar_target = -1
                        self.calendar_reasons = ("monday_short",)
                    else:
                        self.calendar_reasons = ("monday_flat_gap",)
        elif _is_expiry_session(today):
            self.calendar_target = 1
            self.calendar_reasons = ("expiry_thursday",)
        else:
            self.calendar_reasons = ("calendar_flat",)
        self._record(self.calendar_reasons)
        self._compose()

    def close_day(self, close: float) -> None:
        self._prior_day_close = close

    def _gate_metrics(self) -> tuple[bool, bool]:
        if self.aggregate is None or self.aggregate_symbol is None:
            return False, False
        candidate = self.aggregate.to_domain(self.aggregate_symbol)
        bars = [*self.completed_bars, candidate]
        if len(bars) < 120:
            return False, False
        closes = [float(bar.close) for bar in bars]
        sma = sum(closes[-120:]) / 120
        ranges: list[float] = []
        start = len(bars) - 20
        for index in range(start, len(bars)):
            bar = bars[index]
            high = float(bar.high)
            low = float(bar.low)
            values = [high - low]
            if index > 0:
                previous = float(bars[index - 1].close)
                values.extend((abs(high - previous), abs(low - previous)))
            ranges.append(max(values))
        atr = sum(ranges) / 20
        close = closes[-1]
        distance = (close - sma) / (atr + 1e-6)
        ret_2bar = math.log(close / closes[-3]) if closes[-3] > 0 else None
        ret_5bar = math.log(close / closes[-6]) if closes[-6] > 0 else None
        is_fomo = (
            ret_5bar is not None and ret_5bar > self.params.max_ret_5bar
            if distance <= self.params.ma120_threshold
            else ret_2bar is not None and ret_2bar > self.params.max_ret_2bar
        )
        complete = self.aggregate.first_component.time() == time(14, 0)
        return complete, bool(is_fomo)

    def _afternoon_decision(self, today: date, symbol: str) -> None:
        if today in self.afternoon_days:
            return
        self.afternoon_days.add(today)
        signal_day = _next_trading_day(today)
        self.effective_day = signal_day
        if today == _contract_expiry(symbol):
            self.calendar_target = 0
            self.calendar_hard_flat = True
            self.calendar_reasons = ("expiry_flatten",)
        else:
            reasons = _core_long_reasons(signal_day)
            if reasons and _is_post_expiry_friday(signal_day):
                self.calendar_target = 0
                self.calendar_hard_flat = False
                self.calendar_reasons = ("post_expiry_friday_veto",)
            else:
                self.calendar_target = 1 if reasons else 0
                self.calendar_hard_flat = False
                self.calendar_reasons = reasons or ("calendar_flat_next_session",)
            if self.calendar_target == 1 and self.params.use_fomo_gatekeeper:
                complete, is_fomo = self._gate_metrics()
                if not complete:
                    self.calendar_target = 0
                    self.calendar_hard_flat = True
                    self.calendar_reasons = ("gatekeeper_incomplete_1400_bar",)
                    self.incomplete_gate_blocks += 1
                elif is_fomo:
                    self.calendar_target = 0
                    self.calendar_hard_flat = True
                    self.calendar_reasons = ("gatekeeper_fomo_blocked",)
                    self.fomo_blocks += 1
            if self.calendar_hard_flat:
                self.blocked_execution_day = signal_day
            elif self.blocked_execution_day == signal_day:
                self.blocked_execution_day = None
        self._record(self.calendar_reasons)
        self._compose()


def generate_luna_ec2_targets(
    futures_5m: pd.DataFrame,
    params: Ec2LunaReplayParameters | None = None,
) -> Ec2LunaTargets:
    """Generate quantity-scaled targets for every observed five-minute row."""

    params = params or Ec2LunaReplayParameters()
    frame = futures_5m.copy()
    frame.columns = [str(column).capitalize() for column in frame.columns]
    required = {"Datetime", "Open", "High", "Low", "Close", "Volume", "Contract"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Futures frame is missing columns: {missing}")
    frame["Datetime"] = pd.to_datetime(frame["Datetime"])
    frame = frame.sort_values("Datetime").reset_index(drop=True)
    replay = _Ec2SignalReplay(params)
    targets: dict[datetime, int] = {}

    rows = list(frame.itertuples(index=False))
    for index, row in enumerate(rows):
        stamp = row.Datetime.to_pydatetime()
        target = replay.begin_row(stamp, str(row.Contract), float(row.Open))
        targets[stamp] = target
        replay.observe_row(
            stamp=stamp,
            symbol=str(row.Contract),
            open_price=float(row.Open),
            high=float(row.High),
            low=float(row.Low),
            close=float(row.Close),
            volume=max(int(row.Volume or 0), 0),
        )
        next_day = index + 1 == len(rows) or rows[index + 1].Datetime.date() != stamp.date()
        if next_day:
            replay.close_day(float(row.Close))

    replay._finalize_aggregate()
    counts = Counter(targets.values())
    observed_days = frame["Datetime"].dt.date.nunique()
    diagnostics = {
        "observed_rows": len(frame),
        "observed_days": int(observed_days),
        "target_rows": {str(key): value for key, value in sorted(counts.items())},
        "reason_counts": dict(sorted(replay.reason_counts.items())),
        "fomo_blocks": replay.fomo_blocks,
        "incomplete_gate_blocks": replay.incomplete_gate_blocks,
        "morning_decision_days": len(replay.morning_days),
        "afternoon_decision_days": len(replay.afternoon_days),
        "timing_approximation": {
            "morning": "09:20 using the completed 09:15-09:20 bar",
            "afternoon": "14:25 using data observed through the 14:20-14:25 bar",
        },
    }
    return Ec2LunaTargets(targets=targets, diagnostics=diagnostics)

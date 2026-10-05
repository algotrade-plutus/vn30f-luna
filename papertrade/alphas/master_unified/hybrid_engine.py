"""Dependency-free signal engine matching the research HybridGatedAlpha.

The engine owns only completed 30-minute OHLC bars and the path-dependent
T+2 state.  Calendar scheduling and live order execution stay outside this
module so this code can be parity-tested without PaperBroker or credentials.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Deque, Iterable, Optional
from luna_core.momentum import advance_t2
from luna_core.gates import fomo_pump


@dataclass(frozen=True)
class Bar30m:
    datetime: str
    open: float
    high: float
    low: float
    close: float

    @classmethod
    def from_mapping(cls, item: dict[str, Any]) -> "Bar30m":
        close = float(item["close"])
        return cls(
            datetime=str(item.get("datetime", "")),
            open=float(item.get("open", close)),
            high=float(item.get("high", close)),
            low=float(item.get("low", close)),
            close=close,
        )


@dataclass(frozen=True)
class HybridParameters:
    max_ret_5bar: float = 0.011
    max_ret_2bar: float = 0.010
    ma120_threshold: float = 4.77
    gate_ma_window: int = 120
    gate_atr_window: int = 20
    t2_fast_bars: int = 20
    t2_slow_bars: int = 50
    t2_macro_bars: int = 120
    t2_macro_trend_bars: int = 200
    t2_long_thresh: float = 0.008
    t2_short_thresh: float = -0.010


class HybridSignalEngine:
    """Rolling indicators plus the exact research T+2 state machine."""

    def __init__(
        self,
        params: Optional[HybridParameters] = None,
        *,
        max_history: int = 4000,
    ) -> None:
        self.params = params or HybridParameters()
        minimum = max(
            self.params.gate_ma_window,
            self.params.gate_atr_window,
            self.params.t2_macro_trend_bars + 1,
        )
        if max_history < minimum:
            raise ValueError(f"max_history must be at least {minimum}")
        self._bars: Deque[Bar30m] = deque(maxlen=max_history)
        self.t2_state = 0
        self.last_t2_bar: Optional[str] = None
        self.last_t2_reason: tuple[str, ...] = ()

    @property
    def bar_count(self) -> int:
        return len(self._bars)

    @property
    def latest_bar(self) -> Optional[Bar30m]:
        return self._bars[-1] if self._bars else None

    @property
    def bars(self) -> tuple[Bar30m, ...]:
        return tuple(self._bars)

    def load(
        self,
        records: Iterable[dict[str, Any] | Bar30m],
        *,
        persisted_t2_state: Optional[int] = None,
        persisted_last_t2_bar: Optional[str] = None,
    ) -> int:
        """Load ordered history and replay only bars newer than saved state."""
        parsed = [
            item if isinstance(item, Bar30m) else Bar30m.from_mapping(item)
            for item in records
        ]
        parsed.sort(key=lambda bar: bar.datetime)
        unique: dict[str, Bar30m] = {bar.datetime: bar for bar in parsed}

        if persisted_t2_state in (-1, 0, 1) and persisted_last_t2_bar:
            self.t2_state = int(persisted_t2_state)
            self.last_t2_bar = str(persisted_last_t2_bar)

        for bar in unique.values():
            self._bars.append(bar)
            if self.last_t2_bar is None or bar.datetime > self.last_t2_bar:
                self._advance_t2_for_latest()
        return len(unique)

    def load_file(
        self,
        path: Path,
        *,
        persisted_t2_state: Optional[int] = None,
        persisted_last_t2_bar: Optional[str] = None,
    ) -> int:
        if not path.exists():
            return 0
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Warmup file must contain a list: {path}")
        return self.load(
            payload,
            persisted_t2_state=persisted_t2_state,
            persisted_last_t2_bar=persisted_last_t2_bar,
        )

    def save_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps([asdict(bar) for bar in self._bars], indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def add_completed_bar(self, bar: Bar30m) -> bool:
        """Append one new bar and advance T+2 exactly once."""
        latest = self.latest_bar
        if latest is not None and bar.datetime <= latest.datetime:
            return False
        self._bars.append(bar)
        self._advance_t2_for_latest()
        return True

    def metrics(self, candidate: Optional[Bar30m] = None) -> dict[str, Any]:
        bars = list(self._bars)
        if candidate is not None:
            if bars and candidate.datetime == bars[-1].datetime:
                bars[-1] = candidate
            elif not bars or candidate.datetime > bars[-1].datetime:
                bars.append(candidate)
        if not bars:
            return self._empty_metrics()

        p = self.params
        closes = [bar.close for bar in bars]
        close = closes[-1]
        ret_fast = self._pct_change(closes, p.t2_fast_bars)
        ret_slow = self._pct_change(closes, p.t2_slow_bars)
        ret_macro = self._pct_change(closes, p.t2_macro_trend_bars)
        ret_2bar = self._log_change(closes, 2)
        ret_5bar = self._log_change(closes, 5)
        sma = (
            sum(closes[-p.t2_macro_bars :]) / p.t2_macro_bars
            if len(closes) >= p.t2_macro_bars
            else None
        )
        gate_ma = (
            sum(closes[-p.gate_ma_window :]) / p.gate_ma_window
            if len(closes) >= p.gate_ma_window
            else None
        )
        atr = self._atr(bars, p.gate_atr_window)
        dist_ma = (
            (close - gate_ma) / (atr + 1e-6)
            if gate_ma is not None and atr is not None
            else None
        )
        gate_ready = atr is not None and gate_ma is not None
        is_fomo = False
        if gate_ready:
            is_fomo = fomo_pump(
                dist_ma, ret_2bar, ret_5bar, distance_threshold=p.ma120_threshold,
                max_ret_2bar=p.max_ret_2bar, max_ret_5bar=p.max_ret_5bar,
            )

        return {
            "ready": sma is not None and ret_fast is not None and ret_slow is not None,
            "gate_ready": gate_ready,
            "close": close,
            "ret_2d": ret_fast,
            "ret_5d": ret_slow,
            "ret_20d": ret_macro,
            "sma120": sma,
            "atr20": atr,
            "dist_ma120": dist_ma,
            "ret_2bar": ret_2bar,
            "ret_5bar": ret_5bar,
            "is_fomo": bool(is_fomo),
        }

    def previous_session_close(self, day: date) -> Optional[float]:
        for bar in reversed(self._bars):
            try:
                bar_day = datetime.fromisoformat(bar.datetime).date()
            except ValueError:
                continue
            if bar_day < day:
                return bar.close
        return None

    def bar_at(self, day: date, hour: int, minute: int) -> Optional[Bar30m]:
        for bar in reversed(self._bars):
            try:
                stamp = datetime.fromisoformat(bar.datetime)
            except ValueError:
                continue
            if stamp.date() == day and stamp.hour == hour and stamp.minute == minute:
                return bar
            if stamp.date() < day:
                break
        return None

    def _advance_t2_for_latest(self) -> None:
        latest = self.latest_bar
        if latest is None:
            return
        metrics = self.metrics()
        self.t2_state, reason = advance_t2(
            self.t2_state, fast=metrics["ret_2d"], slow=metrics["ret_5d"],
            macro=metrics["ret_20d"], close=metrics["close"], average=metrics["sma120"],
            long_threshold=self.params.t2_long_thresh,
            short_threshold=self.params.t2_short_thresh,
        )
        self.last_t2_bar = latest.datetime
        self.last_t2_reason = reason

    @staticmethod
    def _pct_change(closes: list[float], lookback: int) -> Optional[float]:
        if len(closes) <= lookback or closes[-(lookback + 1)] == 0:
            return None
        return closes[-1] / closes[-(lookback + 1)] - 1.0

    @staticmethod
    def _log_change(closes: list[float], lookback: int) -> Optional[float]:
        if len(closes) <= lookback:
            return None
        current = closes[-1]
        previous = closes[-(lookback + 1)]
        if current <= 0 or previous <= 0:
            return None
        return math.log(current / previous)

    @staticmethod
    def _atr(bars: list[Bar30m], window: int) -> Optional[float]:
        if len(bars) < window:
            return None
        start = len(bars) - window
        ranges: list[float] = []
        for index in range(start, len(bars)):
            bar = bars[index]
            values = [bar.high - bar.low]
            if index > 0:
                previous_close = bars[index - 1].close
                values.extend(
                    [abs(bar.high - previous_close), abs(bar.low - previous_close)]
                )
            ranges.append(max(values))
        return sum(ranges) / window

    @staticmethod
    def _empty_metrics() -> dict[str, Any]:
        return {
            "ready": False,
            "gate_ready": False,
            "close": None,
            "ret_2d": None,
            "ret_5d": None,
            "ret_20d": None,
            "sma120": None,
            "atr20": None,
            "dist_ma120": None,
            "ret_2bar": None,
            "ret_5bar": None,
            "is_fomo": False,
        }

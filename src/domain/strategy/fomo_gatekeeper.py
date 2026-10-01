"""Domain Strategy: FOMO Pump Detector / Gatekeeper.
Pure Python standard library only (no pandas, no numpy).
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal
import math

from ..entities.bar import Bar


class FomoGatekeeper:
    """Overbought rally / FOMO pump detector.

    Prevents buying into overheated market tops by computing:
    1. Distance from SMA120 normalized by ATR20.
    2. 2-bar and 5-bar logarithmic price returns.
    """

    def __init__(
        self,
        *,
        atr_window: int = 20,
        sma_window: int = 120,
        distance_threshold: float = 4.77,
        max_ret_2bar: float = 0.010,
        max_ret_5bar: float = 0.011,
    ) -> None:
        self.atr_window = atr_window
        self.sma_window = sma_window
        self.distance_threshold = distance_threshold
        self.max_ret_2bar = max_ret_2bar
        self.max_ret_5bar = max_ret_5bar

        self._closes: deque[float] = deque(maxlen=max(sma_window, 6) + 1)
        self._true_ranges: deque[float] = deque(maxlen=atr_window)
        self._prev_close: float | None = None

    def update(self, bar: Bar) -> bool:
        """Add bar and check if FOMO pump condition is triggered.
        Returns True if market is in FOMO condition (buy veto active).
        """
        c = float(bar.close)
        h = float(bar.high)
        l = float(bar.low)

        # 1. Compute True Range
        if self._prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))
        self._prev_close = c
        self._true_ranges.append(tr)
        self._closes.append(c)

        # 2. Check if we have enough warmup for evaluation
        warmup = max(self.sma_window, self.atr_window, 6)
        if len(self._closes) < warmup:
            return False

        # ATR20
        atr = sum(self._true_ranges) / len(self._true_ranges) if self._true_ranges else 1.0

        # SMA120
        sma_len = min(len(self._closes), self.sma_window)
        recent_for_sma = list(self._closes)[-sma_len:]
        sma120 = sum(recent_for_sma) / sma_len

        # Normalized distance from SMA
        dist_ma = (c - sma120) / (atr + 1e-6)

        # Returns
        p_prev2 = self._closes[-3]
        ret_2bar = math.log(c / p_prev2) if p_prev2 > 0 else 0.0

        ret_5bar: float | None = None
        if len(self._closes) >= 6:
            p_prev5 = self._closes[-6]
            ret_5bar = math.log(c / p_prev5) if p_prev5 > 0 else 0.0

        # Predicate
        return fomo_predicate(
            distance=dist_ma,
            ret_2bar=ret_2bar,
            ret_5bar=ret_5bar,
            distance_threshold=self.distance_threshold,
            max_ret_2bar=self.max_ret_2bar,
            max_ret_5bar=self.max_ret_5bar,
        )


def fomo_predicate(
    distance: float,
    ret_2bar: float | None,
    ret_5bar: float | None,
    *,
    distance_threshold: float = 4.77,
    max_ret_2bar: float = 0.010,
    max_ret_5bar: float = 0.011,
) -> bool:
    """Core FOMO pump boolean predicate."""
    if distance <= distance_threshold:
        return ret_5bar is not None and ret_5bar > max_ret_5bar
    return ret_2bar is not None and ret_2bar > max_ret_2bar

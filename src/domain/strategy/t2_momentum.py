"""Domain Strategy: T+2 Institutional Momentum Engine.
Pure Python standard library only (no pandas, no numpy).
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal

from ..entities.bar import Bar


class T2MomentumEngine:
    """T+2 Institutional Momentum state machine.
    
    Tracks multi-timeframe price returns and macro trend moving averages.
    Returns target position: 1 (Long), -1 (Short), or 0 (Flat).
    """

    def __init__(
        self,
        *,
        fast_bars: int = 20,
        slow_bars: int = 50,
        macro_bars: int = 120,
        macro_trend_bars: int = 200,
        long_threshold: float = 0.008,
        short_threshold: float = -0.010,
    ) -> None:
        self.fast_bars = fast_bars
        self.slow_bars = slow_bars
        self.macro_bars = macro_bars
        self.macro_trend_bars = macro_trend_bars
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold

        maxlen = max(fast_bars, slow_bars, macro_bars, macro_trend_bars) + 1
        self._closes: deque[float] = deque(maxlen=maxlen)
        self.state: int = 0
        self.last_reason: str = ""

    def update(self, bar: Bar) -> int:
        """Process incoming 30m bar and transition state machine."""
        c = float(bar.close)
        self._closes.append(c)

        if len(self._closes) <= self.macro_bars:
            return self.state

        # Compute SMA Macro
        sma_slice = list(self._closes)[-self.macro_bars:]
        sma_macro = sum(sma_slice) / len(sma_slice)

        # Compute Momentum returns
        rf = (c / self._closes[-self.fast_bars - 1] - 1.0) if len(self._closes) > self.fast_bars else None
        rs = (c / self._closes[-self.slow_bars - 1] - 1.0) if len(self._closes) > self.slow_bars else None
        rm = (c / self._closes[-self.macro_trend_bars - 1] - 1.0) if len(self._closes) > self.macro_trend_bars else None

        new_state, reason = advance_t2_state(
            self.state,
            fast=rf,
            slow=rs,
            macro=rm,
            close=c,
            average=sma_macro,
            long_threshold=self.long_threshold,
            short_threshold=self.short_threshold,
        )
        self.state = new_state
        if reason:
            self.last_reason = reason
        return self.state


def advance_t2_state(
    state: int,
    *,
    fast: float | None,
    slow: float | None,
    macro: float | None,
    close: float,
    average: float | None,
    long_threshold: float = 0.008,
    short_threshold: float = -0.010,
) -> tuple[int, str]:
    """Pure functional T+2 state machine transition."""
    if average is None:
        return state, ""
    if state == 0:
        if fast is not None and slow is not None:
            if fast > long_threshold and slow > 0 and close > average:
                return 1, "t2_momentum_long_entry"
            if fast < short_threshold and slow < 0 and close < average and macro is not None and macro < 0:
                return -1, "t2_momentum_short_entry"
        return 0, ""
    elif state == 1:
        if fast is not None and fast < 0:
            return 0, "t2_long_momentum_exhausted"
        return 1, "t2_hold_long"
    elif state == -1:
        if fast is not None and fast > 0:
            return 0, "t2_short_momentum_exhausted"
        return -1, "t2_hold_short"
    return state, ""

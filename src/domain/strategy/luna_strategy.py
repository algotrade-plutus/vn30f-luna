"""Domain Strategy: Luna Alpha Composite Strategy.
Pure Python standard library only (no pandas, no numpy).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from ..entities.bar import Bar
from .calendar_rules import (
    is_calendar_long_day,
    is_regular_monday,
    next_trading_day,
)
from .fomo_gatekeeper import FomoGatekeeper
from .t2_momentum import T2MomentumEngine


@dataclass
class LunaParameters:
    """Strategy hyperparameters for Luna Alpha."""
    use_som2: bool = True
    use_preholiday: bool = True
    use_tue_wed: bool = True
    use_monday_short: bool = True
    monday_max_gap: float = 0.0
    use_fomo_gatekeeper: bool = True
    fomo_max_ret_5bar: float = 0.011
    fomo_max_ret_2bar: float = 0.010
    use_t2_momentum: bool = True
    t2_fast_bars: int = 20
    t2_slow_bars: int = 50
    t2_macro_bars: int = 120
    t2_macro_trend_bars: int = 200
    t2_long_thresh: float = 0.008
    t2_short_thresh: float = -0.010
    session_end_time: time = time(14, 30)


class LunaStrategy:
    """Unified Pure-Domain Luna Alpha Strategy.

    Generates target position in {-1, 0, 1} for each bar:
    - Trụ cột 1: Calendar Anomalies (SOM2, Tue/Wed, Pre-holiday, Monday Short).
    - Bộ lọc: FOMO Gatekeeper Veto against buying overheated tops.
    - Trụ cột 2: T+2 Institutional Momentum Engine when Calendar is neutral (0).
    """

    def __init__(self, params: LunaParameters | None = None) -> None:
        self.params = params or LunaParameters()
        self._build_indicators()
        self.blocked_execution_dates: set[date] = set()
        self.prev_day_close: float | None = None
        self.daily_open_map: dict[date, float] = {}

    def _build_indicators(self) -> None:
        self.fomo_gate = FomoGatekeeper(
            max_ret_5bar=self.params.fomo_max_ret_5bar,
            max_ret_2bar=self.params.fomo_max_ret_2bar,
        )
        self.t2_engine = T2MomentumEngine(
            fast_bars=self.params.t2_fast_bars,
            slow_bars=self.params.t2_slow_bars,
            macro_bars=self.params.t2_macro_bars,
            macro_trend_bars=self.params.t2_macro_trend_bars,
            long_threshold=self.params.t2_long_thresh,
            short_threshold=self.params.t2_short_thresh,
        )

    def reset_market_history(self) -> None:
        """Reset price indicators when the tradable futures contract changes.

        Returns across two different expiries are not an economic return.  The
        frozen dataset does not contain enough overlap to back-adjust a roll,
        so failing closed means warming the FOMO and momentum indicators again
        while retaining calendar state.
        """

        self._build_indicators()

    def on_bar(self, bar: Bar) -> tuple[int, str]:
        """Evaluate incoming bar and return (target_position, reason)."""
        bar_dt = bar.timestamp
        current_date = bar_dt.date()
        bar_time = bar_dt.time()
        close_f = float(bar.close)
        open_f = float(bar.open)

        if current_date not in self.daily_open_map:
            self.daily_open_map[current_date] = open_f

        # 1. Update Sub-engines
        is_fomo = self.fomo_gate.update(bar)
        t2_state = self.t2_engine.update(bar) if self.params.use_t2_momentum else 0

        # Check for Session End (14:30) to evaluate FOMO veto on tomorrow's Long
        is_at_session_end = bar_time >= self.params.session_end_time
        if is_at_session_end and self.params.use_fomo_gatekeeper:
            tomorrow = next_trading_day(current_date)
            tomorrow_is_long = is_calendar_long_day(
                tomorrow,
                use_som2=self.params.use_som2,
                use_preholiday=self.params.use_preholiday,
                use_tue_wed=self.params.use_tue_wed,
            )
            if tomorrow_is_long and is_fomo:
                self.blocked_execution_dates.add(tomorrow)

        # 2. Evaluate Calendar signals
        calendar_target = 0
        calendar_reason = ""

        # Check Calendar Long (SOM2, Pre-holiday, Tue/Wed)
        today_calendar_long = is_calendar_long_day(
            current_date,
            use_som2=self.params.use_som2,
            use_preholiday=self.params.use_preholiday,
            use_tue_wed=self.params.use_tue_wed,
        )

        if today_calendar_long:
            if current_date in self.blocked_execution_dates:
                # A veto must fail closed. Falling through to T+2 here could
                # immediately reopen the exact long exposure FOMO blocked.
                return 0, "calendar_long_blocked_by_fomo"
            else:
                calendar_target = 1
                calendar_reason = "calendar_long_active"

        # Check Monday Short
        elif self.params.use_monday_short and is_regular_monday(current_date):
            if not is_at_session_end:
                # Gap check
                gap_ok = True
                if self.prev_day_close is not None and self.params.monday_max_gap is not None:
                    first_open = self.daily_open_map.get(current_date, open_f)
                    gap = first_open - self.prev_day_close
                    gap_ok = gap <= self.params.monday_max_gap

                if gap_ok:
                    calendar_target = -1
                    calendar_reason = "monday_short_active"

        # Track previous day close for gap calculations
        if is_at_session_end:
            self.prev_day_close = close_f

        # 3. Composite Priority
        if calendar_target != 0:
            return calendar_target, calendar_reason

        # Fallback to T+2 momentum if calendar is neutral (0)
        if self.params.use_t2_momentum and t2_state != 0:
            return t2_state, self.t2_engine.last_reason

        return 0, "neutral_flat"

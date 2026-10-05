"""Pure decision composer combining Calendar and Hybrid (T+2 + FOMO) rules.

Separates signal evaluation from execution and network logic so decisions can be
audited and tested without broker dependencies.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time as clock_time
from typing import Any, Callable, Dict, Optional, Tuple
from luna_core.policy import base_target

from .bar_aggregator import BarAggregator
from .hybrid_engine import Bar30m, HybridSignalEngine
from .schedule import (
    HCM_TZ,
    contract_expiry,
    core_long_reasons,
    is_expiry_session,
    is_post_expiry_friday,
    is_post_expiry_monday,
    is_regular_monday,
    next_trading_day,
)

LOGGER = logging.getLogger(__name__)


def _as_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


class SignalComposer:
    """Evaluate target position units and reasoning for the Hybrid alpha."""

    def __init__(
        self,
        *,
        signal_engine: HybridSignalEngine,
        long_dows: Tuple[int, ...] = (1, 2),
        use_month_start: bool = True,
        use_preholiday: bool = True,
        use_monday_short: bool = True,
        use_post_expiry_monday_short: bool = True,
        post_exp_monday_min_basis_bps: float = -15.0,
        use_post_expiry_friday_veto: bool = True,
        use_december_rally: bool = True,
        use_expiry_thursday: bool = True,
        monday_max_gap_pct: float = 0.0,
        use_monday_opening_move_veto: bool = True,
        monday_max_opening_move_pts: float = 1.5,
        use_fomo_gatekeeper: bool = True,
        use_t2_momentum: bool = True,
    ) -> None:
        self.signal_engine = signal_engine

        self.long_dows = long_dows
        self.use_month_start = use_month_start
        self.use_preholiday = use_preholiday
        self.use_monday_short = use_monday_short
        self.use_post_expiry_monday_short = use_post_expiry_monday_short
        self.post_exp_monday_min_basis_bps = post_exp_monday_min_basis_bps
        self.use_post_expiry_friday_veto = use_post_expiry_friday_veto
        self.use_december_rally = use_december_rally
        self.use_expiry_thursday = use_expiry_thursday
        self.monday_max_gap_pct = monday_max_gap_pct
        self.use_monday_opening_move_veto = use_monday_opening_move_veto
        self.monday_max_opening_move_pts = monday_max_opening_move_pts
        self.use_fomo_gatekeeper = use_fomo_gatekeeper
        self.use_t2_momentum = use_t2_momentum

        # Internal state
        self.calendar_target: int = 0
        self.calendar_hard_flat: bool = False
        self.calendar_reasons: Tuple[str, ...] = ("startup",)
        self.effective_day: Optional[date] = None
        self.blocked_execution_day: Optional[date] = None
        self.last_morning_decision_day: Optional[date] = None
        self.last_afternoon_decision_day: Optional[date] = None
        self.desired_units: int = 0
        self.reasons: Tuple[str, ...] = ("startup",)

    def load_state(self, saved: Dict[str, Any], symbol: str) -> None:
        """Load persisted runtime state."""
        if not isinstance(saved, dict) or saved.get("symbol") not in (None, symbol):
            saved = {}
        self.calendar_target = int(saved.get("calendar_target", 0))
        self.calendar_hard_flat = bool(saved.get("calendar_hard_flat", False))
        self.calendar_reasons = tuple(saved.get("calendar_reasons", ("startup",)))
        self.effective_day = _as_date(saved.get("effective_day"))
        self.blocked_execution_day = _as_date(saved.get("blocked_execution_day"))
        self.last_morning_decision_day = _as_date(saved.get("last_morning_decision_day"))
        self.last_afternoon_decision_day = _as_date(saved.get("last_afternoon_decision_day"))

    def dump_state(self, symbol: str) -> Dict[str, Any]:
        """Serialize state for persistence."""
        return {
            "schema_version": 1,
            "symbol": symbol,
            "calendar_target": self.calendar_target,
            "calendar_hard_flat": self.calendar_hard_flat,
            "calendar_reasons": list(self.calendar_reasons),
            "effective_day": self.effective_day.isoformat() if self.effective_day else None,
            "blocked_execution_day": (
                self.blocked_execution_day.isoformat() if self.blocked_execution_day else None
            ),
            "last_morning_decision_day": (
                self.last_morning_decision_day.isoformat() if self.last_morning_decision_day else None
            ),
            "last_afternoon_decision_day": (
                self.last_afternoon_decision_day.isoformat() if self.last_afternoon_decision_day else None
            ),
            "t2_state": self.signal_engine.t2_state,
            "last_t2_bar": self.signal_engine.last_t2_bar,
            "desired_units": self.desired_units,
        }

    def monday_gap(
        self,
        day: date,
        ref_price: Optional[float],
        bar_open: Optional[float],
        quote_open: Optional[float] = None,
    ) -> Optional[float]:
        previous_close = self.signal_engine.previous_session_close(day)
        if previous_close is None and ref_price is not None:
            previous_close = ref_price
        open_price = bar_open
        if quote_open is not None:
            open_price = float(quote_open)
        if previous_close is None or open_price is None or float(previous_close) <= 0:
            return None
        return (float(open_price) - float(previous_close)) / float(previous_close)

    def bootstrap_calendar_day(
        self,
        local_now: datetime,
        ref_price: Optional[float],
        bar_open: Optional[float],
        quote_open: Optional[float] = None,
        live_basis_fn: Optional[Callable[[], Optional[float]]] = None,
        spot_price: Optional[float] = None,
        current_price: Optional[float] = None,
    ) -> None:
        today = local_now.date()
        if self.effective_day == today:
            return
        if self.effective_day is not None and self.effective_day > today:
            return

        core_reasons = core_long_reasons(
            today,
            long_dows=self.long_dows,
            use_month_start=self.use_month_start,
            use_preholiday=self.use_preholiday,
        )
        blocked = self.blocked_execution_day == today
        if blocked:
            self.calendar_target = 0
            self.calendar_hard_flat = True
            self.calendar_reasons = ("gatekeeper_blocked_execution",)
        else:
            if core_reasons and self.use_post_expiry_friday_veto and is_post_expiry_friday(today):
                self.calendar_target = 0
                self.calendar_hard_flat = False
                self.calendar_reasons = ("post_expiry_friday_veto",)
            elif core_reasons:
                if self.use_december_rally and today.month == 12:
                    metrics = self.signal_engine.metrics()
                    if metrics.get("sma120") is not None and metrics.get("close") is not None:
                        if metrics["close"] > metrics["sma120"]:
                            core_reasons = core_reasons + ("december_rally",)
                self.calendar_target = 1
                self.calendar_hard_flat = False
                self.calendar_reasons = core_reasons
            else:
                self.calendar_target = 0
                self.calendar_hard_flat = False
                self.calendar_reasons = ("calendar_flat",)
        self.effective_day = today

        if local_now.time() >= clock_time(9, 16):
            self.apply_morning_decision(
                local_now,
                ref_price=ref_price,
                bar_open=bar_open,
                quote_open=quote_open,
                live_basis_fn=live_basis_fn,
                spot_price=spot_price,
                current_price=current_price,
            )

    def apply_morning_decision(
        self,
        local_now: datetime,
        ref_price: Optional[float],
        bar_open: Optional[float],
        quote_open: Optional[float] = None,
        live_basis_fn: Optional[Callable[[], Optional[float]]] = None,
        spot_price: Optional[float] = None,
        current_price: Optional[float] = None,
    ) -> None:
        today = local_now.date()
        if self.last_morning_decision_day == today:
            return
        if self.calendar_hard_flat or self.calendar_target != 0:
            self.last_morning_decision_day = today
            return

        if self.use_monday_short and is_regular_monday(today):
            gap = self.monday_gap(today, ref_price, bar_open, quote_open)
            if gap is None:
                self.calendar_reasons = ("monday_missing_gap",)
                return
            if gap > self.monday_max_gap_pct:
                self.calendar_reasons = ("monday_flat_gap",)
                return

            if self.use_monday_opening_move_veto and current_price is not None:
                effective_open = bar_open if bar_open is not None else quote_open
                if effective_open is not None:
                    opening_move = current_price - effective_open
                    if opening_move > self.monday_max_opening_move_pts:
                        self.calendar_reasons = ("monday_flat_opening_surge",)
                        return

            self.calendar_target = -1
            self.calendar_reasons = ("monday_short",)
        elif self.use_post_expiry_monday_short and is_post_expiry_monday(today):
            if live_basis_fn is not None:
                basis = live_basis_fn()
                basis_bps = (basis / spot_price * 10000.0) if (basis is not None and spot_price) else None
                if basis_bps is None:
                    self.calendar_reasons = ("post_expiry_monday_missing_basis",)
                    return
                if basis_bps >= self.post_exp_monday_min_basis_bps:
                    self.calendar_target = -1
                    self.calendar_reasons = ("post_expiry_monday_short",)
                else:
                    self.calendar_reasons = ("post_expiry_monday_flat",)
            else:
                self.calendar_reasons = ("post_expiry_monday_missing_basis",)
        elif self.use_expiry_thursday and is_expiry_session(today):
            self.calendar_target = 1
            self.calendar_reasons = ("expiry_thursday",)
        else:
            self.calendar_reasons = ("calendar_flat",)
        self.last_morning_decision_day = today

    def gate_candidate(
        self, local_now: datetime, aggregator: BarAggregator
    ) -> Tuple[Optional[Bar30m], bool]:
        expected = local_now.replace(hour=14, minute=0, second=0, microsecond=0)
        snapshot = aggregator.current_bar_snapshot()
        if snapshot is not None and aggregator.current_bar_start == expected:
            first = aggregator.current_bar_first_quote
            complete = first is not None and (first - expected).total_seconds() <= 120
            return snapshot, complete
        historical = self.signal_engine.bar_at(local_now.date(), 14, 0)
        return historical, historical is not None

    def apply_afternoon_decision(
        self, local_now: datetime, aggregator: BarAggregator, symbol: str
    ) -> None:
        today = local_now.date()
        if self.last_afternoon_decision_day == today:
            return
        signal_day = next_trading_day(today)
        self.effective_day = signal_day

        if today == contract_expiry(symbol):
            self.calendar_target = 0
            self.calendar_hard_flat = True
            self.calendar_reasons = ("expiry_flatten",)
        else:
            reasons = core_long_reasons(
                signal_day,
                long_dows=self.long_dows,
                use_month_start=self.use_month_start,
                use_preholiday=self.use_preholiday,
            )
            if reasons and self.use_post_expiry_friday_veto and is_post_expiry_friday(signal_day):
                self.calendar_target = 0
                self.calendar_hard_flat = False
                self.calendar_reasons = ("post_expiry_friday_veto",)
            else:
                if reasons and self.use_december_rally and signal_day.month == 12:
                    metrics = self.signal_engine.metrics()
                    if metrics.get("sma120") is not None and metrics.get("close") is not None:
                        if metrics["close"] > metrics["sma120"]:
                            reasons = reasons + ("december_rally",)

                self.calendar_target = 1 if reasons else 0
                self.calendar_hard_flat = False
                self.calendar_reasons = reasons or ("calendar_flat_next_session",)

            if self.calendar_target == 1 and self.use_fomo_gatekeeper:
                candidate, complete = self.gate_candidate(local_now, aggregator)
                metrics = self.signal_engine.metrics(candidate)
                if not complete or not metrics["gate_ready"]:
                    self.calendar_target = 0
                    self.calendar_hard_flat = True
                    self.calendar_reasons = ("gatekeeper_incomplete_1400_bar",)
                elif metrics["is_fomo"]:
                    self.calendar_target = 0
                    self.calendar_hard_flat = True
                    self.calendar_reasons = ("gatekeeper_fomo_blocked",)

            if self.calendar_hard_flat and "gatekeeper_incomplete_1400_bar" not in self.calendar_reasons:
                self.blocked_execution_day = signal_day
            elif self.blocked_execution_day == signal_day:
                self.blocked_execution_day = None

        self.last_afternoon_decision_day = today

    def compose_desired(
        self,
        now: datetime,
    ) -> Tuple[int, Tuple[str, ...]]:
        """Compute desired units and reasons from Calendar and T+2 priority."""
        desired = base_target(
            self.calendar_target,
            self.signal_engine.t2_state if self.use_t2_momentum else 0,
            hard_flat=self.calendar_hard_flat,
        )
        if self.calendar_hard_flat:
            reasons = self.calendar_reasons
        elif self.calendar_target != 0:
            reasons = self.calendar_reasons
        elif self.use_t2_momentum:
            if self.signal_engine.last_t2_reason:
                reasons = self.signal_engine.last_t2_reason
            elif desired == 1:
                reasons = ("t2_hold_long",)
            elif desired == -1:
                reasons = ("t2_hold_short",)
            else:
                reasons = self.calendar_reasons or ("flat",)
        else:
            reasons = self.calendar_reasons or ("flat",)

        self.desired_units = int(desired)
        self.reasons = tuple(reasons)
        return self.desired_units, self.reasons

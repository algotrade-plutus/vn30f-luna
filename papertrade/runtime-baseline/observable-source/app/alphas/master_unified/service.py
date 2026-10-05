"""Fail-closed PaperTrade runtime for the research HybridGatedAlpha.

The package path remains ``alphas.master_unified`` so the existing AWS factory
can be replaced without running a second alpha.  Signal semantics mirror
``PS_V30_Vien_hybrid_gated``; broker reconciliation and execution safety stay
at the adapter boundary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from paperbroker.alpha import AlphaConfig, AlphaContext, OrderRequest, Signal
from algotrade_adapter.account_snapshot import AccountSnapshotExporter
from algotrade_adapter.client import build_client
from algotrade_adapter.market_data import build_market_data
from algotrade_adapter.safe_alpha import SafeSignalDrivenAlpha

from .hybrid_engine import Bar30m, HybridParameters, HybridSignalEngine
from .genesis_engine import GenesisIntradayEngine, GenesisIntradayParameters
from .schedule import (
    AFTERNOON_DECISION_END,
    HCM_TZ,
    HOLIDAY_COVERED_TO,
    contract_expiry,
    core_long_reasons,
    front_month_symbol,
    in_afternoon_decision_window,
    in_morning_decision_window,
    is_expiry_session,
    is_regular_monday,
    is_post_expiry_monday,
    is_post_expiry_friday,
    market_is_open,
    next_decision_plan,
    next_trading_day,
    order_submission_allowed,
    third_thursday,
)

LOGGER = logging.getLogger(__name__)
MAX_HYBRID_GATED_QTY = 10
_TERMINAL_ORDER_STATES = {
    "Canceled",
    "Filled",
    "Rejected",
    "Expired",
    "DoneForDay",
    "CANCELED",
    "FILLED",
    "REJECTED",
    "EXPIRED",
    "DONE_FOR_DAY",
}
_REST_TERMINAL_STATES = {
    "2",
    "4",
    "8",
    "C",
    "FILLED",
    "CANCELED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "DONEFORDAY",
    "DONE_FOR_DAY",
}


def _rest_order_is_terminal(item: Dict[str, Any]) -> bool:
    """Accept any canonical REST status field as authoritative terminal state."""
    for raw in (item.get("ordStatus"), item.get("status"), item.get("statusText")):
        status = str(raw or "").upper().replace(" ", "")
        if status in _REST_TERMINAL_STATES:
            return True
    return False


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}], got {value}")
    return value


def _hybrid_qty() -> int:
    raw = os.getenv("HYBRID_GATED_QTY")
    if raw is None:
        raw = os.getenv("UNIFIED_QTY", os.getenv("CALENDAR_QTY", "1"))
    value = int(raw)
    if not 1 <= value <= MAX_HYBRID_GATED_QTY:
        raise ValueError(
            f"HYBRID_GATED_QTY must be in [1, {MAX_HYBRID_GATED_QTY}], got {value}"
        )
    return value


def _as_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


class HybridGatedPaperAlpha(SafeSignalDrivenAlpha):
    """One-contract executor whose target is the HybridGated position."""

    trigger_on_bar = False
    trigger_on_quote = True
    signal_namespace = "hybrid"
    declared_params = {
        "cancel_after_s",
        "cross_points",
        "eval_interval_s",
        "long_dows",
        "use_month_start",
        "use_preholiday",
        "use_monday_short",
        "use_post_expiry_monday_short",
        "post_exp_monday_min_basis_bps",
        "use_post_expiry_friday_veto",
        "use_december_rally",
        "use_expiry_thursday",
        "monday_max_gap_pct",
        "use_fomo_gatekeeper",
        "max_ret_5bar",
        "max_ret_2bar",
        "ma120_threshold",
        "gate_ma_window",
        "gate_atr_window",
        "use_t2_momentum",
        "t2_fast_bars",
        "t2_slow_bars",
        "t2_macro_bars",
        "t2_macro_trend_bars",
        "t2_long_thresh",
        "t2_short_thresh",
    }

    def __init__(
        self,
        *,
        client: Any,
        market_data: Any,
        config: AlphaConfig,
        account_reader: Any = None,
        account_snapshot_path: Optional[Path] = None,
        warmup_path: Optional[Path] = None,
        seed_warmup_path: Optional[Path] = None,
    ) -> None:
        super().__init__(client=client, market_data=market_data, config=config)
        self._stop_requested = threading.Event()
        self._snapshot_lock = threading.RLock()
        self._portfolio_lock = threading.Lock()
        self._last_eval_monotonic = 0.0
        self._last_quote_epoch: Optional[float] = None
        self._latest_price: Optional[float] = None
        self._last_portfolio_epoch: Optional[float] = None
        self._remote_positions: Dict[str, int] = {}
        self._desired_units = 0
        self._desired_qty: Optional[int] = None
        self._signal_day: Optional[str] = None
        self._reasons: Tuple[str, ...] = ("startup",)
        self._last_error: Optional[str] = None
        self._started_epoch = time.time()

        params = config.params
        self._long_dows = tuple(int(value) for value in params.get("long_dows", (1, 2)))
        self._use_month_start = bool(params.get("use_month_start", True))
        self._use_preholiday = bool(params.get("use_preholiday", True))
        self._use_monday_short = bool(params.get("use_monday_short", True))
        self._use_post_expiry_monday_short = bool(params.get("use_post_expiry_monday_short", True))
        self._post_exp_monday_min_basis_bps = float(params.get("post_exp_monday_min_basis_bps", -15.0))
        self._use_post_expiry_friday_veto = bool(params.get("use_post_expiry_friday_veto", True))
        self._use_december_rally = bool(params.get("use_december_rally", True))
        self._use_expiry_thursday = bool(params.get("use_expiry_thursday", True))
        self._monday_max_gap_pct = float(params.get("monday_max_gap_pct", 0.0))
        self._use_fomo_gatekeeper = bool(params.get("use_fomo_gatekeeper", True))
        self._use_t2_momentum = bool(params.get("use_t2_momentum", True))
        engine_params = HybridParameters(
            max_ret_5bar=float(params.get("max_ret_5bar", 0.011)),
            max_ret_2bar=float(params.get("max_ret_2bar", 0.010)),
            ma120_threshold=float(params.get("ma120_threshold", 4.77)),
            gate_ma_window=int(params.get("gate_ma_window", 120)),
            gate_atr_window=int(params.get("gate_atr_window", 20)),
            t2_fast_bars=int(params.get("t2_fast_bars", 20)),
            t2_slow_bars=int(params.get("t2_slow_bars", 50)),
            t2_macro_bars=int(params.get("t2_macro_bars", 120)),
            t2_macro_trend_bars=int(params.get("t2_macro_trend_bars", 200)),
            t2_long_thresh=float(params.get("t2_long_thresh", 0.008)),
            t2_short_thresh=float(params.get("t2_short_thresh", -0.010)),
        )
        self.signal_engine = HybridSignalEngine(engine_params)

        saved = self.state_store.get("hybrid_runtime", {})
        if not isinstance(saved, dict) or saved.get("symbol") not in (None, self.symbol):
            saved = {}
        self._calendar_target = int(saved.get("calendar_target", 0))
        self._calendar_hard_flat = bool(saved.get("calendar_hard_flat", False))
        self._calendar_reasons = tuple(saved.get("calendar_reasons", ("startup",)))
        self._effective_day = _as_date(saved.get("effective_day"))
        self._blocked_execution_day = _as_date(saved.get("blocked_execution_day"))
        self._last_morning_decision_day = _as_date(saved.get("last_morning_decision_day"))
        self._last_afternoon_decision_day = _as_date(saved.get("last_afternoon_decision_day"))
        saved_t2_state = saved.get("t2_state")
        saved_last_t2_bar = saved.get("last_t2_bar")

        self._warmup_path = warmup_path or Path("/app/runtime/hybrid_gated_warmup_bars.json")
        self._seed_warmup_path = seed_warmup_path or Path("/app/runtime/warmup_bars.json")
        local_runtime = Path(__file__).resolve().parents[2] / "runtime"
        if not self._warmup_path.exists() and not self._seed_warmup_path.exists():
            local_seed = local_runtime / "hybrid_gated_warmup_bars.json"
            if not local_seed.exists():
                local_seed = local_runtime / "warmup_bars.json"
            self._seed_warmup_path = local_seed
        source = self._warmup_path if self._warmup_path.exists() else self._seed_warmup_path
        loaded = self.signal_engine.load_file(
            source,
            persisted_t2_state=(
                int(saved_t2_state) if saved_t2_state in (-1, 0, 1) else None
            ),
            persisted_last_t2_bar=(
                str(saved_last_t2_bar) if saved_last_t2_bar else None
            ),
        )
        LOGGER.info("HybridGated loaded %d warmup bars from %s", loaded, source)

        self._current_bar_start: Optional[datetime] = None
        self._current_bar_first_quote: Optional[datetime] = None
        self._bar_open: Optional[float] = None
        self._bar_high: Optional[float] = None
        self._bar_low: Optional[float] = None
        self._bar_close: Optional[float] = None
        self._bar_transition_pending = False

        self._account_refresh_s = float(os.getenv("ACCOUNT_SNAPSHOT_REFRESH_S", "30"))
        if not 10 <= self._account_refresh_s <= 300:
            raise ValueError("ACCOUNT_SNAPSHOT_REFRESH_S must be in [10, 300]")
        self._account_exporter = None
        if account_reader is not None:
            self._account_exporter = AccountSnapshotExporter(
                account_reader,
                account_snapshot_path or Path("/app/runtime/account.json"),
            )

        self._compose_desired()

    @property
    def symbol(self) -> str:
        return self.config.instruments[0]

    @property
    def target_qty(self) -> int:
        return self.config.qty_for(self.symbol)

    @staticmethod
    def _bucket_start(local_now: datetime) -> Optional[datetime]:
        current = local_now.time()
        if clock_time(9, 0) <= current < clock_time(11, 30):
            minute = 30 if local_now.minute >= 30 else 0
            return local_now.replace(minute=minute, second=0, microsecond=0)
        if current == clock_time(11, 30):
            return local_now.replace(hour=11, minute=0, second=0, microsecond=0)
        if clock_time(13, 0) <= current <= clock_time(14, 45):
            minute = 30 if local_now.minute >= 30 else 0
            return local_now.replace(minute=minute, second=0, microsecond=0)
        return None

    def _current_bar_snapshot(self) -> Optional[Bar30m]:
        if self._current_bar_start is None or self._bar_close is None:
            return None
        return Bar30m(
            datetime=self._current_bar_start.strftime("%Y-%m-%d %H:%M:%S"),
            open=float(self._bar_open if self._bar_open is not None else self._bar_close),
            high=float(self._bar_high if self._bar_high is not None else self._bar_close),
            low=float(self._bar_low if self._bar_low is not None else self._bar_close),
            close=float(self._bar_close),
        )

    def _update_live_bar(self, price: float, local_now: datetime) -> bool:
        bucket_start = self._bucket_start(local_now)
        if bucket_start is None:
            return False
        if self._current_bar_start is None:
            self._start_bar(bucket_start, price, local_now)
            return False
        if bucket_start < self._current_bar_start:
            return False
        if bucket_start == self._current_bar_start:
            self._bar_high = max(float(self._bar_high), price)
            self._bar_low = min(float(self._bar_low), price)
            self._bar_close = price
            return False

        completed = self._current_bar_snapshot()
        added = bool(completed and self.signal_engine.add_completed_bar(completed))
        if added:
            self.signal_engine.save_file(self._warmup_path)
            self._bar_transition_pending = True
            self._compose_desired()
            self._persist_runtime()
            LOGGER.info("hybrid_closed_bar at=%s close=%.2f", completed.datetime, completed.close)
        self._start_bar(bucket_start, price, local_now)
        return added

    def _start_bar(self, bucket_start: datetime, price: float, observed_at: datetime) -> None:
        self._current_bar_start = bucket_start
        self._current_bar_first_quote = observed_at
        self._bar_open = price
        self._bar_high = price
        self._bar_low = price
        self._bar_close = price

    def should_evaluate_on_quote(self, instrument: str, quote: Any) -> bool:
        now_epoch = time.time()
        local_now = datetime.now(HCM_TZ)
        latest = getattr(quote, "latest_matched_price", None)
        with self._snapshot_lock:
            self._last_quote_epoch = now_epoch
            if latest is not None:
                self._latest_price = float(latest)
                self._update_live_bar(self._latest_price, local_now)

            day_changed = (
                self._effective_day is None
                or (
                    self._effective_day != local_now.date()
                    and local_now.time() < AFTERNOON_DECISION_END
                )
            )
            morning_due = (
                in_morning_decision_window(local_now)
                and self._last_morning_decision_day != local_now.date()
            )
            afternoon_due = (
                in_afternoon_decision_window(local_now)
                and self._last_afternoon_decision_day != local_now.date()
            )
            actual = int(self._remote_positions.get(self.symbol, 0))
            reconcile_due = (
                self._desired_qty is not None
                and actual != self._desired_qty
                and order_submission_allowed(local_now)
            )
            due = (
                self._bar_transition_pending
                or day_changed
                or morning_due
                or afternoon_due
                or reconcile_due
            )
        if not market_is_open(local_now) or not due:
            return False
        interval = float(self.config.params.get("eval_interval_s", 2.0))
        now_mono = time.monotonic()
        if now_mono - self._last_eval_monotonic < interval:
            return False
        self._last_eval_monotonic = now_mono
        return True

    def _bootstrap_calendar_day(self, local_now: datetime, quote: Any) -> None:
        today = local_now.date()
        if self._effective_day == today:
            return
        if self._effective_day is not None and self._effective_day > today:
            return

        core_reasons = core_long_reasons(
            today,
            long_dows=self._long_dows,
            use_month_start=self._use_month_start,
            use_preholiday=self._use_preholiday,
        )
        blocked = self._blocked_execution_day == today
        if blocked:
            self._calendar_target = 0
            self._calendar_hard_flat = True
            self._calendar_reasons = ("gatekeeper_blocked_execution",)
        else:
            if core_reasons and self._use_post_expiry_friday_veto and is_post_expiry_friday(today):
                self._calendar_target = 0
                self._calendar_hard_flat = False
                self._calendar_reasons = ("post_expiry_friday_veto",)
            elif core_reasons:
                if self._use_december_rally and today.month == 12:
                    metrics = self.signal_engine.metrics()
                    if metrics.get("sma120") is not None and metrics.get("close") is not None:
                        if metrics["close"] > metrics["sma120"]:
                            core_reasons = core_reasons + ("december_rally",)
                self._calendar_target = 1
                self._calendar_hard_flat = False
                self._calendar_reasons = core_reasons
            else:
                self._calendar_target = 0
                self._calendar_hard_flat = False
                self._calendar_reasons = ("calendar_flat",)
        self._effective_day = today

        if local_now.time() >= clock_time(9, 16):
            self._apply_morning_decision(local_now, quote)
        self._compose_desired()
        self._persist_runtime()

    def _monday_gap(self, day: date, quote: Any) -> Optional[float]:
        previous_close = self.signal_engine.previous_session_close(day)
        if previous_close is None:
            previous_close = getattr(quote, "reference_price", None)
        if previous_close is None:
            previous_close = getattr(quote, "ref_price", None)
        open_price = self._bar_open
        quote_open = getattr(quote, "open_price", None)
        if quote_open is not None:
            open_price = float(quote_open)
        if previous_close is None or open_price is None or float(previous_close) <= 0:
            return None
        return (float(open_price) - float(previous_close)) / float(previous_close)

    def _apply_morning_decision(self, local_now: datetime, quote: Any) -> None:
        today = local_now.date()
        if self._last_morning_decision_day == today:
            return
        if self._calendar_hard_flat or self._calendar_target != 0:
            self._last_morning_decision_day = today
            return

        if self._use_monday_short and is_regular_monday(today):
            gap = self._monday_gap(today, quote)
            if gap is None:
                self._calendar_reasons = ("monday_missing_gap",)
                return
            if gap <= self._monday_max_gap_pct:
                self._calendar_target = -1
                self._calendar_reasons = ("monday_short",)
            else:
                self._calendar_reasons = ("monday_flat_gap",)
        elif self._use_post_expiry_monday_short and is_post_expiry_monday(today):
            if hasattr(self, "_live_basis"):
                basis = getattr(self, "_live_basis")()
                spot = getattr(self, "_latest_spot_price", None)
                basis_bps = (basis / spot * 10000.0) if (basis is not None and spot) else None
                if basis_bps is None:
                    # Do not set _last_morning_decision_day, retry on next quote
                    self._calendar_reasons = ("post_expiry_monday_missing_basis",)
                    return
                if basis_bps >= self._post_exp_monday_min_basis_bps:
                    self._calendar_target = -1
                    self._calendar_reasons = ("post_expiry_monday_short",)
                else:
                    self._calendar_reasons = ("post_expiry_monday_flat",)
            else:
                self._calendar_reasons = ("post_expiry_monday_missing_basis",)
        elif self._use_expiry_thursday and is_expiry_session(today):
            self._calendar_target = 1
            self._calendar_reasons = ("expiry_thursday",)
        else:
            self._calendar_reasons = ("calendar_flat",)
        self._last_morning_decision_day = today

    def _gate_candidate(self, local_now: datetime) -> tuple[Optional[Bar30m], bool]:
        expected = local_now.replace(hour=14, minute=0, second=0, microsecond=0)
        snapshot = self._current_bar_snapshot()
        if snapshot is not None and self._current_bar_start == expected:
            first = self._current_bar_first_quote
            complete = first is not None and (first - expected).total_seconds() <= 120
            return snapshot, complete
        historical = self.signal_engine.bar_at(local_now.date(), 14, 0)
        return historical, historical is not None

    def _apply_afternoon_decision(self, local_now: datetime) -> None:
        today = local_now.date()
        if self._last_afternoon_decision_day == today:
            return
        signal_day = next_trading_day(today)
        self._effective_day = signal_day

        if today == contract_expiry(self.symbol):
            self._calendar_target = 0
            self._calendar_hard_flat = True
            self._calendar_reasons = ("expiry_flatten",)
        else:
            reasons = core_long_reasons(
                signal_day,
                long_dows=self._long_dows,
                use_month_start=self._use_month_start,
                use_preholiday=self._use_preholiday,
            )
            
            if reasons and self._use_post_expiry_friday_veto and is_post_expiry_friday(signal_day):
                self._calendar_target = 0
                self._calendar_hard_flat = False
                self._calendar_reasons = ("post_expiry_friday_veto",)
            else:
                if reasons and self._use_december_rally and signal_day.month == 12:
                    metrics = self.signal_engine.metrics()
                    if metrics.get("sma120") is not None and metrics.get("close") is not None:
                        if metrics["close"] > metrics["sma120"]:
                            reasons = reasons + ("december_rally",)
                
                self._calendar_target = 1 if reasons else 0
                self._calendar_hard_flat = False
                self._calendar_reasons = reasons or ("calendar_flat_next_session",)

            if self._calendar_target == 1 and self._use_fomo_gatekeeper:
                candidate, complete = self._gate_candidate(local_now)
                metrics = self.signal_engine.metrics(candidate)
                if not complete or not metrics["gate_ready"]:
                    self._calendar_target = 0
                    self._calendar_hard_flat = True
                    self._calendar_reasons = ("gatekeeper_incomplete_1400_bar",)
                elif metrics["is_fomo"]:
                    self._calendar_target = 0
                    self._calendar_hard_flat = True
                    self._calendar_reasons = ("gatekeeper_fomo_blocked",)

            if self._calendar_hard_flat:
                self._blocked_execution_day = signal_day
            elif self._blocked_execution_day == signal_day:
                self._blocked_execution_day = None

        self._last_afternoon_decision_day = today
        self._compose_desired()
        self._persist_runtime()

    def _compose_desired(self) -> None:
        if self._calendar_hard_flat:
            desired = 0
            reasons = self._calendar_reasons
        elif self._calendar_target != 0:
            desired = self._calendar_target
            reasons = self._calendar_reasons
        elif self._use_t2_momentum:
            desired = self.signal_engine.t2_state
            if self.signal_engine.last_t2_reason:
                reasons = self.signal_engine.last_t2_reason
            elif desired == 1:
                reasons = ("t2_hold_long",)
            elif desired == -1:
                reasons = ("t2_hold_short",)
            else:
                reasons = self._calendar_reasons or ("flat",)
        else:
            desired = 0
            reasons = self._calendar_reasons or ("flat",)
        self._desired_units = int(desired)
        self._desired_qty = self._desired_units * self.target_qty
        self._signal_day = self._effective_day.isoformat() if self._effective_day else None
        self._reasons = tuple(reasons)

    def _persist_runtime(self) -> None:
        self.state_store.set(
            "hybrid_runtime",
            {
                "schema_version": 1,
                "symbol": self.symbol,
                "calendar_target": self._calendar_target,
                "calendar_hard_flat": self._calendar_hard_flat,
                "calendar_reasons": list(self._calendar_reasons),
                "effective_day": self._effective_day.isoformat() if self._effective_day else None,
                "blocked_execution_day": (
                    self._blocked_execution_day.isoformat()
                    if self._blocked_execution_day
                    else None
                ),
                "last_morning_decision_day": (
                    self._last_morning_decision_day.isoformat()
                    if self._last_morning_decision_day
                    else None
                ),
                "last_afternoon_decision_day": (
                    self._last_afternoon_decision_day.isoformat()
                    if self._last_afternoon_decision_day
                    else None
                ),
                "t2_state": self.signal_engine.t2_state,
                "last_t2_bar": self.signal_engine.last_t2_bar,
                "desired_units": self._desired_units,
                "updated_at": time.time(),
            },
        )
        self.state_store.flush()

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        local_now = ctx.now.astimezone(HCM_TZ)
        quote = ctx.quotes.get(self.symbol)
        if quote is None:
            self._risk_block(f"no quote for {self.symbol}")
            raise RuntimeError(f"No quote for {self.symbol}")
        latest = getattr(quote, "latest_matched_price", None)
        if latest is not None:
            with self._snapshot_lock:
                self._latest_price = float(latest)

        with self._snapshot_lock:
            self._bootstrap_calendar_day(local_now, quote)
            if in_morning_decision_window(local_now):
                self._apply_morning_decision(local_now, quote)
            if in_afternoon_decision_window(local_now):
                self._apply_afternoon_decision(local_now)
            self._compose_desired()
            self._persist_runtime()
            self._bar_transition_pending = False

        try:
            positions = self.fetch_positions()
        except Exception as exc:
            self._risk_block(f"REST portfolio failed: {type(exc).__name__}")
            raise
        with self._snapshot_lock:
            desired_units = self._desired_units
            signal_day = self._effective_day or local_now.date()
            reasons = self._reasons
        return {
            "local_now": local_now,
            "desired_units": desired_units,
            "desired_qty": desired_units * self.target_qty,
            "calendar_target": self._calendar_target,
            "calendar_hard_flat": self._calendar_hard_flat,
            "t2_target": self.signal_engine.t2_state,
            "signal_day": signal_day,
            "reasons": reasons,
            "positions": positions,
        }

    def get_signals(self, indicators: Dict[str, Any], ctx: AlphaContext) -> list[Signal]:
        local_now = indicators["local_now"]
        if not order_submission_allowed(local_now):
            return []

        working = ctx.open_orders.get(self.symbol, [])
        if working:
            oldest = min(order.placed_at for order in working)
            age = (ctx.now - oldest).total_seconds()
            if age >= float(self.config.params.get("cancel_after_s", 8.0)):
                for order in working:
                    terminal, status = self.client.cancel_order(order.cl_ord_id, timeout=3.0)
                    self.logger.warning(
                        "hybrid_cancel_stale cl_ord_id=%s terminal=%s status=%s",
                        order.cl_ord_id,
                        terminal,
                        status,
                    )
            return []

        positions: Dict[str, int] = indicators["positions"]
        foreign = {
            symbol: qty
            for symbol, qty in positions.items()
            if symbol != self.symbol and qty != 0
        }
        if foreign:
            return self._risk_block(f"foreign positions present: {sorted(foreign)}")

        actual = int(positions.get(self.symbol, 0))
        if not -self.target_qty <= actual <= self.target_qty:
            return self._risk_block(
                f"unexpected {self.symbol} position actual={actual} "
                f"target_range=[{-self.target_qty},{self.target_qty}]"
            )
        tracked = ctx.positions.get(self.symbol)
        if tracked is not None and int(tracked.quantity) != actual:
            working = ctx.open_orders.get(self.symbol, [])
            if not working and self._position_tracker is not None:
                self.reconcile_positions(positions, ctx.open_orders)
                tracked_pos = self._position_tracker.get(self.symbol)
                if tracked_pos is not None and int(tracked_pos.quantity) == actual:
                    tracked.quantity = float(actual)
                    self.logger.info(
                        "Reconciled position drift on %s: local adjusted to %s to match remote",
                        self.symbol,
                        actual,
                    )
                else:
                    return self._risk_block(
                        f"position drift local={tracked.quantity} remote={actual}; "
                        "waiting for REST convergence"
                    )
            else:
                return self._risk_block(
                    f"position drift local={tracked.quantity} remote={actual}; "
                    "waiting for REST convergence"
                )

        desired = int(indicators["desired_qty"])
        # A direct reversal (for example -8 -> +8) overstates the capacity
        # required by asking the broker for one BUY 16 batch.  Flatten first;
        # after REST confirms zero, the quote-driven reconciler submits the
        # opening leg as a separate capacity-checked order.
        reversing = actual != 0 and desired != 0 and (actual > 0) != (desired > 0)
        leg_target = 0 if reversing else desired
        delta = leg_target - actual
        decision = {
            "at": ctx.now.isoformat(),
            "symbol": self.symbol,
            "actual": actual,
            "desired": desired,
            "signal_day": indicators["signal_day"].isoformat(),
            "reasons": list(indicators["reasons"]),
        }
        if delta == 0:
            with self._snapshot_lock:
                self._last_error = None
            self.state_store.set("last_converged", decision)
            self.state_store.flush()
            return []
        if not self.client.allow_orders:
            self.state_store.set("last_shadow_decision", decision)
            self.state_store.flush()
            self.logger.info("hybrid_shadow_decision %s", decision)
            return []

        side = "BUY" if delta > 0 else "SELL"
        self.state_store.set(
            "last_submit_intent",
            {**decision, "side": side, "qty": abs(delta)},
        )
        self.state_store.flush()
        return [
            Signal(
                symbol=self.symbol,
                side=side,
                tag=(
                    f"{self.signal_namespace}_reversal_close"
                    if reversing
                    else self.signal_namespace
                    + "_"
                    + "_".join(indicators["reasons"] or ("flat",))
                ),
                metadata={
                    "qty": abs(delta),
                    "signal_day": indicators["signal_day"].isoformat(),
                },
            )
        ]

    def _risk_block(self, message: str) -> list[Signal]:
        with self._snapshot_lock:
            self._last_error = message
        self.logger.error("hybrid_risk_block %s", message)
        return []

    def get_entry_price(self, signal: Signal, ctx: AlphaContext) -> Optional[float]:
        quote = ctx.quotes.get(signal.symbol)
        if quote is None:
            self._risk_block(f"no quote for {signal.symbol}")
            return None
        latest = getattr(quote, "latest_matched_price", None)
        cross = float(self.config.params.get("cross_points", 0.1))
        if signal.side == "BUY":
            base = getattr(quote, "ask_price_1", None) or latest
            ceiling = getattr(quote, "ceiling_price", None)
            price = None if base is None else float(base) + cross
            return min(price, float(ceiling)) if price is not None and ceiling else price
        base = getattr(quote, "bid_price_1", None) or latest
        floor = getattr(quote, "floor_price", None)
        price = None if base is None else float(base) - cross
        return max(price, float(floor)) if price is not None and floor else price

    def get_quantity(self, signal: Signal, ctx: AlphaContext) -> int:
        return int(signal.metadata.get("qty", 0))

    def plan_orders(self, signal: Signal, ctx: AlphaContext) -> list[OrderRequest]:
        price = self.get_entry_price(signal, ctx)
        qty = self.get_quantity(signal, ctx)
        if price is None or qty <= 0:
            return []
        capacity = self.client.get_max_placeable(self.symbol, price, signal.side)
        if not isinstance(capacity, dict) or not capacity.get("success"):
            return self._risk_block("get_max_placeable failed")
        if not capacity.get("unlimited") and float(capacity.get("maxQty", 0) or 0) < qty:
            return self._risk_block(
                f"max placeable below request: max={capacity.get('maxQty')} requested={qty}"
            )
        return [
            OrderRequest(
                symbol=self.symbol,
                side=signal.side,
                qty=qty,
                price=round(price, 1),
                ord_type="LIMIT",
                tag=signal.tag,
            )
        ]

    @staticmethod
    def _normalise_symbol(raw: Any) -> Optional[str]:
        value = str(raw or "").strip()
        if not value:
            return None
        return value if ":" in value else f"HNXDS:{value}"

    def fetch_positions(self) -> Dict[str, int]:
        with self._portfolio_lock:
            payload = self.client.get_portfolio_by_sub()
        if not isinstance(payload, dict) or not payload.get("success"):
            raise RuntimeError("REST portfolio query failed")
        positions: Dict[str, int] = {}
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            symbol = self._normalise_symbol(item.get("instrument") or item.get("symbol"))
            if symbol is None:
                continue
            raw_qty = item.get("quantity")
            if raw_qty is None:
                raw_qty = item.get("openQuantity", 0)
            quantity = int(float(raw_qty or 0))
            if quantity:
                positions[symbol] = quantity
        with self._snapshot_lock:
            self._remote_positions = positions
            self._last_portfolio_epoch = time.time()
        return dict(positions)

    def _recover_orders(self) -> None:
        for row in self.client.recover_pending_orders():
            cl_ord_id = row.get("cl_ord_id")
            if not cl_ord_id:
                raise RuntimeError("Recovered order has no cl_ord_id")
            self.client.request_order_status(cl_ord_id)
            self.client.wait_for(cl_ord_id, _TERMINAL_ORDER_STATES, timeout=3.0)
            if not self.client.is_order_done(cl_ord_id):
                terminal, status = self.client.cancel_order(cl_ord_id, timeout=5.0)
                if not terminal:
                    raise RuntimeError(
                        f"Cannot settle recovered order {cl_ord_id}: status={status}"
                    )
            self.client.cleanup_order(cl_ord_id)

    def _assert_no_remote_working_orders(self) -> None:
        get_orders = getattr(self.client, "get_orders", None)
        if get_orders is None:
            raise RuntimeError("REST get_orders is unavailable")
        today = datetime.now(HCM_TZ).date()
        payload = get_orders((today - timedelta(days=1)).isoformat(), today.isoformat())
        if not isinstance(payload, dict) or not payload.get("success"):
            raise RuntimeError("REST order reconciliation failed")
        active: list[str] = []
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            leaves = float(item.get("leavesQty", 0) or 0)
            if not _rest_order_is_terminal(item) and leaves > 0:
                symbol = self._normalise_symbol(item.get("symbol") or item.get("instrument"))
                active.append(symbol or "unknown")
        if active:
            raise RuntimeError(f"Refusing startup with REST working orders: {sorted(active)}")

    async def start(self) -> None:
        self.client.connect()
        if not self.client.wait_until_logged_on(timeout=15.0):
            raise RuntimeError(f"FIX logon failed: {self.client.last_logon_error()}")
        self._recover_orders()
        self._assert_no_remote_working_orders()
        positions = self.fetch_positions()
        foreign = {
            symbol: qty
            for symbol, qty in positions.items()
            if symbol != self.symbol and qty != 0
        }
        if foreign:
            raise RuntimeError(f"Refusing startup with foreign positions: {sorted(foreign)}")
        actual = int(positions.get(self.symbol, 0))
        if not -self.target_qty <= actual <= self.target_qty:
            raise RuntimeError(f"Refusing startup with out-of-range position: {actual}")
        await super().start()
        self.seed_positions(positions)

    def stop(self) -> None:
        self._stop_requested.set()

    def run(self) -> None:
        loop = asyncio.new_event_loop()

        async def managed() -> None:
            started = False
            next_account_refresh = 0.0
            try:
                await self.start()
                started = True
                while not self._stop_requested.is_set() and self.state == self.STATE_RUNNING:
                    now_mono = time.monotonic()
                    if now_mono >= next_account_refresh:
                        try:
                            await asyncio.to_thread(self.fetch_positions)
                            if self._account_exporter is not None:
                                await asyncio.to_thread(self._export_account_snapshot)
                        except Exception as exc:
                            self._risk_block(f"account_refresh_failed:{type(exc).__name__}")
                        next_account_refresh = now_mono + self._account_refresh_s
                    await asyncio.sleep(0.5)
            finally:
                self._persist_runtime()
                if started:
                    SafeSignalDrivenAlpha.stop(self)
                await self.market_data.stop()
                self.client.disconnect()

        try:
            loop.run_until_complete(managed())
        finally:
            loop.close()

    def _export_account_snapshot(self) -> None:
        if self._account_exporter is None:
            return
        with self._snapshot_lock:
            latest_price = self._latest_price
        self._account_exporter.collect(
            symbol=self.symbol,
            latest_price=latest_price,
            target_qty=self.target_qty,
        )

    def health_snapshot(self) -> Dict[str, Any]:
        now_epoch = time.time()
        local_now = datetime.now(HCM_TZ)
        decision_at, next_signal_day, next_reasons = next_decision_plan(local_now)
        candidate = self._current_bar_snapshot()
        metrics = self.signal_engine.metrics(candidate)
        with self._snapshot_lock:
            feed_age = (
                None if self._last_quote_epoch is None else round(now_epoch - self._last_quote_epoch, 1)
            )
            portfolio_age = (
                None
                if self._last_portfolio_epoch is None
                else round(now_epoch - self._last_portfolio_epoch, 1)
            )
            snapshot = {
                "status": "running" if self.state == self.STATE_RUNNING else self.state,
                "updated_at": now_epoch,
                "mode": "alpha",
                "alpha": "HybridGatedPaperAlpha",
                "symbol": self.symbol,
                "fix_logged_on": bool(self.client.is_logged_on()),
                "feed_age_s": feed_age,
                "portfolio_age_s": portfolio_age,
                "positions": dict(self._remote_positions),
                "desired_qty": self._desired_qty,
                "signal_day": self._signal_day,
                "reasons": list(self._reasons),
                "calendar_target": self._calendar_target,
                "calendar_hard_flat": self._calendar_hard_flat,
                "t2_target": self.signal_engine.t2_state,
                "warmup_bars": self.signal_engine.bar_count,
                "momentum_ready": metrics["ready"],
                "gate_ready": metrics["gate_ready"],
                "momentum_ret_2d": (
                    round(metrics["ret_2d"] * 100, 3)
                    if metrics["ret_2d"] is not None
                    else None
                ),
                "gate_ret_5bar": (
                    round(metrics["ret_5bar"] * 100, 3)
                    if metrics["ret_5bar"] is not None
                    else None
                ),
                "gate_ret_2bar": (
                    round(metrics["ret_2bar"] * 100, 3)
                    if metrics["ret_2bar"] is not None
                    else None
                ),
                "gate_dist_ma120": (
                    round(metrics["dist_ma120"], 3)
                    if metrics["dist_ma120"] is not None
                    else None
                ),
                "order_gate": bool(self.client.allow_orders),
                "last_error": self._last_error,
                "uptime_s": round(now_epoch - self._started_epoch, 1),
                "configured_qty": self.target_qty,
                "next_decision_at": decision_at.isoformat(),
                "next_signal_day": next_signal_day.isoformat(),
                "next_calendar_target_qty": (1 if next_reasons else 0) * self.target_qty,
                "next_reasons": list(next_reasons),
            }
        grace_elapsed = now_epoch - self._started_epoch > 90
        feed_stale = market_is_open(local_now) and grace_elapsed and (
            feed_age is None or feed_age > 120
        )
        portfolio_stale = market_is_open(local_now) and grace_elapsed and (
            portfolio_age is None or portfolio_age > 120
        )
        snapshot["healthy"] = (
            self.state == self.STATE_RUNNING
            and snapshot["fix_logged_on"]
            and not feed_stale
            and not portfolio_stale
            and snapshot["last_error"] is None
        )
        return snapshot


class GenesisPaperAlpha(HybridGatedPaperAlpha):
    """Full Genesis signal stack with point-in-time cross-asset basis."""

    signal_namespace = "genesis"
    declared_params = HybridGatedPaperAlpha.declared_params | {
        "index_symbol",
        "basis_max_age_s",
        "use_orb_breakout",
        "orb_thresh_pct",
        "min_range_pct",
        "orb_mode",
        "use_lunch_gap",
        "lunch_gap_thresh_pct",
        "use_basis_veto",
        "basis_veto_bps",
        "use_expiry_basis_arb",
        "expiry_basis_thresh_bps",
        "days_before_expiry",
    }

    def __init__(self, **kwargs: Any) -> None:
        config: AlphaConfig = kwargs["config"]
        params = config.params
        self.index_symbol = str(params.get("index_symbol", "HSX:VN30"))
        if self.index_symbol not in config.instruments:
            raise ValueError(f"index_symbol {self.index_symbol!r} is not subscribed")
        self._basis_max_age_s = float(params.get("basis_max_age_s", 900.0))
        if not 1 <= self._basis_max_age_s <= 3600:
            raise ValueError("basis_max_age_s must be in [1, 3600]")
        self._latest_spot_price: Optional[float] = None
        self._last_spot_quote_epoch: Optional[float] = None
        self._basis: Optional[float] = None
        self._basis_ready = False
        self._evaluation_now: Optional[datetime] = None
        self._use_orb_breakout = bool(params.get("use_orb_breakout", True))
        self._use_lunch_gap = bool(params.get("use_lunch_gap", True))
        self._use_basis_veto = bool(params.get("use_basis_veto", True))
        self._use_expiry_basis_arb = bool(params.get("use_expiry_basis_arb", True))
        self.intraday_engine = GenesisIntradayEngine(
            GenesisIntradayParameters(
                orb_thresh_pct=float(params.get("orb_thresh_pct", 0.0)),
                min_range_pct=float(params.get("min_range_pct", 0.0)),
                orb_mode=str(params.get("orb_mode", "short_only")),
                lunch_gap_thresh_pct=float(params.get("lunch_gap_thresh_pct", -0.0003)),
                basis_veto_bps=float(params.get("basis_veto_bps", 45.0)),
                expiry_basis_thresh_bps=float(params.get("expiry_basis_thresh_bps", 30.0)),
                days_before_expiry=tuple(
                    int(value) for value in params.get("days_before_expiry", (1, 2, 3))
                ),
            )
        )
        super().__init__(**kwargs)
        self._seed_spot_quote_if_needed()

    def _seed_spot_quote_if_needed(self) -> None:
        if self._latest_spot_price is not None:
            return
        try:
            from kafka import KafkaConsumer, TopicPartition
            bootstrap_servers = os.getenv("PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS")
            if not bootstrap_servers:
                return
            username = os.getenv("PAPERBROKER_KAFKA_USERNAME")
            password = os.getenv("PAPERBROKER_KAFKA_PASSWORD")
            env_id = os.getenv("PAPERBROKER_ENV_ID", "real")
            topic = f"{env_id}.{self.index_symbol.replace(':', '.')}"
            consumer = KafkaConsumer(
                bootstrap_servers=bootstrap_servers.split(","),
                security_protocol="SASL_PLAINTEXT" if username else "PLAINTEXT",
                sasl_mechanism="PLAIN" if username else None,
                sasl_plain_username=username,
                sasl_plain_password=password,
                request_timeout_ms=5000,
            )
            tp = TopicPartition(topic, 0)
            consumer.assign([tp])
            end_offset = consumer.end_offsets([tp]).get(tp, 0)
            if end_offset > 0:
                consumer.seek(tp, end_offset - 1)
                records = consumer.poll(timeout_ms=3000)
                for rec in records.get(tp, []):
                    val = json.loads(rec.value.decode("utf-8"))
                    entries = val.get("entries", val)
                    price = entries.get("latest_matched_price") if isinstance(entries, dict) else None
                    if price is not None:
                        with self._snapshot_lock:
                            self._latest_spot_price = float(price)
                            self._last_spot_quote_epoch = rec.timestamp / 1000.0
                            self._live_basis()
            consumer.close()
        except Exception as exc:
            LOGGER.warning("Could not seed initial spot quote from Kafka: %s", exc)

    def should_evaluate_on_quote(self, instrument: str, quote: Any) -> bool:
        if instrument == self.index_symbol:
            latest = getattr(quote, "latest_matched_price", None)
            if latest is not None:
                with self._snapshot_lock:
                    self._latest_spot_price = float(latest)
                    observed_at = getattr(quote, "timestamp", None)
                    if isinstance(observed_at, datetime):
                        if observed_at.tzinfo is None:
                            observed_at = observed_at.replace(tzinfo=HCM_TZ)
                        observed_at = observed_at.timestamp()
                    self._last_spot_quote_epoch = (
                        float(observed_at) if observed_at is not None else time.time()
                    )
                    self._live_basis()
            return False
        if instrument != self.symbol:
            return False
        return super().should_evaluate_on_quote(instrument, quote)

    def _live_basis(self) -> Optional[float]:
        now_epoch = time.time()
        if (
            self._latest_price is None
            or self._latest_spot_price is None
            or self._last_spot_quote_epoch is None
            or now_epoch - self._last_spot_quote_epoch > self._basis_max_age_s
        ):
            self._basis_ready = False
            self._basis = None
            return None
        self._basis_ready = True
        self._basis = float(self._latest_price) - float(self._latest_spot_price)
        return self._basis

    def _compose_desired(self) -> None:
        super()._compose_desired()
        now = self._evaluation_now or datetime.now(HCM_TZ)
        basis = self._live_basis()
        if not hasattr(self, "intraday_engine") or self._calendar_hard_flat:
            return

        basis_bps = None
        if basis is not None and self._latest_spot_price is not None and self._latest_spot_price > 0:
            basis_bps = (basis / self._latest_spot_price) * 10000.0

        is_at_end = in_afternoon_decision_window(now)

        snapshot = self.intraday_engine.evaluate(
            bars=self.signal_engine.bars,
            current=self._current_bar_snapshot(),
            now=now,
            basis_bps=basis_bps,
            pre_atc=is_at_end,
        )
        desired = self._desired_units
        reasons = self._reasons

        # SC3, SC4, SC5 Scope Errors: Intraday signals are NOT held overnight
        if not is_at_end:
            if desired == 0 and self._use_orb_breakout and snapshot.orb:
                desired, reasons = snapshot.orb, ("orb_breakout",)
            if desired == 0 and self._use_lunch_gap and snapshot.lunch:
                desired, reasons = snapshot.lunch, ("lunch_gap",)
            if self._use_expiry_basis_arb and snapshot.expiry_arb == -1:
                desired, reasons = -1, ("expiry_basis_arb",)

        # Basis Veto triggers when pre_atc (is_at_end) is True
        if self._use_basis_veto and snapshot.basis_veto and desired == 1:
            desired, reasons = 0, ("basis_veto",)

        self._desired_units = int(desired)
        self._desired_qty = self._desired_units * self.target_qty
        self._reasons = tuple(reasons)

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        self._evaluation_now = ctx.now.astimezone(HCM_TZ)
        try:
            indicators = super().get_indicators(ctx)
        finally:
            self._evaluation_now = None
        indicators.update(
            {
                "basis": self._basis,
                "basis_ready": self._basis_ready,
                "index_symbol": self.index_symbol,
            }
        )
        return indicators

    def _needs_basis_feed(self, local_now: datetime) -> bool:
        days_to_expiry = (third_thursday(local_now.year, local_now.month) - local_now.date()).days
        return bool(
            (self._use_basis_veto and in_afternoon_decision_window(local_now))
            or (
                self._use_expiry_basis_arb
                and days_to_expiry in self.intraday_engine.params.days_before_expiry
            )
        )

    def get_signals(self, indicators: Dict[str, Any], ctx: AlphaContext) -> list[Signal]:
        local_now = indicators.get("local_now") or datetime.now(HCM_TZ)
        if self._needs_basis_feed(local_now) and not indicators.get(
            "basis_ready", False
        ):
            positions: Dict[str, int] = indicators.get("positions", {})
            actual = int(positions.get(self.symbol, 0))
            desired = int(indicators.get("desired_qty", 0))
            risk_reducing = desired == 0 or (
                actual != 0 and desired != 0 and (actual > 0) != (desired > 0)
            )
            if not risk_reducing and "expiry_basis_arb" in indicators.get("reasons", ()):
                LOGGER.warning("basis feed unavailable or stale; skipping expiry basis arb")
                return []
        return super().get_signals(indicators, ctx)

    def health_snapshot(self) -> Dict[str, Any]:
        snapshot = super().health_snapshot()
        basis = self._live_basis()
        spot_age = (
            None
            if self._last_spot_quote_epoch is None
            else round(time.time() - self._last_spot_quote_epoch, 1)
        )
        snapshot.update(
            {
                "alpha": "GenesisPaperAlpha",
                "index_symbol": self.index_symbol,
                "spot_source": getattr(self.market_data, "spot_source", "kafka"),
                "spot_feed_age_s": spot_age,
                "basis": basis,
                "basis_ready": self._basis_ready,
            }
        )
        local_now = datetime.now(HCM_TZ)
        grace_elapsed = time.time() - self._started_epoch > 90
        basis_stale = (
            market_is_open(local_now)
            and grace_elapsed
            and self._needs_basis_feed(local_now)
            and not self._basis_ready
        )
        snapshot["basis_stale"] = basis_stale
        snapshot["healthy"] = bool(snapshot["healthy"])
        return snapshot


class HybridGatedSupervisor:
    """Run exactly one HybridGated child and rotate its VN30 contract."""

    def __init__(self) -> None:
        self._stop_requested = threading.Event()
        self._child_lock = threading.RLock()
        self._child: Optional[HybridGatedPaperAlpha] = None
        self._child_thread: Optional[threading.Thread] = None
        self._child_error: Optional[BaseException] = None

    def _resolved_symbol(self) -> str:
        mode = os.getenv("VN30F_ROLLOVER_MODE", "auto").strip().lower()
        if mode == "fixed":
            symbol = os.environ["VN30F1M"].strip()
            if not symbol:
                raise ValueError("VN30F1M is empty in fixed rollover mode")
            return symbol
        if mode != "auto":
            raise ValueError("VN30F_ROLLOVER_MODE must be auto or fixed")
        return front_month_symbol(datetime.now(HCM_TZ))

    def _build_child(self, symbol: str) -> HybridGatedPaperAlpha:
        if datetime.now(HCM_TZ).date() > HOLIDAY_COVERED_TO:
            raise RuntimeError("Holiday calendar expired; update it before trading")
        qty = _hybrid_qty()
        client = build_client(enable_fix=True)
        account_reader = build_client(
            enable_fix=False,
            order_store_path=Path("runtime/dashboard_orders.db"),
            allow_orders=False,
        )
        market_data = build_market_data()
        state_dir = Path("/app/state")
        runtime_dir = Path("/app/runtime")
        if not state_dir.exists():
            app_root = Path(__file__).resolve().parents[2]
            state_dir = app_root / "state"
            runtime_dir = app_root / "runtime"
        config = AlphaConfig.single(
            instrument=symbol,
            sub_account=os.environ["PAPER_ACCOUNT_ID"],
            timeframe="30m",
            qty=qty,
            params={
                "cancel_after_s": float(os.getenv("HYBRID_GATED_CANCEL_AFTER_S", "8")),
                "cross_points": float(os.getenv("HYBRID_GATED_CROSS_POINTS", "0.1")),
                "eval_interval_s": float(os.getenv("HYBRID_GATED_EVAL_INTERVAL_S", "2")),
                "long_dows": (1, 2),
                "use_month_start": True,
                "use_preholiday": True,
                "use_monday_short": True,
                "use_expiry_thursday": True,
                "monday_max_gap": float(os.getenv("HYBRID_GATED_MONDAY_MAX_GAP", "0.0")),
                "use_fomo_gatekeeper": True,
                "max_ret_5bar": float(os.getenv("HYBRID_GATED_MAX_RET_5BAR", "0.011")),
                "max_ret_2bar": float(os.getenv("HYBRID_GATED_MAX_RET_2BAR", "0.010")),
                "ma120_threshold": float(os.getenv("HYBRID_GATED_MA120_THRESHOLD", "4.77")),
                "gate_ma_window": 120,
                "gate_atr_window": 20,
                "use_t2_momentum": True,
                "t2_fast_bars": 20,
                "t2_slow_bars": 50,
                "t2_macro_bars": 120,
                "t2_macro_trend_bars": 200,
                "t2_long_thresh": float(os.getenv("HYBRID_GATED_T2_LONG_THRESH", "0.008")),
                "t2_short_thresh": float(os.getenv("HYBRID_GATED_T2_SHORT_THRESH", "-0.010")),
            },
            state_path=str(state_dir / f"hybrid_gated_{symbol.replace(':', '_')}.json"),
            log_dir="logs",
        )
        return HybridGatedPaperAlpha(
            client=client,
            market_data=market_data,
            config=config,
            account_reader=account_reader,
            account_snapshot_path=runtime_dir / "account.json",
            warmup_path=runtime_dir / "hybrid_gated_warmup_bars.json",
            seed_warmup_path=runtime_dir / "warmup_bars.json",
        )

    def _start_child(self, symbol: str) -> None:
        child = self._build_child(symbol)
        self._child_error = None

        def target() -> None:
            try:
                child.run()
            except BaseException as exc:
                self._child_error = exc
                LOGGER.exception("HybridGatedPaperAlpha failed: %s", exc)

        thread = threading.Thread(target=target, name=f"hybrid.{symbol}", daemon=True)
        with self._child_lock:
            self._child = child
            self._child_thread = thread
        thread.start()

    def _stop_child(self) -> None:
        with self._child_lock:
            child, thread = self._child, self._child_thread
        if child is not None:
            child.stop()
        if thread is not None:
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("HybridGated alpha did not stop within 20 seconds")
        with self._child_lock:
            self._child = None
            self._child_thread = None

    def run(self) -> None:
        self._start_child(self._resolved_symbol())
        try:
            while not self._stop_requested.wait(10):
                with self._child_lock:
                    child, thread = self._child, self._child_thread
                if child is None or thread is None:
                    raise RuntimeError("HybridGated child is missing")
                if not thread.is_alive():
                    if self._child_error is not None:
                        raise RuntimeError("HybridGated child failed") from self._child_error
                    raise RuntimeError("HybridGated child stopped unexpectedly")
                health = child.health_snapshot()
                if not health.get("fix_logged_on", False) and float(health.get("uptime_s", 0)) > 180:
                    raise RuntimeError("HybridGated child lost FIX logon for > 180s")
                if not health.get("healthy", False):
                    LOGGER.warning("HybridGated child reporting unhealthy state: %s", health.get("last_error"))
                resolved = self._resolved_symbol()
                if resolved != child.symbol:
                    positions = child.fetch_positions()
                    if positions.get(child.symbol, 0) != 0:
                        raise RuntimeError(
                            f"Rollover blocked: {child.symbol} position is not flat"
                        )
                    LOGGER.info("hybrid_rollover old=%s new=%s", child.symbol, resolved)
                    self._stop_child()
                    self._start_child(resolved)
        finally:
            self._stop_child()

    def stop(self) -> None:
        self._stop_requested.set()
        with self._child_lock:
            child = self._child
        if child is not None:
            child.stop()

    def health_snapshot(self) -> Dict[str, Any]:
        with self._child_lock:
            child, thread = self._child, self._child_thread
        if child is None:
            return {"healthy": False, "alpha": type(self).__name__, "reason": "starting"}
        snapshot = child.health_snapshot()
        snapshot["alpha"] = type(self).__name__
        snapshot["worker_alive"] = bool(thread and thread.is_alive())
        return snapshot


def build_hybrid_gated_service() -> HybridGatedSupervisor:
    """Preferred factory name for new configuration."""
    return HybridGatedSupervisor()


class GenesisSupervisor(HybridGatedSupervisor):
    """Run one full Genesis child and rotate its execution contract."""

    def _build_child(self, symbol: str) -> GenesisPaperAlpha:
        if datetime.now(HCM_TZ).date() > HOLIDAY_COVERED_TO:
            raise RuntimeError("Holiday calendar expired; update it before trading")
        qty = _hybrid_qty()
        index_symbol = os.getenv("VN30_INDEX", "HSX:VN30").strip()
        client = build_client(enable_fix=True)
        account_reader = build_client(
            enable_fix=False,
            order_store_path=Path("runtime/dashboard_orders.db"),
            allow_orders=False,
        )
        market_data = build_market_data(spot_symbol=index_symbol)
        state_dir = Path("/app/state")
        runtime_dir = Path("/app/runtime")
        if not state_dir.exists():
            app_root = Path(__file__).resolve().parents[2]
            state_dir = app_root / "state"
            runtime_dir = app_root / "runtime"
        config = AlphaConfig(
            instruments=[symbol, index_symbol],
            sub_account=os.environ["PAPER_ACCOUNT_ID"],
            timeframe="30m",
            qty={symbol: qty},
            params={
                "cancel_after_s": float(os.getenv("GENESIS_CANCEL_AFTER_S", "8")),
                "cross_points": float(os.getenv("GENESIS_CROSS_POINTS", "0.1")),
                "eval_interval_s": float(os.getenv("GENESIS_EVAL_INTERVAL_S", "2")),
                "index_symbol": index_symbol,
                "basis_max_age_s": float(os.getenv("GENESIS_BASIS_MAX_AGE_S", "15")),
                "long_dows": (1, 2),
                "use_month_start": True,
                "use_preholiday": True,
                "use_monday_short": True,
                "use_post_expiry_monday_short": True,
                "post_exp_monday_min_basis_bps": float(os.getenv("GENESIS_POST_EXP_MON_BASIS", "-15.0")),
                "use_post_expiry_friday_veto": True,
                "use_december_rally": True,
                "use_expiry_thursday": True,
                "monday_max_gap_pct": float(os.getenv("GENESIS_MONDAY_MAX_GAP_PCT", "0.0")),
                "use_fomo_gatekeeper": True,
                "max_ret_5bar": float(os.getenv("GENESIS_MAX_RET_5BAR", "0.011")),
                "max_ret_2bar": float(os.getenv("GENESIS_MAX_RET_2BAR", "0.010")),
                "ma120_threshold": float(os.getenv("GENESIS_MA120_THRESHOLD", "4.77")),
                "gate_ma_window": 120,
                "gate_atr_window": 20,
                "use_t2_momentum": True,
                "t2_fast_bars": 20,
                "t2_slow_bars": 50,
                "t2_macro_bars": 120,
                "t2_macro_trend_bars": 200,
                "t2_long_thresh": float(os.getenv("GENESIS_T2_LONG_THRESH", "0.008")),
                "t2_short_thresh": float(os.getenv("GENESIS_T2_SHORT_THRESH", "-0.010")),
                "use_orb_breakout": True,
                "orb_thresh_pct": float(os.getenv("GENESIS_ORB_THRESH_PCT", "0.0")),
                "min_range_pct": float(os.getenv("GENESIS_ORB_MIN_RANGE_PCT", "0.0")),
                "orb_mode": os.getenv("GENESIS_ORB_MODE", "short_only"),
                "use_lunch_gap": True,
                "lunch_gap_thresh_pct": float(os.getenv("GENESIS_LUNCH_GAP_THRESH_PCT", "-0.0003")),
                "use_basis_veto": True,
                "basis_veto_bps": float(os.getenv("GENESIS_BASIS_VETO_BPS", "45.0")),
                "use_expiry_basis_arb": True,
                "expiry_basis_thresh_bps": float(
                    os.getenv("GENESIS_EXPIRY_BASIS_THRESH_BPS", "30.0")
                ),
                "days_before_expiry": (1, 2, 3),
            },
            state_path=str(state_dir / f"genesis_{symbol.replace(':', '_')}.json"),
            log_dir="logs",
        )
        return GenesisPaperAlpha(
            client=client,
            market_data=market_data,
            config=config,
            account_reader=account_reader,
            account_snapshot_path=runtime_dir / "account.json",
            warmup_path=runtime_dir / "genesis_warmup_bars.json",
            seed_warmup_path=runtime_dir / "warmup_bars.json",
        )


def build_genesis_service() -> GenesisSupervisor:
    return GenesisSupervisor()


def build_unified_service() -> GenesisSupervisor:
    """Compatibility factory used by the currently configured AWS service."""
    return build_genesis_service()


# Compatibility imports for existing local tooling. They now point to the
# replacement implementation; no second alpha is created.
MasterUnifiedPaperAlpha = GenesisPaperAlpha
MasterUnifiedSupervisor = GenesisSupervisor

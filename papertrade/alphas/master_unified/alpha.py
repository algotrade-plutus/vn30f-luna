"""PaperTrade execution runtime implementation for the HybridGated alpha.

Coordinates paperbroker-client event hooks, BarAggregator, SignalComposer,
and position reconciliation at the broker boundary.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from paperbroker.alpha import AlphaConfig, AlphaContext, OrderRequest, Signal
from algotrade_adapter.account_snapshot import AccountSnapshotExporter
from algotrade_adapter.safe_alpha import SafeSignalDrivenAlpha
from runtime_core.reconcile import (
    TERMINAL_ORDER_STATES as _REST_TERMINAL_STATES,
    normalize_symbol,
    order_is_terminal,
    reconcile_account,
)

from .bar_aggregator import BarAggregator
from .hybrid_engine import Bar30m, HybridParameters, HybridSignalEngine
from .schedule import (
    AFTERNOON_DECISION_END,
    HCM_TZ,
    in_afternoon_decision_window,
    in_morning_decision_window,
    market_is_open,
    next_decision_plan,
    order_submission_allowed,
)
from .signal_composer import SignalComposer, _as_date

LOGGER = logging.getLogger(__name__)
MAX_HYBRID_GATED_QTY = 10

_TERMINAL_ORDER_STATES = {
    "Canceled", "Filled", "Rejected", "Expired", "DoneForDay",
    "CANCELED", "FILLED", "REJECTED", "EXPIRED", "DONE_FOR_DAY",
}
def _rest_order_is_terminal(item: Dict[str, Any]) -> bool:
    """Compatibility facade for callers importing the legacy helper."""
    return order_is_terminal(item)


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
        raise ValueError(f"HYBRID_GATED_QTY must be in [1, {MAX_HYBRID_GATED_QTY}], got {value}")
    return value


class HybridGatedPaperAlpha(SafeSignalDrivenAlpha):
    """One-contract executor whose target is the HybridGated position."""

    trigger_on_bar = False
    trigger_on_quote = True
    signal_namespace = "hybrid"
    declared_params = {
        "cancel_after_s",
        "cross_points",
        "eval_interval_s",
        "account_refresh_s",
        "long_dows",
        "use_month_start",
        "use_preholiday",
        "use_monday_short",
        "use_post_expiry_monday_short",
        "post_exp_monday_min_basis_bps",
        "use_post_expiry_friday_veto",
        "use_december_rally",
        "use_expiry_thursday",
        "monday_max_gap",
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
        self.bar_aggregator = BarAggregator()

        self.composer = SignalComposer(
            signal_engine=self.signal_engine,
            long_dows=tuple(int(v) for v in params.get("long_dows", (1, 2))),
            use_month_start=bool(params.get("use_month_start", True)),
            use_preholiday=bool(params.get("use_preholiday", True)),
            use_monday_short=bool(params.get("use_monday_short", True)),
            use_post_expiry_monday_short=bool(params.get("use_post_expiry_monday_short", True)),
            post_exp_monday_min_basis_bps=float(params.get("post_exp_monday_min_basis_bps", -15.0)),
            use_post_expiry_friday_veto=bool(params.get("use_post_expiry_friday_veto", True)),
            use_december_rally=bool(params.get("use_december_rally", True)),
            use_expiry_thursday=bool(params.get("use_expiry_thursday", True)),
            monday_max_gap_pct=float(params.get("monday_max_gap_pct", params.get("monday_max_gap", 0.0))),
            use_fomo_gatekeeper=bool(params.get("use_fomo_gatekeeper", True)),
            use_t2_momentum=bool(params.get("use_t2_momentum", True)),
        )

        saved = self.state_store.get("hybrid_runtime", {})
        self.composer.load_state(saved, self.symbol)

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
                int(saved.get("t2_state")) if saved.get("t2_state") in (-1, 0, 1) else None
            ),
            persisted_last_t2_bar=(
                str(saved.get("last_t2_bar")) if saved.get("last_t2_bar") else None
            ),
        )
        LOGGER.info("HybridGated loaded %d warmup bars from %s", loaded, source)

        self._account_refresh_s = float(
            params.get(
                "account_refresh_s",
                os.getenv("ACCOUNT_SNAPSHOT_REFRESH_S", "30"),
            )
        )
        if not 10 <= self._account_refresh_s <= 300:
            raise ValueError("ACCOUNT_SNAPSHOT_REFRESH_S must be in [10, 300]")
        self._account_exporter = None
        if account_reader is not None:
            self._account_exporter = AccountSnapshotExporter(
                account_reader=account_reader,
                output_path=account_snapshot_path or Path("/app/runtime/account.json"),
            )

    @property
    def symbol(self) -> str:
        return self.config.instruments[0]

    @property
    def target_qty(self) -> int:
        return self.config.qty_for(self.symbol)

    # State properties for backward-compatibility with tests & internals
    @property
    def _calendar_target(self) -> int:
        return self.composer.calendar_target

    @_calendar_target.setter
    def _calendar_target(self, val: int) -> None:
        self.composer.calendar_target = val

    @property
    def _calendar_hard_flat(self) -> bool:
        return self.composer.calendar_hard_flat

    @_calendar_hard_flat.setter
    def _calendar_hard_flat(self, val: bool) -> None:
        self.composer.calendar_hard_flat = val

    @property
    def _calendar_reasons(self) -> Tuple[str, ...]:
        return self.composer.calendar_reasons

    @_calendar_reasons.setter
    def _calendar_reasons(self, val: Tuple[str, ...]) -> None:
        self.composer.calendar_reasons = val

    @property
    def _effective_day(self) -> Optional[date]:
        return self.composer.effective_day

    @_effective_day.setter
    def _effective_day(self, val: Optional[date]) -> None:
        self.composer.effective_day = val

    @property
    def _blocked_execution_day(self) -> Optional[date]:
        return self.composer.blocked_execution_day

    @_blocked_execution_day.setter
    def _blocked_execution_day(self, val: Optional[date]) -> None:
        self.composer.blocked_execution_day = val

    @property
    def _last_morning_decision_day(self) -> Optional[date]:
        return self.composer.last_morning_decision_day

    @_last_morning_decision_day.setter
    def _last_morning_decision_day(self, val: Optional[date]) -> None:
        self.composer.last_morning_decision_day = val

    @property
    def _last_afternoon_decision_day(self) -> Optional[date]:
        return self.composer.last_afternoon_decision_day

    @_last_afternoon_decision_day.setter
    def _last_afternoon_decision_day(self, val: Optional[date]) -> None:
        self.composer.last_afternoon_decision_day = val

    @property
    def _bar_open(self) -> Optional[float]:
        return self.bar_aggregator.bar_open

    @property
    def _bar_transition_pending(self) -> bool:
        return self.bar_aggregator.bar_transition_pending

    @_bar_transition_pending.setter
    def _bar_transition_pending(self, val: bool) -> None:
        self.bar_aggregator.bar_transition_pending = val

    @property
    def _current_bar_start(self) -> Optional[datetime]:
        return self.bar_aggregator.current_bar_start

    @_current_bar_start.setter
    def _current_bar_start(self, val: Optional[datetime]) -> None:
        self.bar_aggregator.current_bar_start = val

    @property
    def _current_bar_first_quote(self) -> Optional[datetime]:
        return self.bar_aggregator.current_bar_first_quote

    @_current_bar_first_quote.setter
    def _current_bar_first_quote(self, val: Optional[datetime]) -> None:
        self.bar_aggregator.current_bar_first_quote = val

    def _start_bar(self, bucket_start: datetime, price: float, observed_at: datetime) -> None:
        self.bar_aggregator.start_bar(bucket_start, price, observed_at)

    def _current_bar_snapshot(self) -> Optional[Bar30m]:
        return self.bar_aggregator.current_bar_snapshot()

    def _update_live_bar(self, price: float, local_now: datetime) -> bool:
        completed = self.bar_aggregator.update(price, local_now)
        if completed is not None and self.signal_engine.add_completed_bar(completed):
            self.signal_engine.save_file(self._warmup_path)
            self._compose_desired()
            self._persist_runtime()
            LOGGER.info("hybrid_closed_bar at=%s close=%.2f", completed.datetime, completed.close)
            return True
        return False

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

    def _compose_desired(self) -> None:
        now = getattr(self, "_evaluation_now", None) or datetime.now(HCM_TZ)
        units, reasons = self.composer.compose_desired(
            now=now,
        )
        self._desired_units = units
        self._desired_qty = units * self.target_qty
        self._signal_day = self._effective_day.isoformat() if self._effective_day else None
        self._reasons = reasons

    def _persist_runtime(self) -> None:
        state = self.composer.dump_state(self.symbol)
        state["updated_at"] = time.time()
        self.state_store.set("hybrid_runtime", state)
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

        ref_price = getattr(quote, "reference_price", getattr(quote, "ref_price", None))
        quote_open = getattr(quote, "open_price", None)
        live_basis_fn = getattr(self, "_live_basis", None)
        spot_price = getattr(self, "_latest_spot_price", None)

        with self._snapshot_lock:
            latest_price = getattr(self, "_latest_price", None)
            self.composer.bootstrap_calendar_day(
                local_now,
                ref_price=ref_price,
                bar_open=self._bar_open,
                quote_open=quote_open,
                live_basis_fn=live_basis_fn,
                spot_price=spot_price,
                current_price=latest_price,
            )
            if in_morning_decision_window(local_now):
                self.composer.apply_morning_decision(
                    local_now,
                    ref_price=ref_price,
                    bar_open=self._bar_open,
                    quote_open=quote_open,
                    live_basis_fn=live_basis_fn,
                    spot_price=spot_price,
                    current_price=latest_price,
                )
            if in_afternoon_decision_window(local_now):
                self.composer.apply_afternoon_decision(
                    local_now,
                    aggregator=self.bar_aggregator,
                    symbol=self.symbol,
                )
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
        return normalize_symbol(raw)

    def fetch_positions(self) -> Dict[str, int]:
        with self._portfolio_lock:
            payload = self.client.get_portfolio_by_sub()
        if not isinstance(payload, dict) or not payload.get("success"):
            raise RuntimeError("REST portfolio query failed")
        snapshot = reconcile_account(
            payload.get("items"), [], managed_symbols=(self.symbol,)
        )
        if snapshot.malformed_positions:
            raise RuntimeError("REST portfolio contains malformed positions")
        positions = dict(snapshot.positions)
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
                    raise RuntimeError(f"Cannot settle recovered order {cl_ord_id}: status={status}")
            self.client.cleanup_order(cl_ord_id)

    def _assert_no_remote_working_orders(self) -> None:
        get_orders = getattr(self.client, "get_orders", None)
        if get_orders is None:
            raise RuntimeError("REST get_orders is unavailable")
        today = datetime.now(HCM_TZ).date()
        payload = get_orders((today - timedelta(days=1)).isoformat(), today.isoformat())
        if not isinstance(payload, dict) or not payload.get("success"):
            raise RuntimeError("REST order reconciliation failed")
        snapshot = reconcile_account([], payload.get("items"), managed_symbols=(self.symbol,))
        if snapshot.malformed_orders:
            raise RuntimeError("REST order reconciliation returned malformed orders")
        active = [
            self._normalise_symbol(item.get("symbol") or item.get("instrument")) or "unknown"
            for item in snapshot.working_orders
        ]
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

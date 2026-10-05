"""Long-running, fail-closed PaperTrade service for the calendar alpha."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from paperbroker.alpha import AlphaConfig, AlphaContext, OrderRequest, Signal
from paperbroker.market_data import KafkaMarketDataClient

from algotrade_adapter.client import build_client
from algotrade_adapter.account_snapshot import AccountSnapshotExporter
from algotrade_adapter.safe_alpha import SafeSignalDrivenAlpha

from .schedule import (
    HCM_TZ,
    HOLIDAY_COVERED_TO,
    decision_target,
    front_month_symbol,
    in_decision_window,
    in_monday_decision_window,
    monday_short_target,
    market_is_open,
    next_decision_plan,
)

LOGGER = logging.getLogger(__name__)
MAX_CALENDAR_QTY = 10
_TERMINAL_ORDER_STATES = {
    "Canceled", "Filled", "Rejected", "Expired", "DoneForDay",
    "CANCELED", "FILLED", "REJECTED", "EXPIRED", "DONE_FOR_DAY",
}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}], got {value}")
    return value


def _calendar_qty() -> int:
    """Load position size while retaining a hard production risk ceiling."""
    return _env_int(
        "CALENDAR_QTY",
        1,
        minimum=1,
        maximum=MAX_CALENDAR_QTY,
    )


class CalendarPaperAlpha(SafeSignalDrivenAlpha):
    """One-contract executor. CalendarSupervisor owns contract rotation."""

    trigger_on_bar = False
    trigger_on_quote = True
    declared_params = {"cancel_after_s", "cross_points", "eval_interval_s", "monday_max_gap"}

    def __init__(
        self,
        *,
        client,
        market_data,
        config: AlphaConfig,
        account_reader=None,
        account_snapshot_path: Optional[Path] = None,
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
        self._desired_qty: Optional[int] = None
        self._signal_day: Optional[str] = None
        self._reasons: tuple[str, ...] = ()
        self._last_error: Optional[str] = None
        self._started_epoch = time.time()
        self._account_refresh_s = float(os.getenv("ACCOUNT_SNAPSHOT_REFRESH_S", "30"))
        if not 10 <= self._account_refresh_s <= 300:
            raise ValueError("ACCOUNT_SNAPSHOT_REFRESH_S must be in [10, 300]")
        self._account_exporter = None
        if account_reader is not None:
            self._account_exporter = AccountSnapshotExporter(
                account_reader,
                account_snapshot_path or Path("/app/runtime/account.json"),
            )

    @property
    def symbol(self) -> str:
        return self.config.instruments[0]

    @property
    def target_qty(self) -> int:
        return self.config.qty_for(self.symbol)

    def should_evaluate_on_quote(self, instrument: str, quote: Any) -> bool:
        now_epoch = time.time()
        latest_price = getattr(quote, "latest_matched_price", None)
        with self._snapshot_lock:
            self._last_quote_epoch = now_epoch
            if latest_price is not None:
                self._latest_price = float(latest_price)
        local_now = datetime.now(HCM_TZ)
        if not (in_decision_window(local_now) or in_monday_decision_window(local_now)):
            return False
        interval = float(self.config.params.get("eval_interval_s", 2.0))
        now_mono = time.monotonic()
        if now_mono - self._last_eval_monotonic < interval:
            return False
        self._last_eval_monotonic = now_mono
        return True

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        local_now = ctx.now.astimezone(HCM_TZ)
        if in_monday_decision_window(local_now):
            quote = ctx.quotes.get(self.symbol)
            ref_price = getattr(quote, "reference_price", None)
            open_price = getattr(quote, "open_price", None) or getattr(quote, "latest_matched_price", None)
            if ref_price is not None and open_price is not None:
                gap = float(open_price) - float(ref_price)
                max_gap = float(self.config.params.get("monday_max_gap", 0.0))
                short_unit = monday_short_target(gap, monday_max_gap=max_gap)
                desired_units = short_unit
                reasons = ("monday_short",) if short_unit == -1 else ("monday_flat_gap",)
            else:
                desired_units = 0
                reasons = ("monday_missing_quote",)
            signal_day = local_now.date()
        elif in_decision_window(local_now):
            desired_units, signal_day, reasons = decision_target(local_now, self.symbol)
        else:
            desired_units = 0
            signal_day = local_now.date()
            reasons = ()

        positions = self.fetch_positions()
        desired_qty = desired_units * self.target_qty
        with self._snapshot_lock:
            self._desired_qty = desired_qty
            self._signal_day = signal_day.isoformat()
            self._reasons = reasons
            self._last_error = None
        return {
            "local_now": local_now,
            "desired_qty": desired_qty,
            "positions": positions,
            "signal_day": signal_day,
            "reasons": reasons,
        }

    def get_signals(self, indicators: Dict[str, Any], ctx: AlphaContext) -> list[Signal]:
        local_now = indicators["local_now"]
        if not (in_decision_window(local_now) or in_monday_decision_window(local_now)):
            return []

        working = ctx.open_orders.get(self.symbol, [])
        if working:
            oldest = min(order.placed_at for order in working)
            age = (ctx.now - oldest).total_seconds()
            if age >= float(self.config.params.get("cancel_after_s", 8.0)):
                for order in working:
                    terminal, status = self.client.cancel_order(order.cl_ord_id, timeout=3.0)
                    self.logger.warning(
                        "calendar_cancel_stale cl_ord_id=%s terminal=%s status=%s",
                        order.cl_ord_id, terminal, status,
                    )
            return []

        positions: Dict[str, int] = indicators["positions"]
        foreign = {symbol: qty for symbol, qty in positions.items() if symbol != self.symbol and qty != 0}
        if foreign:
            return self._risk_block(f"foreign positions present: {sorted(foreign)}")

        actual = int(positions.get(self.symbol, 0))
        desired = int(indicators["desired_qty"])
        if actual < -self.target_qty or actual > self.target_qty:
            return self._risk_block(
                f"unexpected {self.symbol} position actual={actual} target_range=[{-self.target_qty},{self.target_qty}]"
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
                        f"position drift local={tracked.quantity} remote={actual}; waiting for REST convergence"
                    )
            else:
                return self._risk_block(
                    f"position drift local={tracked.quantity} remote={actual}; waiting for REST convergence"
                )

        delta = desired - actual
        if delta == 0:
            self.state_store.set("last_converged", {
                "at": ctx.now.isoformat(),
                "symbol": self.symbol,
                "quantity": actual,
                "signal_day": indicators["signal_day"].isoformat(),
            })
            self.state_store.flush()
            return []

        decision = {
            "at": ctx.now.isoformat(),
            "symbol": self.symbol,
            "actual": actual,
            "desired": desired,
            "signal_day": indicators["signal_day"].isoformat(),
            "reasons": list(indicators["reasons"]),
        }
        if not self.client.allow_orders:
            self.state_store.set("last_shadow_decision", decision)
            self.state_store.flush()
            self.logger.info("calendar_shadow_decision %s", decision)
            return []

        side = "BUY" if delta > 0 else "SELL"
        self.state_store.set("last_submit_intent", {**decision, "side": side, "qty": abs(delta)})
        self.state_store.flush()
        return [Signal(
            symbol=self.symbol,
            side=side,
            tag="calendar_" + "_".join(indicators["reasons"] or ("flat",)),
            metadata={"qty": abs(delta), "signal_day": indicators["signal_day"].isoformat()},
        )]

    def _risk_block(self, message: str) -> list[Signal]:
        with self._snapshot_lock:
            self._last_error = message
        self.logger.error("calendar_risk_block %s", message)
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
        return [OrderRequest(
            symbol=self.symbol,
            side=signal.side,
            qty=qty,
            price=price,
            ord_type="LIMIT",
            tag=signal.tag,
        )]

    def fetch_positions(self) -> Dict[str, int]:
        with self._portfolio_lock:
            response = self.client.get_portfolio_by_sub()
        if not isinstance(response, dict) or not response.get("success"):
            raise RuntimeError("REST portfolio query failed")
        positions: Dict[str, int] = {}
        for item in response.get("items", []):
            symbol = str(item.get("instrument", "")).strip()
            if not symbol:
                continue
            quantity = int(float(item.get("quantity", 0) or 0))
            if quantity:
                positions[symbol] = quantity
        with self._snapshot_lock:
            self._remote_positions = positions
            self._last_portfolio_epoch = time.time()
        return dict(positions)

    def _recover_orders(self) -> None:
        active = self.client.recover_pending_orders()
        for row in active:
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

    async def start(self) -> None:
        self.client.connect()
        if not self.client.wait_until_logged_on(timeout=15.0):
            raise RuntimeError(f"FIX logon failed: {self.client.last_logon_error()}")
        self._recover_orders()
        positions = self.fetch_positions()
        foreign = {symbol: qty for symbol, qty in positions.items() if symbol != self.symbol and qty != 0}
        if foreign:
            raise RuntimeError(f"Refusing startup with foreign positions: {sorted(foreign)}")
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
                    if self._account_exporter is not None and now_mono >= next_account_refresh:
                        try:
                            await asyncio.to_thread(self._export_account_snapshot)
                        except Exception as exc:
                            self.logger.warning(
                                "account_snapshot_failed error_type=%s",
                                type(exc).__name__,
                            )
                        next_account_refresh = now_mono + self._account_refresh_s
                    await asyncio.sleep(0.5)
            finally:
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
        with self._snapshot_lock:
            feed_age = None if self._last_quote_epoch is None else now_epoch - self._last_quote_epoch
            portfolio_age = None if self._last_portfolio_epoch is None else now_epoch - self._last_portfolio_epoch
            snapshot = {
                "symbol": self.symbol,
                "fix_logged_on": bool(self.client.is_logged_on()),
                "feed_age_s": None if feed_age is None else round(feed_age, 1),
                "portfolio_age_s": None if portfolio_age is None else round(portfolio_age, 1),
                "positions": dict(self._remote_positions),
                "desired_qty": self._desired_qty,
                "signal_day": self._signal_day,
                "reasons": list(self._reasons),
                "order_gate": bool(self.client.allow_orders),
                "last_error": self._last_error,
                "uptime_s": round(now_epoch - self._started_epoch, 1),
            }
        local_now = datetime.now(HCM_TZ)
        decision_at, target_units, signal_day, reasons = next_decision_plan(
            local_now,
            self.symbol,
        )
        snapshot.update({
            "configured_qty": self.target_qty,
            "next_decision_at": decision_at.isoformat(),
            "next_signal_day": signal_day.isoformat(),
            "next_target_qty": target_units * self.target_qty,
            "next_reasons": list(reasons),
        })
        grace_elapsed = now_epoch - self._started_epoch > 90
        feed_stale = market_is_open(local_now) and grace_elapsed and (
            feed_age is None or feed_age > 120
        )
        snapshot["healthy"] = snapshot["fix_logged_on"] and not feed_stale
        return snapshot


class CalendarSupervisor:
    """Restart the single-contract alpha when VN30 front month changes."""

    def __init__(self) -> None:
        self._stop_requested = threading.Event()
        self._child_lock = threading.RLock()
        self._child: Optional[CalendarPaperAlpha] = None
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

    def _build_child(self, symbol: str) -> CalendarPaperAlpha:
        if datetime.now(HCM_TZ).date() > HOLIDAY_COVERED_TO:
            raise RuntimeError("Holiday calendar expired; update it before trading")
        qty = _calendar_qty()
        client = build_client(enable_fix=True)
        account_reader = build_client(
            enable_fix=False,
            order_store_path=Path("runtime/dashboard_orders.db"),
            allow_orders=False,
        )
        market_data = KafkaMarketDataClient(
            bootstrap_servers=os.environ["PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS"],
            username=os.environ["PAPERBROKER_KAFKA_USERNAME"],
            password=os.environ["PAPERBROKER_KAFKA_PASSWORD"],
            env_id=os.environ["PAPERBROKER_ENV_ID"],
            auto_offset_reset="latest",
            merge_updates=True,
        )
        config = AlphaConfig.single(
            instrument=symbol,
            sub_account=os.environ["PAPER_ACCOUNT_ID"],
            timeframe="30m",
            qty=qty,
            params={
                "cancel_after_s": float(os.getenv("CALENDAR_CANCEL_AFTER_S", "8")),
                "cross_points": float(os.getenv("CALENDAR_CROSS_POINTS", "0.1")),
                "eval_interval_s": float(os.getenv("CALENDAR_EVAL_INTERVAL_S", "2")),
            },
            state_path=f"state/calendar_{symbol.replace(':', '_')}.json",
            log_dir="logs",
        )
        return CalendarPaperAlpha(
            client=client,
            market_data=market_data,
            config=config,
            account_reader=account_reader,
            account_snapshot_path=Path("/app/runtime/account.json"),
        )

    def _start_child(self, symbol: str) -> None:
        child = self._build_child(symbol)
        self._child_error = None

        def target() -> None:
            try:
                child.run()
            except BaseException as exc:
                self._child_error = exc

        thread = threading.Thread(target=target, name=f"calendar.{symbol}", daemon=True)
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
                raise RuntimeError("Calendar alpha did not stop within 20 seconds")
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
                    raise RuntimeError("Calendar child is missing")
                if not thread.is_alive():
                    if self._child_error is not None:
                        raise RuntimeError("Calendar child failed") from self._child_error
                    raise RuntimeError("Calendar child stopped unexpectedly")
                health = child.health_snapshot()
                if not health.get("healthy", False) and float(health.get("uptime_s", 0)) > 30:
                    raise RuntimeError(f"Calendar child unhealthy: {health.get('last_error')}")
                resolved = self._resolved_symbol()
                if resolved != child.symbol:
                    old_positions = child.fetch_positions()
                    if old_positions.get(child.symbol, 0) != 0:
                        raise RuntimeError(
                            f"Rollover blocked: {child.symbol} position is not flat"
                        )
                    LOGGER.info("calendar_rollover old=%s new=%s", child.symbol, resolved)
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
            return {"healthy": False, "alpha": "calendar", "reason": "starting"}
        snapshot = child.health_snapshot()
        snapshot["alpha"] = "calendar"
        snapshot["worker_alive"] = bool(thread and thread.is_alive())
        return snapshot


def build_calendar_service() -> CalendarSupervisor:
    """Factory used by ``ALPHA_FACTORY`` inside the container."""
    return CalendarSupervisor()

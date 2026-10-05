"""Process supervision and contract rollover for the Hybrid alpha."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from paperbroker.alpha import AlphaConfig
from algotrade_adapter.client import build_client
from algotrade_adapter.market_data import build_market_data
from runtime_core.config import MasterUnifiedRuntimeConfig, load_master_unified_config

from .alpha import HybridGatedPaperAlpha
from .schedule import HCM_TZ, HOLIDAY_COVERED_TO, front_month_symbol

LOGGER = logging.getLogger(__name__)


class HybridGatedSupervisor:
    """Run exactly one HybridGated child and rotate its VN30 contract."""

    profile = "hybrid"

    def __init__(self, runtime_config: MasterUnifiedRuntimeConfig | None = None) -> None:
        self.runtime_config = runtime_config or load_master_unified_config(self.profile)
        self._stop_requested = threading.Event()
        self._child_lock = threading.RLock()
        self._child: Optional[HybridGatedPaperAlpha] = None
        self._child_thread: Optional[threading.Thread] = None
        self._child_error: Optional[BaseException] = None

    def _resolved_symbol(self) -> str:
        return self.runtime_config.resolve_symbol(
            datetime.now(HCM_TZ), front_month_symbol
        )

    def _build_child(self, symbol: str) -> HybridGatedPaperAlpha:
        if datetime.now(HCM_TZ).date() > HOLIDAY_COVERED_TO:
            raise RuntimeError("Holiday calendar expired; update it before trading")
        runtime = self.runtime_config
        client = build_client(enable_fix=True)
        account_reader = build_client(
            enable_fix=False,
            order_store_path=runtime.paths.runtime_dir / "dashboard_orders.db",
            allow_orders=False,
        )
        market_data = build_market_data()
        params = {
            "cancel_after_s": runtime.cancel_after_s,
            "cross_points": runtime.cross_points,
            "eval_interval_s": runtime.eval_interval_s,
            "account_refresh_s": runtime.account_refresh_s,
            **runtime.strategy_params,
        }
        config = AlphaConfig.single(
            instrument=symbol,
            sub_account=os.environ["PAPER_ACCOUNT_ID"],
            timeframe="30m",
            qty=runtime.quantity,
            params=params,
            state_path=str(
                runtime.paths.state_dir / f"hybrid_gated_{symbol.replace(':', '_')}.json"
            ),
            log_dir=str(runtime.paths.log_dir),
        )
        return HybridGatedPaperAlpha(
            client=client,
            market_data=market_data,
            config=config,
            account_reader=account_reader,
            account_snapshot_path=runtime.paths.runtime_dir / "account.json",
            warmup_path=runtime.paths.runtime_dir / "hybrid_gated_warmup_bars.json",
            seed_warmup_path=runtime.paths.runtime_dir / "warmup_bars.json",
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
        snapshot["config_profile"] = self.runtime_config.profile
        snapshot["config_hash"] = self.runtime_config.fingerprint
        return snapshot


def build_hybrid_gated_service() -> HybridGatedSupervisor:
    return HybridGatedSupervisor()


def build_unified_service() -> HybridGatedSupervisor:
    """Compatibility alias for the single supported runtime profile."""
    return build_hybrid_gated_service()

"""
Example 11 — exit-by-signal patterns (v0.2.7).

Demonstrates how exit logic lives **inside ``get_signals``**, not in
separate framework infrastructure (no built-in OCO / TP / SL / EOD
plugin). Inspect ``ctx.positions`` for the current state and emit
opposite-side Signals when an exit condition triggers.

4 exit patterns combined in one alpha:
    1. Take-profit at fixed ±5 points
    2. Stop-loss at fixed -3 points
    3. Drawdown stop (peak-to-trough)
    4. Time-of-day flatten (14:44:30 Asia/Ho_Chi_Minh)

Entry is a trivial SMA crossover for demo purposes.

Run:
    python examples/11_alpha_exit_patterns.py
"""
import os
import sys
from datetime import time as dtime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

try:
    from zoneinfo import ZoneInfo
    _HCM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    from datetime import timedelta
    _HCM_TZ = timezone(timedelta(hours=7))

sys.path.insert(0, str(Path(__file__).parent.parent))

from paperbroker.alpha import (
    AlphaContext,
    CloseSignal,
    Signal,
    SignalDrivenAlpha,
    StopLossSignal,
    TakeProfitSignal,
)

load_dotenv()


class ExitPatternsAlpha(SignalDrivenAlpha):
    """SMA-crossover entry + 4 explicit exit conditions in get_signals.

    Demonstrates v0.2.7 Milestone E close-signal taxonomy:
        - ``TakeProfitSignal`` for TP exits
        - ``StopLossSignal`` for SL exits + drawdown stops
        - Plain ``CloseSignal`` for time-of-day (EOD) flatten

    Framework default for these subtypes: auto-size to
    ``abs(ctx.positions[sym].quantity)`` (full flatten) at MARKET — no
    need to specify qty/price. Tag derived from class name.

    StateStore tracks peak unrealized PnL for the drawdown stop.
    """

    declared_params = {
        "fast_period", "slow_period",
        "tp_points", "sl_points", "dd_points",
        "eod_close_local",
    }

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        sym = self.config.instruments[0]
        closes = [b.close for b in ctx.bars[sym]]
        fast = int(self.config.params.get("fast_period", 5))
        slow = int(self.config.params.get("slow_period", 20))
        if len(closes) < slow:
            return {"sma_fast": None, "sma_slow": None, "close": None}
        return {
            "sma_fast": sum(closes[-fast:]) / fast,
            "sma_slow": sum(closes[-slow:]) / slow,
            "close": closes[-1],
        }

    def get_signals(
        self, indicators: Dict[str, Any], ctx: AlphaContext,
    ) -> List[Signal]:
        sym = self.config.instruments[0]
        close = indicators.get("close")
        if close is None:
            return []

        pos = ctx.positions.get(sym)

        # ============================================================
        # Exit logic — checked BEFORE entry so we don't enter and
        # immediately exit on the same bar.
        #
        # Framework auto-sizes Close/TP/SL signals to abs(position) at
        # MARKET — we only specify symbol + side.
        # ============================================================
        if pos and abs(pos.quantity) > 1e-9:
            entry_px = pos.avg_price
            tp_points = float(self.config.params.get("tp_points", 5))
            sl_points = float(self.config.params.get("sl_points", 3))
            dd_points = float(self.config.params.get("dd_points", 4))

            # Direction-aware PnL in points
            direction = 1 if pos.quantity > 0 else -1
            pnl_points = direction * (close - entry_px)
            exit_side = "SELL" if pos.quantity > 0 else "BUY"

            # (1) Take-profit
            if pnl_points >= tp_points:
                self._reset_peak()
                return [TakeProfitSignal(symbol=sym, side=exit_side)]

            # (2) Stop-loss
            if pnl_points <= -sl_points:
                self._reset_peak()
                return [StopLossSignal(symbol=sym, side=exit_side)]

            # (3) Drawdown stop — peak-to-trough from in-memory state.
            #     Use StopLossSignal subclass with explicit tag for log
            #     attribution; framework still uses MARKET + auto-size.
            peak = self._update_and_get_peak(pnl_points)
            if peak > 0 and (peak - pnl_points) >= dd_points:
                self._reset_peak()
                return [StopLossSignal(symbol=sym, side=exit_side, tag="drawdown")]

            # (4) End-of-day flatten — plain CloseSignal (not loss-driven)
            if self._past_eod_cutoff(ctx):
                self._reset_peak()
                return [CloseSignal(symbol=sym, side=exit_side, tag="eod")]

            return []  # holding, no exit triggered

        # ============================================================
        # Entry logic — simple SMA crossover
        # ============================================================
        f = indicators.get("sma_fast")
        s = indicators.get("sma_slow")
        if f is None or s is None:
            return []
        if f > s * 1.001:  # 0.1% buffer to avoid noise
            return [Signal(sym, "BUY", tag="entry")]
        if f < s * 0.999:
            return [Signal(sym, "SELL", tag="entry")]
        return []

    def get_entry_price(
        self, signal: Signal, ctx: AlphaContext,
    ) -> Optional[float]:
        bars = ctx.bars[signal.symbol]
        return bars[-1].close if bars else None

    def get_quantity(self, signal: Signal, ctx: AlphaContext) -> int:
        return self.config.qty_for(signal.symbol)

    # -------- helpers (in-memory; for cross-restart use state_store) --------
    _peak_pnl: float = 0.0

    def _update_and_get_peak(self, pnl_points: float) -> float:
        if pnl_points > self._peak_pnl:
            self._peak_pnl = pnl_points
        return self._peak_pnl

    def _reset_peak(self) -> None:
        self._peak_pnl = 0.0

    def _past_eod_cutoff(self, ctx: AlphaContext) -> bool:
        cutoff_str = self.config.params.get("eod_close_local", "14:44:30")
        parts = [int(p) for p in str(cutoff_str).split(":")]
        while len(parts) < 3:
            parts.append(0)
        cutoff = dtime(parts[0], parts[1], parts[2])
        local = ctx.now.astimezone(_HCM_TZ).time()
        return local >= cutoff


def main() -> int:
    instrument = os.getenv("VN30F1M", "HNXDS:VN30F2605")
    sub_account = os.getenv("PAPER_ACCOUNT_ID", "main")

    alpha = ExitPatternsAlpha.from_paper(
        instrument=instrument,
        sub_account=sub_account,
        timeframe="1m",
        qty=1,
        params={
            "fast_period": 5,
            "slow_period": 20,
            "tp_points": 5,
            "sl_points": 3,
            "dd_points": 4,
            "eod_close_local": "14:44:30",
        },
    )
    print(f"Exit-patterns demo — {instrument} on {sub_account}")
    try:
        alpha.run()
    except KeyboardInterrupt:
        alpha.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Example 10 — Bollinger-band mean-reversion alpha (v0.2.7).

Demonstrates:
    - Subclassing SignalDrivenAlpha (multi-instrument-capable but N=1 here)
    - Pure-Python Bollinger Bands (SMA ± Nσ)
    - Persisting last-fired signal via StateStore so the alpha won't
      re-enter on the same band touch after a restart
    - Exit logic in-signal: close when price returns to middle band

Run:
    python examples/10_alpha_bollinger_bands.py
"""
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from paperbroker.alpha import (
    AlphaContext,
    Signal,
    SignalDrivenAlpha,
)

load_dotenv()


def _bollinger(
    closes: List[float], period: int, k: float,
) -> Optional[Tuple[float, float, float]]:
    """Return (lower, mid, upper) for the LAST point, or None."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    sd = math.sqrt(var)
    return mid - k * sd, mid, mid + k * sd


class BBAlpha(SignalDrivenAlpha):
    """Mean-reversion: BUY on lower band touch, SELL on upper band touch.
    Exit when price returns to mid band."""

    declared_params = {"bb_period", "bb_sigma"}

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        sym = self.config.instruments[0]
        closes = [b.close for b in ctx.bars[sym]]
        period = int(self.config.params.get("bb_period", 20))
        k = float(self.config.params.get("bb_sigma", 2.0))
        bb = _bollinger(closes, period, k)
        return {
            "close": closes[-1] if closes else None,
            "bb": bb,
        }

    def get_signals(
        self, indicators: Dict[str, Any], ctx: AlphaContext,
    ) -> List[Signal]:
        sym = self.config.instruments[0]
        bb = indicators.get("bb")
        close = indicators.get("close")
        if bb is None or close is None:
            return []
        lower, mid, upper = bb

        # ----- Exit logic: position returns to mid band -----
        pos = ctx.positions.get(sym)
        if pos and abs(pos.quantity) > 1e-9:
            if pos.quantity > 0 and close >= mid:
                return [Signal(sym, "SELL", tag="exit_long")]
            if pos.quantity < 0 and close <= mid:
                return [Signal(sym, "BUY", tag="exit_short")]
            return []

        # ----- Entry logic with sticky-lock to avoid re-entry on same touch -----
        last_signal = (
            self._state_store.get("last_signal") if self._state_store else None
        )
        if close <= lower and last_signal != "BUY":
            if self._state_store:
                self._state_store.set("last_signal", "BUY")
            return [Signal(sym, "BUY", tag="entry")]
        if close >= upper and last_signal != "SELL":
            if self._state_store:
                self._state_store.set("last_signal", "SELL")
            return [Signal(sym, "SELL", tag="entry")]
        # Within bands — clear sticky lock so next touch fires.
        if lower < close < upper and self._state_store:
            self._state_store.set("last_signal", None)
        return []

    def get_entry_price(
        self, signal: Signal, ctx: AlphaContext,
    ) -> Optional[float]:
        bars = ctx.bars[signal.symbol]
        return bars[-1].close if bars else None

    def get_quantity(self, signal: Signal, ctx: AlphaContext) -> int:
        return self.config.qty_for(signal.symbol)


def main() -> int:
    instrument = os.getenv("VN30F1M", "HNXDS:VN30F2605")
    sub_account = os.getenv("PAPER_ACCOUNT_ID", "main")

    alpha = BBAlpha.from_paper(
        instrument=instrument,
        sub_account=sub_account,
        timeframe="1m",
        qty=1,
        params={"bb_period": 20, "bb_sigma": 2.0},
        state_path="state/bb.json",
    )
    print(f"BB alpha — {instrument} on {sub_account}")
    try:
        alpha.run()
    except KeyboardInterrupt:
        alpha.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

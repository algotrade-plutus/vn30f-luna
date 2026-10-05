"""
Example 12 — pair-trade spread alpha (v0.2.7 multi-instrument).

Trades the spread between two derivatives (e.g. VN30F1M vs VN30F2M):
    - Subscribe both instruments via ``instruments=[F1M, F2M]``
    - Joint trigger fires when EITHER instrument's bar closes (debounced
      by ``bar_window_ms``) — ``get_signals`` is called with the full
      context once per burst.
    - When the rolling-window z-score of the spread is extreme, enter
      both legs atomically (one BUY + one SELL).
    - Exit when z-score reverts toward zero.

This is the pair-trade pattern v0.2.7 was designed around. ``get_signals``
returns a **list of Signals** — multi-leg atomic entry.

Run:
    python examples/12_alpha_pair_spread.py
"""
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from paperbroker.alpha import (
    AlphaContext,
    Signal,
    SignalDrivenAlpha,
)

load_dotenv()


def _rolling_z(spreads: List[float], window: int) -> Optional[float]:
    """Z-score of the latest spread vs trailing window."""
    if len(spreads) < window + 1:
        return None
    history = spreads[-window - 1:-1]  # exclude latest
    mean = sum(history) / window
    var = sum((x - mean) ** 2 for x in history) / window
    sd = math.sqrt(var)
    if sd < 1e-9:
        return None
    return (spreads[-1] - mean) / sd


class SpreadPairAlpha(SignalDrivenAlpha):
    """Z-score spread alpha on two correlated instruments.

    On extreme positive z (sym_a expensive vs sym_b): short A, long B.
    On extreme negative z: long A, short B.
    Exit when |z| crosses back below ``exit_z``.
    """

    declared_params = {"window", "entry_z", "exit_z"}

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        a, b = self.config.instruments[0], self.config.instruments[1]
        bars_a = ctx.bars[a]
        bars_b = ctx.bars[b]
        if not bars_a or not bars_b:
            return {"z": None, "a": a, "b": b}
        # Align on the shorter history.
        n = min(len(bars_a), len(bars_b))
        spreads = [bars_a[-i].close - bars_b[-i].close for i in range(n, 0, -1)]
        window = int(self.config.params.get("window", 20))
        z = _rolling_z(spreads, window)
        return {"z": z, "a": a, "b": b}

    def get_signals(
        self, indicators: Dict[str, Any], ctx: AlphaContext,
    ) -> List[Signal]:
        z = indicators.get("z")
        a = indicators["a"]
        b = indicators["b"]
        if z is None:
            return []

        entry_z = float(self.config.params.get("entry_z", 2.0))
        exit_z = float(self.config.params.get("exit_z", 0.5))

        pos_a = ctx.positions.get(a)
        pos_b = ctx.positions.get(b)
        has_position = (
            (pos_a and abs(pos_a.quantity) > 1e-9)
            or (pos_b and abs(pos_b.quantity) > 1e-9)
        )

        # ----- Exit: z reverts toward zero -----
        if has_position and abs(z) <= exit_z:
            signals = []
            if pos_a and abs(pos_a.quantity) > 1e-9:
                side = "SELL" if pos_a.quantity > 0 else "BUY"
                signals.append(Signal(a, side, tag="exit"))
            if pos_b and abs(pos_b.quantity) > 1e-9:
                side = "SELL" if pos_b.quantity > 0 else "BUY"
                signals.append(Signal(b, side, tag="exit"))
            return signals

        # ----- Entry: extreme z, no position -----
        if has_position:
            return []
        if z > entry_z:
            # spread too high → short A, long B
            return [
                Signal(a, "SELL", tag="entry_short_spread"),
                Signal(b, "BUY", tag="entry_short_spread"),
            ]
        if z < -entry_z:
            # spread too low → long A, short B
            return [
                Signal(a, "BUY", tag="entry_long_spread"),
                Signal(b, "SELL", tag="entry_long_spread"),
            ]
        return []

    def get_entry_price(
        self, signal: Signal, ctx: AlphaContext,
    ) -> Optional[float]:
        bars = ctx.bars[signal.symbol]
        return bars[-1].close if bars else None

    def get_quantity(self, signal: Signal, ctx: AlphaContext) -> int:
        return self.config.qty_for(signal.symbol)


def main() -> int:
    f1m = os.getenv("VN30F1M", "HNXDS:VN30F2605")
    f2m = os.getenv("VN30F2M", "HNXDS:VN30F2606")
    sub_account = os.getenv("PAPER_ACCOUNT_ID", "main")

    alpha = SpreadPairAlpha.from_paper(
        instruments=[f1m, f2m],
        sub_account=sub_account,
        timeframe="1m",
        qty={f1m: 1, f2m: 1},
        params={"window": 20, "entry_z": 2.0, "exit_z": 0.5},
        state_path="state/pair_spread.json",
    )
    print("=" * 70)
    print(f"  Pair-spread alpha — {f1m} vs {f2m} on {sub_account}")
    print("=" * 70)
    try:
        alpha.run()
    except KeyboardInterrupt:
        alpha.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

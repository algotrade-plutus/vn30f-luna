"""
Example 14 — iceberg-slicing execution (v0.2.7).

One Signal → N OrderRequests via ``plan_orders`` override. Splits a
large order into smaller leg orders to avoid signaling size to the
order book. Each slice is placed at a slightly different limit price
to capture an inside-spread fill.

Demonstrates:
    - Subclass overriding ``plan_orders`` for non-1:1 execution
    - All legs share the same ``parent_signal_id`` (auto-assigned by
      framework) for downstream attribution
    - Multi-leg auto-OCO is disabled by design (framework warns); alphas
      that need aggregate exit semantics manage them in ``get_signals``

Run:
    python examples/14_alpha_iceberg.py
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from paperbroker.alpha import (
    AlphaContext,
    OrderRequest,
    Signal,
    SignalDrivenAlpha,
)

load_dotenv()


class IcebergAlpha(SignalDrivenAlpha):
    """Simple SMA-crossover entry, executed via iceberg slicing.

    Slices an order of ``total_qty`` into ``slice_count`` legs at price
    levels ``[bar.close - i * step]`` (or ``+`` for SELL). When the
    deepest slice hits the book it captures a meaningful improvement on
    the average fill price.
    """

    declared_params = {
        "fast_period", "slow_period",
        "total_qty", "slice_count", "price_step",
    }

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        sym = self.config.instruments[0]
        closes = [b.close for b in ctx.bars[sym]]
        fast = int(self.config.params.get("fast_period", 5))
        slow = int(self.config.params.get("slow_period", 20))
        if len(closes) < slow:
            return {"signal": None}
        sma_fast = sum(closes[-fast:]) / fast
        sma_slow = sum(closes[-slow:]) / slow
        return {"signal": "BUY" if sma_fast > sma_slow else "SELL"}

    def get_signals(
        self, indicators: Dict[str, Any], ctx: AlphaContext,
    ) -> List[Signal]:
        sym = self.config.instruments[0]
        signal = indicators.get("signal")
        if signal is None:
            return []
        pos = ctx.positions.get(sym)
        # Skip if already long for BUY signal, or short for SELL signal.
        if pos and abs(pos.quantity) > 1e-9:
            if (signal == "BUY" and pos.quantity > 0) or (
                signal == "SELL" and pos.quantity < 0
            ):
                return []
        return [Signal(sym, signal, tag="iceberg_entry")]

    def plan_orders(
        self, signal: Signal, ctx: AlphaContext,
    ) -> List[OrderRequest]:
        """Slice signal.symbol into N limit legs at staggered prices."""
        bars = ctx.bars.get(signal.symbol, [])
        if not bars:
            return []
        base_price = bars[-1].close

        total = int(self.config.params.get("total_qty", 30))
        n = int(self.config.params.get("slice_count", 3))
        step = float(self.config.params.get("price_step", 0.5))
        if n <= 0 or total <= 0:
            return []

        per_leg = total // n
        if per_leg == 0:
            return []
        direction = -1 if signal.side == "BUY" else 1
        orders = []
        for i in range(n):
            orders.append(
                OrderRequest(
                    symbol=signal.symbol,
                    side=signal.side,
                    qty=per_leg,
                    price=base_price + direction * step * i,
                    ord_type="LIMIT",
                    tag=f"slice_{i}_of_{n}",
                )
            )
        return orders

    def get_entry_price(self, signal, ctx):
        # Unused — plan_orders builds the orders directly.
        return None

    def get_quantity(self, signal, ctx):
        # Unused — plan_orders sets qty per leg.
        return 0


def main() -> int:
    instrument = os.getenv("VN30F1M", "HNXDS:VN30F2605")
    sub_account = os.getenv("PAPER_ACCOUNT_ID", "main")

    alpha = IcebergAlpha.from_paper(
        instrument=instrument,
        sub_account=sub_account,
        timeframe="1m",
        qty=30,  # informational only; plan_orders splits the actual orders
        params={
            "fast_period": 5,
            "slow_period": 20,
            "total_qty": 30,
            "slice_count": 3,
            "price_step": 0.5,
        },
    )
    print(f"Iceberg slicing demo — {instrument} on {sub_account}")
    try:
        alpha.run()
    except KeyboardInterrupt:
        alpha.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

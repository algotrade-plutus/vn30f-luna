"""
Example 13 — cross-asset execution: signal on X, order on Y (v0.2.7).

Demonstrates the **Signal vs OrderRequest split**: ``Signal.symbol`` is
the instrument that generated the trading idea, but the actual order
trades a different instrument. Both must be in ``config.instruments``.

Use case: use the VN30 index (data only, role="driver") to drive trades
on VN30F1M (the futures contract). The index isn't tradeable; the future
is. Strategy reasons about the index but executes on the future.

Override ``plan_orders`` to redirect the execution symbol.

Run:
    python examples/13_alpha_cross_asset.py
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


class IndexDrivenAlpha(SignalDrivenAlpha):
    """Signals fire on the index symbol; orders route to the futures.

    Strategy: short-term momentum on the index (5-bar return > 0.3% →
    BUY future; < -0.3% → SELL future). The index symbol receives only
    data feed; orders only ever touch the futures symbol.
    """

    declared_params = {
        "index_symbol",
        "execution_symbol",
        "momentum_window",
        "momentum_threshold",
    }

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        index_sym = self.config.params["index_symbol"]
        bars = ctx.bars.get(index_sym, [])
        window = int(self.config.params.get("momentum_window", 5))
        if len(bars) < window + 1:
            return {"momentum": None}
        ret = (bars[-1].close - bars[-window - 1].close) / bars[-window - 1].close
        return {"momentum": ret}

    def get_signals(
        self, indicators: Dict[str, Any], ctx: AlphaContext,
    ) -> List[Signal]:
        m = indicators.get("momentum")
        if m is None:
            return []
        index_sym = self.config.params["index_symbol"]
        threshold = float(self.config.params.get("momentum_threshold", 0.003))

        exec_sym = self.config.params["execution_symbol"]
        pos = ctx.positions.get(exec_sym)
        has_pos = pos and abs(pos.quantity) > 1e-9

        # Exit when momentum reverses
        if has_pos:
            if pos.quantity > 0 and m < 0:
                return [Signal(index_sym, "SELL", tag="exit")]
            if pos.quantity < 0 and m > 0:
                return [Signal(index_sym, "BUY", tag="exit")]
            return []

        if m > threshold:
            return [Signal(index_sym, "BUY", tag="momentum_long")]
        if m < -threshold:
            return [Signal(index_sym, "SELL", tag="momentum_short")]
        return []

    def plan_orders(
        self, signal: Signal, ctx: AlphaContext,
    ) -> List[OrderRequest]:
        """Redirect: the order trades the futures, not the index."""
        exec_sym = self.config.params["execution_symbol"]
        exec_bars = ctx.bars.get(exec_sym, [])
        if not exec_bars:
            return []
        return [
            OrderRequest(
                symbol=exec_sym,
                side=signal.side,
                qty=self.config.qty_for(exec_sym),
                price=exec_bars[-1].close,
                ord_type="LIMIT",
                tag=signal.tag,
            )
        ]

    def get_entry_price(
        self, signal: Signal, ctx: AlphaContext,
    ) -> Optional[float]:
        # Not used because plan_orders is overridden, but the abstract
        # signature still requires an implementation.
        return None

    def get_quantity(self, signal: Signal, ctx: AlphaContext) -> int:
        # Not used because plan_orders is overridden.
        return 0


def main() -> int:
    index_sym = os.getenv("VN30_INDEX", "HSX:VN30")
    exec_sym = os.getenv("VN30F1M", "HNXDS:VN30F2605")
    sub_account = os.getenv("PAPER_ACCOUNT_ID", "main")

    alpha = IndexDrivenAlpha.from_paper(
        instruments=[index_sym, exec_sym],
        sub_account=sub_account,
        timeframe="1m",
        qty={exec_sym: 1},  # only sized for the execution leg; plan_orders overrides
        params={
            "index_symbol": index_sym,
            "execution_symbol": exec_sym,
            "momentum_window": 5,
            "momentum_threshold": 0.003,
        },
    )
    print(f"Index-driven alpha — signal on {index_sym}, execute on {exec_sym}")
    try:
        alpha.run()
    except KeyboardInterrupt:
        alpha.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

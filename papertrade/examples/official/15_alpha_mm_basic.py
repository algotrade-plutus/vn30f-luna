"""
Example 15 — basic market-making alpha (v0.2.7 Milestone E).

Demonstrates the **quote-driven alpha pattern**:

- ``trigger_on_quote = True``: hook chain fires on every quote tick
  (vs bar close for signal-driven alphas)
- ``trigger_on_bar = False``: pure quote-driven; no bar collation
- ``should_evaluate_on_quote`` throttles to price-change events only
  (skip ticks where mid is unchanged)
- 2-sided quoting: emit ``[Signal(BUY, "bid"), Signal(SELL, "ask")]``
  every refresh — **framework no longer blocks per-symbol** (v0.2.7 E
  removed the implicit "one entry per symbol" gate)
- Cancel-then-place: when mid drifts > ``price_drift_ticks``, cancel
  the existing quote on that side via ``self.client.cancel_order(...)``
  and let the next evaluation place a new one
- ``ctx.open_orders[sym]`` is now a list of ``OrderState`` — alpha
  inspects per-side state to decide when to refresh

Pattern is the v0.2.7 primitive layer for Group8-style MM. v0.2.9 ships
``MarketMakingAlpha`` as a thin convenience subclass with these defaults
preconfigured + side-aware helpers.

Run:
    python examples/15_alpha_mm_basic.py
"""
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from paperbroker.alpha import (
    AlphaContext,
    OrderRequest,
    OrderState,
    Signal,
    SignalDrivenAlpha,
)

load_dotenv()


class MMBasicAlpha(SignalDrivenAlpha):
    """Minimal market-maker: quote 2-sided around mid, skip side at
    inventory cap, cancel-then-place on price drift."""

    # Quote-driven: fire on every quote tick (throttled by
    # should_evaluate_on_quote below), not on bar close.
    trigger_on_bar = False
    trigger_on_quote = True
    bar_window_ms = 100      # tight debounce — MM wants prompt response
    bar_max_wait_ms = 500

    declared_params = {
        "spread_pts",         # half-spread in price points
        "max_inventory",      # ±cap
        "min_requote_interval_s",
        "price_drift_ticks",  # cancel-replace when mid moved > N ticks
        "tick_size",
        "quote_size",         # contracts per quote
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_eval_px: Dict[str, float] = {}
        self._last_requote_ts: Dict[str, Dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Quote-trigger throttle: only re-evaluate on actual price change
    # ------------------------------------------------------------------
    def should_evaluate_on_quote(self, instrument: str, quote) -> bool:
        price = getattr(quote, "latest_matched_price", None)
        if price is None:
            return False
        last = self._last_eval_px.get(instrument)
        if last is None or price != last:
            self._last_eval_px[instrument] = price
            return True
        return False

    # ------------------------------------------------------------------
    # Hook chain
    # ------------------------------------------------------------------
    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        sym = self.config.instruments[0]
        q = ctx.quotes.get(sym)
        if q is None or q.bid_price_1 is None or q.ask_price_1 is None:
            return {"mid": None}
        mid = (q.bid_price_1 + q.ask_price_1) / 2.0
        return {"mid": mid}

    def get_signals(
        self, indicators: Dict[str, Any], ctx: AlphaContext,
    ) -> List[Signal]:
        """Quote-driven 2-sided emission.

        For each side independently:
        1. If inventory cap hit on that side → skip (don't emit)
        2. Look at ctx.open_orders[sym] for existing quote on this side
        3. If existing AND mid drifted > threshold → cancel it
           (next eval will place new quote)
        4. If no existing AND min_requote_interval elapsed → emit Signal

        Framework places each Signal as a LIMIT (via plan_orders default
        + get_entry_price returning bid/ask).
        """
        sym = self.config.instruments[0]
        mid = indicators.get("mid")
        if mid is None:
            return []

        params = self.config.params
        spread = float(params.get("spread_pts", 1.5))
        max_inv = int(params.get("max_inventory", 3))
        min_interval = float(params.get("min_requote_interval_s", 5.0))
        drift_ticks = float(params.get("price_drift_ticks", 2))
        tick = float(params.get("tick_size", 0.1))
        drift_threshold = drift_ticks * tick

        pos = ctx.positions.get(sym)
        inv = int(pos.quantity) if pos is not None else 0

        now_ts = ctx.now.timestamp()
        rec = self._last_requote_ts.setdefault(sym, {"BUY": 0.0, "SELL": 0.0})

        # Split open orders by side
        open_for_sym = ctx.open_orders.get(sym, [])
        bids = [o for o in open_for_sym if o.side == "BUY" and o.is_working]
        asks = [o for o in open_for_sym if o.side == "SELL" and o.is_working]

        signals: List[Signal] = []

        # --- BID side ---
        if inv >= max_inv:
            # Cap reached on long side — cancel any working bid
            for o in bids:
                self.client.cancel_order(o.cl_ord_id)
        else:
            target_bid = mid - spread
            if bids:
                # Cancel-then-place if mid drifted enough
                if any(abs(o.price - target_bid) > drift_threshold for o in bids):
                    for o in bids:
                        self.client.cancel_order(o.cl_ord_id)
                # Otherwise keep existing quote
            elif (now_ts - rec["BUY"]) >= min_interval:
                signals.append(Signal(sym, "BUY", tag="bid",
                                      metadata={"target_px": target_bid}))
                rec["BUY"] = now_ts

        # --- ASK side ---
        if inv <= -max_inv:
            for o in asks:
                self.client.cancel_order(o.cl_ord_id)
        else:
            target_ask = mid + spread
            if asks:
                if any(abs(o.price - target_ask) > drift_threshold for o in asks):
                    for o in asks:
                        self.client.cancel_order(o.cl_ord_id)
            elif (now_ts - rec["SELL"]) >= min_interval:
                signals.append(Signal(sym, "SELL", tag="ask",
                                      metadata={"target_px": target_ask}))
                rec["SELL"] = now_ts

        return signals

    def get_entry_price(
        self, signal: Signal, ctx: AlphaContext,
    ) -> Optional[float]:
        # Signal carries target price in metadata (set during get_signals)
        return signal.metadata.get("target_px")

    def get_quantity(self, signal: Signal, ctx: AlphaContext) -> int:
        return int(self.config.params.get("quote_size", 1))


def main() -> int:
    instrument = os.getenv("VN30F1M", "HNXDS:VN30F2606")
    sub_account = os.getenv("PAPER_ACCOUNT_ID", "main")

    # Note: MM is quote-driven — needs reliable per-tick stream. Default
    # Redis pub/sub is too sparse on back-months; use Kafka MD for
    # production-like MM (see alpha-guide.md "Market-data backend choice").
    alpha = MMBasicAlpha.from_paper(
        instruments=[instrument],
        sub_account=sub_account,
        timeframe="1m",       # unused (trigger_on_bar=False); placeholder
        qty=1,
        params={
            "spread_pts": 1.5,
            "max_inventory": 3,
            "min_requote_interval_s": 5.0,
            "price_drift_ticks": 2,
            "tick_size": 0.1,
            "quote_size": 1,
        },
    )

    print("=" * 70)
    print(f"  MM basic alpha — {instrument} on {sub_account}")
    print(f"  trigger_on_quote=True, spread=1.5pts, max_inv=±3, requote≥5s")
    print("=" * 70)
    try:
        alpha.run()
    except KeyboardInterrupt:
        alpha.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

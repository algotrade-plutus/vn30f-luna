"""
Example 09 — RSI 1-minute alpha (v0.2.7 single-instrument template).

Subclasses ``SignalDrivenAlpha`` with ~60 lines of strategy code:
    - get_indicators: rolling RSI(14) on 1m bars
    - get_signals:    BUY when RSI < 30, SELL when RSI > 70.
                      Exit via opposite-band crossing (in-signal close).
    - get_entry_price: bar close
    - get_quantity:   from config

Run:
    python examples/09_alpha_rsi_1m.py
    # or via YAML:
    pip install 'paperbroker-client[cli]'
    paperbroker run --config examples/09_alpha_rsi_1m.yaml

Notes:
    - Pure-Python RSI (no numpy/pandas dependency).
    - Exit logic is in ``get_signals`` — the framework does not provide
      built-in TP/SL/OCO. Inspect ``ctx.positions`` and emit close
      signals when your exit condition triggers.
"""
import os
import sys
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from paperbroker.alpha import (
    AlphaContext,
    Signal,
    SignalDrivenAlpha,
)

load_dotenv()


def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Wilder RSI on a list of closes. Returns None until enough history."""
    if len(closes) < period + 1:
        return None
    gains: Deque[float] = deque(maxlen=period)
    losses: Deque[float] = deque(maxlen=period)
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


class RSI1MAlpha(SignalDrivenAlpha):
    """RSI(14) mean-reversion alpha on 1-minute bars."""

    declared_params = {"rsi_period", "oversold", "overbought"}

    def get_indicators(self, ctx: AlphaContext) -> Dict[str, Any]:
        sym = self.config.instruments[0]
        closes = [b.close for b in ctx.bars[sym]]
        period = int(self.config.params.get("rsi_period", 14))
        return {"rsi": _rsi(closes, period)}

    def get_signals(
        self, indicators: Dict[str, Any], ctx: AlphaContext,
    ) -> List[Signal]:
        sym = self.config.instruments[0]
        rsi = indicators.get("rsi")
        if rsi is None:
            return []

        # ----- Exit logic (in-signal close) -----
        pos = ctx.positions.get(sym)
        if pos and abs(pos.quantity) > 1e-9:
            # Close long when RSI crosses back above mid-band (50)
            if pos.quantity > 0 and rsi > 50:
                return [Signal(sym, "SELL", tag="exit_long")]
            # Close short when RSI crosses back below mid-band
            if pos.quantity < 0 and rsi < 50:
                return [Signal(sym, "BUY", tag="exit_short")]
            return []  # holding, no exit trigger

        # ----- Entry logic -----
        oversold = float(self.config.params.get("oversold", 30))
        overbought = float(self.config.params.get("overbought", 70))
        if rsi < oversold:
            return [Signal(sym, "BUY", tag="entry")]
        if rsi > overbought:
            return [Signal(sym, "SELL", tag="entry")]
        return []

    def get_entry_price(
        self, signal: Signal, ctx: AlphaContext,
    ) -> Optional[float]:
        # Limit at last bar close — for paper backend this is
        # "marketable limit" enough to fill in normal market conditions.
        bars = ctx.bars[signal.symbol]
        return bars[-1].close if bars else None

    def get_quantity(self, signal: Signal, ctx: AlphaContext) -> int:
        return self.config.qty_for(signal.symbol)


def main() -> int:
    instrument = os.getenv("VN30F1M", "HNXDS:VN30F2605")
    sub_account = os.getenv("PAPER_ACCOUNT_ID", "main")

    alpha = RSI1MAlpha.from_paper(
        instrument=instrument,
        sub_account=sub_account,
        timeframe="1m",
        qty=1,
        params={"rsi_period": 14, "oversold": 30, "overbought": 70},
        state_path="state/rsi1m.json",
    )

    print("=" * 70)
    print(f"  RSI 1m alpha — {instrument} on {sub_account}")
    print("=" * 70)
    try:
        alpha.run()  # blocks until Ctrl-C or alpha.stop()
    except KeyboardInterrupt:
        alpha.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

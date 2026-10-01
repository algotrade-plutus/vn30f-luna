"""Domain Strategy: Luna Alpha Hypothesis and Falsification Contract.
Pure Python standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FalsificationCriteria:
    """Quantitative criteria for accepting or rejecting a strategy candidate."""
    min_sharpe_in_sample: Decimal = Decimal("1.00")
    min_sharpe_out_of_sample: Decimal = Decimal("0.50")
    max_drawdown_pct: Decimal = Decimal("25.0")
    max_peak_margin_utilisation: Decimal = Decimal("0.80")
    max_margin_calls: int = 0
    max_exchange_rejects: int = 0
    min_profit_factor: Decimal = Decimal("1.20")


@dataclass(frozen=True)
class StrategyHypothesis:
    """Formal hypothesis record for Alpha Luna."""
    strategy_id: str = "luna_v0"
    name: str = "Alpha Luna Dual-Engine (Calendar + T+2 Momentum + FOMO Gate)"
    instrument: str = "VN30F"
    timeframe: str = "30m"
    economic_premise: str = (
        "Exploits liquidity patterns from start-of-month fund flows, mid-week accumulation, "
        "and pre-holiday risk aversion on VN30 index futures, "
        "complemented by T+2 institutional momentum and protected by a FOMO overbought veto."
    )
    criteria: FalsificationCriteria = FalsificationCriteria()

"""Domain Strategy: Calibrum Alpha Hypothesis and Falsification Contract.
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
    """Formal hypothesis record for Calibrum Master Ensemble."""

    strategy_id: str = "calibrum_v1"
    name: str = "Calibrum Master Ensemble (Ridge H2 + Shinji + Calendar)"
    instrument: str = "VN30F"
    timeframe: str = "30m"
    economic_premise: str = (
        "Calibrum combines three uncorrelated 30-minute alpha engines on VN30 index futures: "
        "a regularized linear model (Ridge H2) on normalized technical price deviations, "
        "a basis spread mean-reversion engine (Shinji) between front-month futures and spot index, "
        "and institutional calendar anomaly patterns (turn-of-month, weekday, and pre-holiday)."
    )
    criteria: FalsificationCriteria = FalsificationCriteria()


"""Fail-closed PaperTrade runtime for the HybridGated alpha.

This module acts as a facade re-exporting components decomposed into:
- ``bar_aggregator``: 30m bar tracking and snapshotting
- ``signal_composer``: Calendar + T+2 + FOMO decision logic
- ``alpha``: Broker-connected HybridGated execution runtime
- ``supervisor``: Process lifecycle, contract rollover, and health reporting

The legacy ``build_unified_service`` name remains as an alias to HybridGated.
"""

from __future__ import annotations

from .alpha import (
    HybridGatedPaperAlpha,
    MAX_HYBRID_GATED_QTY,
    _REST_TERMINAL_STATES,
    _TERMINAL_ORDER_STATES,
    _as_date,
    _env_int,
    _hybrid_qty,
    _rest_order_is_terminal,
)
from .bar_aggregator import BarAggregator
from .hybrid_engine import Bar30m, HybridParameters, HybridSignalEngine
from .schedule import (
    AFTERNOON_DECISION_END,
    HCM_TZ,
    HOLIDAY_COVERED_TO,
    contract_expiry,
    core_long_reasons,
    front_month_symbol,
    in_afternoon_decision_window,
    in_morning_decision_window,
    is_expiry_session,
    is_post_expiry_friday,
    is_post_expiry_monday,
    is_regular_monday,
    market_is_open,
    next_decision_plan,
    next_trading_day,
    order_submission_allowed,
    third_thursday,
)
from .signal_composer import SignalComposer
from .supervisor import (
    HybridGatedSupervisor,
    build_hybrid_gated_service,
    build_unified_service,
)

# Compatibility aliases
MasterUnifiedPaperAlpha = HybridGatedPaperAlpha
MasterUnifiedSupervisor = HybridGatedSupervisor

__all__ = [
    "Bar30m",
    "BarAggregator",
    "HybridGatedPaperAlpha",
    "HybridGatedSupervisor",
    "HybridParameters",
    "HybridSignalEngine",
    "MasterUnifiedPaperAlpha",
    "MasterUnifiedSupervisor",
    "SignalComposer",
    "build_hybrid_gated_service",
    "build_unified_service",
]

"""Single public orchestration path for every local candidate evaluation."""
from __future__ import annotations

import pandas as pd

from .accounting import build_accounting_frame
from .aggregation import build_period_aggregates
from .config import BacktestConfig
from .metrics import calculate_metrics
from .result import BacktestResult
from .stream import validate_position_stream
from .trades import derive_trade_ledger


def evaluate(
    position_stream: pd.DataFrame,
    config: BacktestConfig = BacktestConfig(),
) -> BacktestResult:
    stream = validate_position_stream(position_stream, config)
    accounting = build_accounting_frame(stream, config)
    aggregates = build_period_aggregates(accounting)
    trades = derive_trade_ledger(accounting, config)
    metrics = calculate_metrics(accounting, aggregates, trades, config)
    return BacktestResult(config, accounting, aggregates, trades, metrics)


__all__ = ["evaluate"]

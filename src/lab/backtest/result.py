"""Typed result object returned by the local evaluator."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .aggregation import PeriodAggregates
from .config import BacktestConfig
from .metrics import BacktestMetrics


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    frame: pd.DataFrame
    aggregates: PeriodAggregates
    trades: pd.DataFrame
    metrics: BacktestMetrics

    def plot_pnl(self, title: str = ""):
        from .plotting import plot_pnl

        return plot_pnl(self, title=title)

    def Plot_PNL(self, title: str = ""):
        return self.plot_pnl(title=title)

    def plot_daily_profit(self, title: str = "", figsize=(14, 5)):
        from .plotting import plot_daily_profit

        return plot_daily_profit(self, title=title, figsize=figsize)

    def Plot_Daily_Profit(self, title: str = "", figsize=(14, 5)):
        return self.plot_daily_profit(title=title, figsize=figsize)


    def __repr__(self) -> str:
        from .reporting import format_metrics

        return format_metrics(self.metrics)


__all__ = ["BacktestResult"]

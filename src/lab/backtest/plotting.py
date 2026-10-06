"""Matplotlib PnL plot showing gross and net equity curves."""
from __future__ import annotations

import math

from .result import BacktestResult


def _truncate(value: float, decimals: int = 2) -> float:
    if not math.isfinite(value):
        return value
    scale = 10**decimals
    return math.trunc(value * scale) / scale


def _sharpe_label(prefix: str, value: float) -> str:
    if not math.isfinite(value):
        return f"{prefix}: n/a"
    return f"{prefix}: {_truncate(value):.2f}"


def plot_pnl(result: BacktestResult, title: str = "", figsize=(14, 5)):
    import matplotlib.pyplot as plt

    frame = result.frame
    metrics = result.metrics
    figure, axis = plt.subplots(figsize=figsize)
    axis.plot(
        frame.Datetime,
        frame.GrossEquity,
        label=_sharpe_label("Sharpe", metrics.sharpe),
    )
    axis.plot(
        frame.Datetime,
        frame.NetEquity,
        label=_sharpe_label("Sharpe after fee", metrics.sharpe_after_fee),
    )
    axis.set_xlabel("Time")
    axis.set_ylabel("Return")
    axis.grid(True)
    axis.legend(loc="upper left")
    if title:
        axis.set_title(title)
    figure.tight_layout()
    return figure


def plot_daily_profit(result: BacktestResult, title: str = "", figsize=(14, 5)):
    import matplotlib.pyplot as plt
    import pandas as pd

    daily = result.aggregates.daily
    dates = pd.to_datetime(daily.index)
    cum_gross = daily["GrossGain"].cumsum()
    cum_net = daily["NetGain"].cumsum()
    num_days = len(daily)

    figure, axis = plt.subplots(figsize=figsize)
    axis.plot(
        dates,
        cum_gross,
        label=f"Total Profit: {cum_gross.iloc[-1]:.2f}" if len(cum_gross) else "Total Profit: 0.00",
    )
    axis.plot(
        dates,
        cum_net,
        label=f"Profit after fee: {cum_net.iloc[-1]:.2f}" if len(cum_net) else "Profit after fee: 0.00",
    )
    axis.set_xlabel("Time")
    axis.set_ylabel("Points")
    axis.grid(True)
    axis.legend(loc="upper left")
    if title:
        axis.set_title(title, loc="center")
    axis.set_title(f"Số ngày: {num_days}", loc="right", fontsize=10.5, color="#1e293b", fontweight="medium")
    figure.tight_layout()
    return figure


__all__ = ["plot_pnl", "plot_daily_profit"]


"""Standard metrics calculated from bar accounting, never exit-only rows."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .aggregation import PeriodAggregates, nonzero_hit_rate
from .config import BacktestConfig


def _sharpe(daily_points: pd.Series, annualization: int) -> float:
    if len(daily_points) < 2:
        return float("nan")
    deviation = float(daily_points.std(ddof=1))
    if deviation == 0.0:
        return float("nan")
    return float(daily_points.mean() / deviation * np.sqrt(annualization))


def _longest_losing_streak(values: pd.Series) -> int:
    longest = current = 0
    for value in values:
        if value < 0.0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


@dataclass(frozen=True)
class BacktestMetrics:
    bars: int
    trading_days: int
    total_profit: float
    total_fee: float
    profit_after_fee: float
    margin: float
    margin_after_fee: float
    sharpe: float
    sharpe_after_fee: float
    mdd_points: float
    mdd_percent: float
    mdd_peak: pd.Timestamp | None
    mdd_trough: pd.Timestamp | None
    total_trading_quantity: float
    profit_per_trade: float
    trading_quantity_per_day: float
    profit_per_day_after_fee: float
    profit_per_year: float
    hit_rate: float
    daily_hit_rate: float
    weekly_hit_rate: float
    monthly_hit_rate: float
    long_trades: int
    short_trades: int
    hit_rate_long: float
    hit_rate_short: float
    longest_consecutive_losing_days: int
    overnight_holding: float

    def as_dict(self) -> dict:
        return asdict(self)




def calculate_metrics(
    accounting: pd.DataFrame,
    aggregates: PeriodAggregates,
    trades: pd.DataFrame,
    config: BacktestConfig,
) -> BacktestMetrics:
    gross = float(accounting.GrossGain.sum())
    fee = float(accounting.FeeCost.sum())
    net = gross - fee
    traded_notional = float((accounting.Close * accounting.PositionChange).sum())
    quantity = float(accounting.PositionChange.sum() / 2.0)
    margin = gross / traded_notional * 10_000.0 if traded_notional else float("nan")
    margin_after_fee = net / traded_notional * 10_000.0 if traded_notional else float("nan")

    drawdown = accounting.NetPnl - accounting.NetPnl.cummax()
    trough_index = int(drawdown.idxmin())
    peak_index = int(accounting.NetPnl.loc[:trough_index].idxmax())
    mdd = float(-drawdown.loc[trough_index])
    trough_close = float(accounting.Close.loc[trough_index])
    mdd_percent = mdd / trough_close * 100.0
    days = int(len(aggregates.daily))
    annualized_denominator = max(days - 1, 1)

    gross_wins = trades.GrossPoints.gt(0.0) if len(trades) else pd.Series(dtype=bool)
    long = trades.Side.gt(0.0) if len(trades) else pd.Series(dtype=bool)
    short = trades.Side.lt(0.0) if len(trades) else pd.Series(dtype=bool)
    last_position = accounting.groupby("SessionDate", sort=True).Position.last()
    return BacktestMetrics(
        bars=int(len(accounting)),
        trading_days=days,
        total_profit=gross,
        total_fee=fee,
        profit_after_fee=net,
        margin=margin,
        margin_after_fee=margin_after_fee,
        sharpe=_sharpe(aggregates.daily.GrossGain, config.annualization_days),
        sharpe_after_fee=_sharpe(aggregates.daily.NetGain, config.annualization_days),
        mdd_points=mdd,
        mdd_percent=mdd_percent,
        mdd_peak=pd.Timestamp(accounting.Datetime.loc[peak_index]),
        mdd_trough=pd.Timestamp(accounting.Datetime.loc[trough_index]),
        total_trading_quantity=quantity,
        profit_per_trade=net / quantity if quantity else float("nan"),
        trading_quantity_per_day=quantity / days if days else float("nan"),
        profit_per_day_after_fee=net / days if days else float("nan"),
        profit_per_year=net / annualized_denominator * config.annualization_days,
        hit_rate=float(gross_wins.mean()) if len(gross_wins) else float("nan"),
        daily_hit_rate=nonzero_hit_rate(aggregates.daily.GrossGain),
        weekly_hit_rate=nonzero_hit_rate(aggregates.weekly.GrossGain),
        monthly_hit_rate=nonzero_hit_rate(aggregates.monthly.GrossGain),
        long_trades=int(long.sum()),
        short_trades=int(short.sum()),
        hit_rate_long=float(gross_wins[long].mean()) if long.any() else 0.0,
        hit_rate_short=float(gross_wins[short].mean()) if short.any() else 0.0,
        longest_consecutive_losing_days=_longest_losing_streak(
            aggregates.daily.NetGain
        ),
        overnight_holding=float(last_position.ne(0.0).mean()),
    )


__all__ = ["BacktestMetrics", "calculate_metrics"]

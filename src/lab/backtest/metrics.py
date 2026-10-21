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
    return_per_year: float = 0.0
    avg_return_per_year: float = 0.0
    sortino_after_fee: float = 0.0
    calmar_after_fee: float = 0.0
    annual_volatility_points: float = 0.0
    worst_daily_loss: float = 0.0
    daily_var_95: float = 0.0
    daily_cvar_95: float = 0.0
    mdd_duration_days: int = 0
    mdd_recovery_days: int | None = None
    daily_skew: float = 0.0
    daily_kurtosis: float = 0.0
    profit_factor: float = 0.0
    avg_win_points: float = 0.0
    avg_loss_points: float = 0.0
    win_loss_ratio: float = 0.0
    avg_bars_held: float = 0.0
    exposure_rate: float = 0.0
    fee_ratio: float = 0.0

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

    profit_per_year = net / annualized_denominator * config.annualization_days

    # Return on notional (NetGain / Close)
    total_net_return = float(accounting.NetBarReturn.sum())
    return_per_year = (total_net_return / annualized_denominator * config.annualization_days) * 100.0
    yearly_returns = accounting.groupby(accounting.Datetime.dt.year, sort=True).NetBarReturn.sum() * 100.0
    avg_return_per_year = float(yearly_returns.mean()) if len(yearly_returns) else float("nan")

    # Risk metrics from daily NetGain distribution
    daily_net = aggregates.daily.NetGain
    downside = np.minimum(daily_net, 0.0)
    downside_dev = float(np.sqrt(np.mean(downside**2))) if len(daily_net) else 0.0
    sortino_after_fee = (
        float(daily_net.mean() / downside_dev * np.sqrt(config.annualization_days))
        if downside_dev > 0.0
        else float("nan")
    )
    calmar_after_fee = float(profit_per_year / mdd) if mdd > 0.0 else float("nan")
    daily_std = float(daily_net.std(ddof=1)) if len(daily_net) > 1 else 0.0
    annual_volatility_points = float(daily_std * np.sqrt(config.annualization_days))
    worst_daily_loss = float(daily_net.min()) if len(daily_net) else float("nan")
    daily_var_95 = float(np.percentile(daily_net, 5)) if len(daily_net) else float("nan")
    tail = daily_net[daily_net <= daily_var_95]
    daily_cvar_95 = float(tail.mean()) if len(tail) else daily_var_95
    daily_skew = float(daily_net.skew()) if len(daily_net) > 2 else float("nan")
    daily_kurtosis = float(daily_net.kurtosis()) if len(daily_net) > 3 else float("nan")

    # Drawdown timing
    mdd_peak_time = pd.Timestamp(accounting.Datetime.loc[peak_index])
    mdd_trough_time = pd.Timestamp(accounting.Datetime.loc[trough_index])
    mdd_duration_days = int((mdd_trough_time.normalize() - mdd_peak_time.normalize()).days)
    subsequent = accounting.loc[trough_index:]
    recovered = subsequent[subsequent.NetPnl >= accounting.NetPnl.loc[peak_index]]
    if len(recovered) > 1 or (len(recovered) == 1 and recovered.index[0] != trough_index):
        recovery_time = pd.Timestamp(recovered.Datetime.iloc[0])
        mdd_recovery_days = int((recovery_time.normalize() - mdd_trough_time.normalize()).days)
    else:
        mdd_recovery_days = None

    # Trade ledger metrics
    pos_gain = float(daily_net[daily_net > 0.0].sum())
    neg_gain = float(abs(daily_net[daily_net < 0.0].sum()))
    profit_factor = (
        float(pos_gain / neg_gain)
        if neg_gain > 0.0
        else (float("inf") if pos_gain > 0.0 else 0.0)
    )
    wins = trades.NetPoints[trades.NetPoints > 0.0] if len(trades) else pd.Series(dtype=float)
    losses = trades.NetPoints[trades.NetPoints < 0.0] if len(trades) else pd.Series(dtype=float)
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    win_loss_ratio = float(avg_win / abs(avg_loss)) if avg_loss != 0.0 else float("nan")
    avg_bars_held = float(trades.BarsHeld.mean()) if len(trades) else 0.0
    exposure_rate = float(accounting.ExecutedPosition.ne(0.0).mean()) * 100.0
    fee_ratio = float(fee / gross * 100.0) if gross > 0.0 else float("nan")

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
        profit_per_year=profit_per_year,
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
        return_per_year=return_per_year,
        avg_return_per_year=avg_return_per_year,
        sortino_after_fee=sortino_after_fee,
        calmar_after_fee=calmar_after_fee,
        annual_volatility_points=annual_volatility_points,
        worst_daily_loss=worst_daily_loss,
        daily_var_95=daily_var_95,
        daily_cvar_95=daily_cvar_95,
        mdd_duration_days=mdd_duration_days,
        mdd_recovery_days=mdd_recovery_days,
        daily_skew=daily_skew,
        daily_kurtosis=daily_kurtosis,
        profit_factor=profit_factor,
        avg_win_points=avg_win,
        avg_loss_points=avg_loss,
        win_loss_ratio=win_loss_ratio,
        avg_bars_held=avg_bars_held,
        exposure_rate=exposure_rate,
        fee_ratio=fee_ratio,
    )


__all__ = ["BacktestMetrics", "calculate_metrics"]

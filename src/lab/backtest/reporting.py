"""Console report intentionally limited to metrics with verified parity."""
from __future__ import annotations

from .metrics import BacktestMetrics


def format_metrics(metrics: BacktestMetrics) -> str:
    mdd_time = (
        f"{metrics.mdd_peak:%Y-%m-%d} → {metrics.mdd_trough:%Y-%m-%d}"
        if metrics.mdd_peak is not None and metrics.mdd_trough is not None
        else "n/a"
    )
    mdd_recovery = (
        f"{metrics.mdd_recovery_days} days"
        if metrics.mdd_recovery_days is not None
        else "not recovered"
    )
    lines = [
        f"                   Margin: {metrics.margin:.2f}",
        f"         Margin after fee: {metrics.margin_after_fee:.2f}",
        f"                      MDD: {metrics.mdd_points:.1f} ({metrics.mdd_percent:.2f}%); Time: {mdd_time}",
        f"   Total trading quantity: {metrics.total_trading_quantity:g}",
        f"         Sharpe after fee: {metrics.sharpe_after_fee:.2f}",
        f"         Profit per trade: {metrics.profit_per_trade:.2f}",
        f"             Total Profit: {metrics.total_profit:.2f}",
        f"         Profit after fee: {metrics.profit_after_fee:.2f}",
        f" Trading quantity per day: {metrics.trading_quantity_per_day:.2f}",
        f" Profit per day after fee: {metrics.profit_per_day_after_fee:.2f}",
        f"          Return per year: {metrics.return_per_year:.2f}%",
        f"      Avg return per year: {metrics.avg_return_per_year:.2f}%",
        f"          Profit per year: {metrics.profit_per_year:.2f}",
        f"                  HitRate: {metrics.hit_rate:.2%}",
        f"            Daily HitRate: {metrics.daily_hit_rate:.2%}",
        f"           Weekly HitRate: {metrics.weekly_hit_rate:.2%}",
        f"          Monthly HitRate: {metrics.monthly_hit_rate:.2%}",
        f"                     Long: {metrics.long_trades}",
        f"                    Short: {metrics.short_trades}",
        f"             Hitrate long: {metrics.hit_rate_long:.2%}",
        f"            Hitrate short: {metrics.hit_rate_short:.2%}",
        f"Longest consecutive losing days: {metrics.longest_consecutive_losing_days}",
        f"        Overnight holding: {metrics.overnight_holding:.2%}",
        "--------------------------------------------------",
        f"                  Sortino: {metrics.sortino_after_fee:.2f}",
        f"                   Calmar: {metrics.calmar_after_fee:.2f}",
        f"        Annual Volatility: {metrics.annual_volatility_points:.2f} pts",
        f"                Worst Day: {metrics.worst_daily_loss:.2f} pts",
        f"            Daily VaR 95%: {metrics.daily_var_95:.2f} pts",
        f"           Daily CVaR 95%: {metrics.daily_cvar_95:.2f} pts",
        f"             MDD Duration: {metrics.mdd_duration_days} days (recovery: {mdd_recovery})",
        f"          Skew / Kurtosis: {metrics.daily_skew:.2f} / {metrics.daily_kurtosis:.2f}",
        f"            Profit Factor: {metrics.profit_factor:.2f}",
        f"       Avg Win / Avg Loss: {metrics.avg_win_points:.2f} pts / {metrics.avg_loss_points:.2f} pts (Ratio: {metrics.win_loss_ratio:.2f})",
        f"            Avg Bars Held: {metrics.avg_bars_held:.1f} bars",
        f"            Exposure Rate: {metrics.exposure_rate:.2f}%",
        f"                Fee Ratio: {metrics.fee_ratio:.2f}%",
    ]
    return "\n".join(lines)


__all__ = ["format_metrics"]

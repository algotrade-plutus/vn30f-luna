"""Console report intentionally limited to metrics with verified parity."""
from __future__ import annotations

from .metrics import BacktestMetrics


def format_metrics(metrics: BacktestMetrics) -> str:
    return "\n".join(
        [
            f"                   Margin: {metrics.margin:.2f}",
            f"         Margin after fee: {metrics.margin_after_fee:.2f}",
            f"                      MDD: {metrics.mdd_points:.1f} ({metrics.mdd_percent:.2f}%); "
            f"Time: {metrics.mdd_peak:%Y-%m-%d} → {metrics.mdd_trough:%Y-%m-%d}",
            f"   Total trading quantity: {metrics.total_trading_quantity:g}",
            f"         Sharpe after fee: {metrics.sharpe_after_fee:.2f}",
            f"         Profit per trade: {metrics.profit_per_trade:.2f}",
            f"             Total Profit: {metrics.total_profit:.2f}",
            f"         Profit after fee: {metrics.profit_after_fee:.2f}",
            f" Trading quantity per day: {metrics.trading_quantity_per_day:.2f}",
            f" Profit per day after fee: {metrics.profit_per_day_after_fee:.2f}",
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
        ]
    )


__all__ = ["format_metrics"]

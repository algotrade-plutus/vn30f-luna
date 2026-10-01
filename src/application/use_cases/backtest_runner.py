"""Application Use Case: Backtest Runner.
Coordinates Steps 4, 5, 6 backtest runs and computes full accounting metrics.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import math

from src.application.ports.broker_port import IBrokerGateway
from src.application.ports.market_data_port import IMarketDataGateway
from src.application.use_cases.risk_monitor import RiskMonitorUseCase
from src.application.use_cases.trading_cycle import TradingCycleUseCase
from src.domain.strategy.hypothesis import FalsificationCriteria
from src.domain.strategy.luna_strategy import LunaParameters, LunaStrategy
from src.domain.entities.position import Position


@dataclass
class BacktestSummary:
    """Summary metrics of a completed backtest execution."""
    sample_name: str
    symbol: str
    start_date: date
    end_date: date
    initial_deposit: float
    ending_equity: float
    total_net_pnl: float
    return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    peak_margin_utilisation_pct: float
    margin_calls_count: int
    margin_warnings_count: int
    rejected_orders_count: int
    passed_falsification: bool
    falsification_failures: list[str]


class BacktestRunnerUseCase:
    """Executes a backtest over a market data window using Clean Architecture gateways."""

    def __init__(
        self,
        market_data: IMarketDataGateway,
        broker: IBrokerGateway,
        criteria: FalsificationCriteria | None = None,
    ) -> None:
        self.market_data = market_data
        self.broker = broker
        self.criteria = criteria or FalsificationCriteria()

    def run(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        sample_name: str = "in_sample",
        params: LunaParameters | None = None,
    ) -> BacktestSummary:
        """Run backtest across all 30m bars between start_date and end_date."""
        strategy = LunaStrategy(params)
        risk_monitor = RiskMonitorUseCase(self.broker)
        trading_cycle = TradingCycleUseCase(
            strategy=strategy,
            broker=self.broker,
            risk_monitor=risk_monitor,
            target_symbol=symbol,
        )

        # 1. Capture capital before the first event, then fetch bars.
        initial_deposit = float(self.broker.get_margin().deposit_balance)
        bars = self.market_data.get_bars(symbol, "30m", start_date, end_date)
        if not bars:
            raise ValueError(f"No bars returned for {symbol} between {start_date} and {end_date}")

        # 2. Iterate bars and advance broker clock
        daily_equities: dict[date, float] = {}

        for bar in bars:
            self.broker.advance_to(bar.timestamp)
            trading_cycle.on_bar(bar)
            margin_snap = self.broker.get_margin()
            d = bar.timestamp.date()
            daily_equities[d] = float(margin_snap.equity)

        # 3. Compute Metrics
        final_equity = list(daily_equities.values())[-1] if daily_equities else initial_deposit
        net_pnl = final_equity - initial_deposit
        return_pct = (net_pnl / initial_deposit) * 100 if initial_deposit > 0 else 0.0

        num_days = max(len(daily_equities), 1)
        annualized_return_pct = (
            ((final_equity / initial_deposit) ** (252 / num_days) - 1) * 100
            if initial_deposit > 0 and final_equity > 0
            else -100.0
        )

        # Daily returns & Sharpe
        daily_vals = list(daily_equities.values())
        daily_returns = [
            (daily_vals[i] - daily_vals[i - 1]) / daily_vals[i - 1]
            for i in range(1, len(daily_vals))
            if daily_vals[i - 1] > 0
        ]
        if len(daily_returns) > 1:
            mean_ret = sum(daily_returns) / len(daily_returns)
            var_ret = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
            std_ret = math.sqrt(var_ret) if var_ret > 0 else 0.0
            sharpe_ratio = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # Maximum Drawdown
        peak = initial_deposit
        max_dd_pct = 0.0
        for eq in daily_vals:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd_pct:
                max_dd_pct = dd

        # Fills and trade stats
        fills = self.broker.get_fills()
        trades_count = len(fills)
        replay = Position(symbol=symbol)
        realised_legs: list[float] = []
        for fill in fills:
            if fill.symbol != symbol:
                continue
            closed, pnl = replay.apply_fill(fill)
            if closed:
                realised_legs.append(float(pnl - fill.fee - fill.tax))
        wins = [pnl for pnl in realised_legs if pnl > 0]
        losses = [-pnl for pnl in realised_legs if pnl < 0]
        profit_factor = sum(wins) / sum(losses) if losses else (float("inf") if wins else 0.0)

        # Check rejections
        rejections = sum(1 for log in trading_cycle.logs if "REJECTED" in log.order_status)

        # Falsification check
        failures: list[str] = []
        min_sharpe = (
            float(self.criteria.min_sharpe_in_sample)
            if sample_name == "in_sample"
            else float(self.criteria.min_sharpe_out_of_sample)
        )
        if sharpe_ratio < min_sharpe:
            failures.append(f"Sharpe ratio ({sharpe_ratio:.2f}) < required minimum ({min_sharpe:.2f})")
        if max_dd_pct > float(self.criteria.max_drawdown_pct):
            failures.append(f"Max drawdown ({max_dd_pct:.1f}%) > threshold ({float(self.criteria.max_drawdown_pct):.1f}%)")
        if risk_monitor.call_count > self.criteria.max_margin_calls:
            failures.append(f"Margin calls ({risk_monitor.call_count}) > {self.criteria.max_margin_calls}")
        if risk_monitor.peak_utilisation >= float(self.criteria.max_peak_margin_utilisation):
            failures.append(f"Peak utilisation ({risk_monitor.peak_utilisation*100:.1f}%) >= {float(self.criteria.max_peak_margin_utilisation)*100:.1f}%")
        if rejections > self.criteria.max_exchange_rejects:
            failures.append(f"Rejected orders ({rejections}) > {self.criteria.max_exchange_rejects}")
        if math.isfinite(profit_factor) and profit_factor < float(self.criteria.min_profit_factor):
            failures.append(
                f"Profit factor ({profit_factor:.2f}) < required minimum "
                f"({float(self.criteria.min_profit_factor):.2f})"
            )

        passed = len(failures) == 0

        return BacktestSummary(
            sample_name=sample_name,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_deposit=initial_deposit,
            ending_equity=final_equity,
            total_net_pnl=net_pnl,
            return_pct=return_pct,
            annualized_return_pct=annualized_return_pct,
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_dd_pct,
            total_trades=trades_count,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=(len(wins) / len(realised_legs) * 100 if realised_legs else 0.0),
            profit_factor=profit_factor,
            peak_margin_utilisation_pct=risk_monitor.peak_utilisation * 100,
            margin_calls_count=risk_monitor.call_count,
            margin_warnings_count=risk_monitor.warning_count,
            rejected_orders_count=rejections,
            passed_falsification=passed,
            falsification_failures=failures,
        )

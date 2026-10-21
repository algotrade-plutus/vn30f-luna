from __future__ import annotations

import pandas as pd
import pytest

from src.lab.backtest import BacktestConfig, evaluate, validate_position_stream


def make_stream(positions: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Datetime": pd.date_range("2024-01-02 09:00", periods=len(positions), freq="30min"),
            "Close": [100.0, 101.0, 103.0, 102.0][: len(positions)],
            "Position": positions,
        }
    )


def test_fee_accounting_round_trip_costs_0_8_points() -> None:
    frame = make_stream([0.0, 1.0, 1.0, 0.0])

    result = evaluate(frame, BacktestConfig(round_trip_fee_points=0.8))

    assert result.metrics.total_profit == pytest.approx(1.0)
    assert result.metrics.total_fee == pytest.approx(0.8)
    assert result.metrics.profit_after_fee == pytest.approx(0.2)

    fees = result.frame["FeeCost"].tolist()
    assert fees[1] == pytest.approx(0.4)
    assert fees[3] == pytest.approx(0.4)
    assert result.metrics.long_trades == 1
    assert result.metrics.short_trades == 0


def test_validate_position_stream_rejects_fractional_positions_when_discrete_required() -> None:
    frame = make_stream([0.5, 0.0])

    with pytest.raises(ValueError, match="discrete"):
        validate_position_stream(frame, BacktestConfig(require_discrete_position=True))


def test_validate_position_stream_allows_continuous_positions_when_not_discrete_required() -> None:
    frame = make_stream([0.5, 0.25])

    validated = validate_position_stream(frame, BacktestConfig(require_discrete_position=False))

    assert validated["Position"].tolist() == [0.5, 0.25]


def test_evaluate_returns_core_outputs_and_metric_fields() -> None:
    frame = make_stream([0.0, 1.0, -1.0, 0.0])

    result = evaluate(frame, BacktestConfig())

    assert {"Datetime", "Close", "Position", "ExecutedPosition", "NetPnl"}.issubset(result.frame.columns)
    assert result.frame["ExecutedPosition"].tolist() == [0.0, 0.0, 1.0, -1.0]

    expected_metric_keys = {
        "bars",
        "trading_days",
        "total_profit",
        "total_fee",
        "profit_after_fee",
        "margin",
        "margin_after_fee",
        "sharpe",
        "sharpe_after_fee",
        "mdd_points",
        "mdd_percent",
        "hit_rate",
        "profit_per_trade",
        "profit_per_year",
        "long_trades",
        "short_trades",
        "return_per_year",
        "avg_return_per_year",
        "sortino_after_fee",
        "calmar_after_fee",
        "annual_volatility_points",
        "worst_daily_loss",
        "daily_var_95",
        "daily_cvar_95",
        "mdd_duration_days",
        "mdd_recovery_days",
        "daily_skew",
        "daily_kurtosis",
        "profit_factor",
        "avg_win_points",
        "avg_loss_points",
        "win_loss_ratio",
        "avg_bars_held",
        "exposure_rate",
        "fee_ratio",
    }
    assert expected_metric_keys.issubset(result.metrics.as_dict().keys())


def test_validate_position_stream_multi_unit_discrete() -> None:
    frame = pd.DataFrame(
        {
            "Datetime": pd.date_range("2024-01-02 09:00", periods=5, freq="30min"),
            "Close": [100.0, 101.0, 102.0, 103.0, 104.0],
            "Position": [-3.0, 0.0, 2.0, 1.0, 3.0],
        }
    )
    # Validates with max_position=3.0
    validated = validate_position_stream(frame, BacktestConfig(max_position=3.0))
    assert validated["Position"].tolist() == [-3.0, 0.0, 2.0, 1.0, 3.0]

    # Rejects 4.0 when max_position=3.0
    invalid_frame = frame.copy()
    invalid_frame.loc[0, "Position"] = 4.0
    with pytest.raises(ValueError, match="discrete"):
        validate_position_stream(invalid_frame, BacktestConfig(max_position=3.0))


def test_trade_ledger_multi_level_scaling_grouped_as_single_trade() -> None:
    # Position: 0 -> 1 -> 2 -> 1 -> 0 (scale in then scale out without sign change)
    # ExecutedPosition: 0 -> 0 -> 1 -> 2 -> 1 -> 0
    frame = pd.DataFrame(
        {
            "Datetime": pd.date_range("2024-01-02 09:00", periods=6, freq="30min"),
            "Close": [100.0, 101.0, 103.0, 106.0, 105.0, 104.0],
            "Position": [0.0, 1.0, 2.0, 1.0, 0.0, 0.0],
        }
    )
    result = evaluate(frame, BacktestConfig(max_position=2.0, round_trip_fee_points=0.8))

    # All scaling in same direction must be 1 Long trade, not split into 3 trades
    assert result.metrics.long_trades == 1
    assert result.metrics.short_trades == 0
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["Side"] == 1.0
    assert trade["BarsHeld"] == 3
    # Peak size was 2.0 units, so round trip fee points = 2.0 * 0.8 = 1.6
    assert trade["FeePoints"] == pytest.approx(1.6)


def test_extended_metrics_and_format_metrics() -> None:
    from src.lab.backtest.reporting import format_metrics

    frame = pd.DataFrame(
        {
            "Datetime": pd.date_range("2024-01-02 09:00", periods=8, freq="30min"),
            "Close": [100.0, 102.0, 105.0, 103.0, 106.0, 104.0, 107.0, 108.0],
            "Position": [0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.0, 0.0],
        }
    )
    result = evaluate(frame, BacktestConfig(round_trip_fee_points=0.8))
    m = result.metrics

    assert isinstance(m.return_per_year, float)
    assert isinstance(m.avg_return_per_year, float)
    assert isinstance(m.sortino_after_fee, float)
    assert isinstance(m.calmar_after_fee, float)
    assert isinstance(m.annual_volatility_points, float)
    assert isinstance(m.worst_daily_loss, float)
    assert isinstance(m.daily_var_95, float)
    assert isinstance(m.daily_cvar_95, float)
    assert isinstance(m.mdd_duration_days, int)
    assert isinstance(m.profit_factor, float)
    assert isinstance(m.avg_bars_held, float)
    assert isinstance(m.exposure_rate, float)
    assert isinstance(m.fee_ratio, float)

    formatted = format_metrics(m)
    assert "Return per year:" in formatted
    assert "Avg return per year:" in formatted
    assert "Sortino:" in formatted
    assert "Calmar:" in formatted
    assert "Annual Volatility:" in formatted
    assert "Worst Day:" in formatted
    assert "Profit Factor:" in formatted


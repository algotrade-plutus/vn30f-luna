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
    }
    assert expected_metric_keys.issubset(result.metrics.as_dict().keys())

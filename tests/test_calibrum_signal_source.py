from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.adapters.strategies.calibrum_signal_source import (
    _ridge_with_roll_guard,
    pre_shift_positions,
    roll_adjust_front_month,
)


def test_pre_shift_positions_uses_next_available_row_not_clock_arithmetic() -> None:
    positions = pd.DataFrame(
        {
            "Datetime": pd.to_datetime(
                ["2024-01-02 11:00", "2024-01-02 11:30", "2024-01-02 13:00"]
            ),
            "Position": [1, -1, 0],
        }
    )

    targets = pre_shift_positions(positions, quantity=2)

    assert targets == {
        datetime(2024, 1, 2, 11, 30): 2,
        datetime(2024, 1, 2, 13, 0): -2,
    }


def test_pre_shift_positions_rejects_non_canonical_signal() -> None:
    positions = pd.DataFrame(
        {
            "Datetime": pd.to_datetime(["2024-01-02 09:00"]),
            "Position": [3],
        }
    )

    with pytest.raises(ValueError, match="must be in"):
        pre_shift_positions(positions)


def test_roll_adjusted_future_removes_mechanical_contract_gap() -> None:
    frame = pd.DataFrame(
        {
            "Datetime": pd.to_datetime(
                ["2024-01-18 14:30", "2024-01-19 09:00", "2024-01-19 09:30"]
            ),
            "Contract": ["VN30F2401", "VN30F2402", "VN30F2402"],
            "Open": [100.0, 105.0, 106.0],
            "High": [101.0, 106.0, 107.0],
            "Low": [99.0, 104.0, 105.0],
            "Close": [101.0, 106.0, 107.0],
            "Volume": [1, 1, 1],
        }
    )

    adjusted, adjustments = roll_adjust_front_month(frame)

    assert adjusted.loc[1, "Open"] == 101.0
    assert adjusted.loc[1, "Close"] == 102.0
    assert adjusted.loc[2, "Close"] == 103.0
    assert adjustments[0]["incremental_offset"] == -4.0


def test_ridge_roll_guard_restarts_each_contract_and_zeros_expiry() -> None:
    class FrozenRidge:
        calls: list[int] = []

        @classmethod
        def _ridge_positions(cls, frame, _parameters, _model):
            cls.calls.append(len(frame))
            return [1] * len(frame)

        @staticmethod
        def _is_expiry_session(stamps):
            return pd.to_datetime(stamps).dt.date.eq(pd.Timestamp("2024-01-18").date()).to_numpy()

    frame = pd.DataFrame(
        {
            "Datetime": pd.to_datetime(
                ["2024-01-18 14:00", "2024-01-18 14:30", "2024-01-19 09:00"]
            ),
            "Contract": ["VN30F2401", "VN30F2401", "VN30F2402"],
        }
    )

    positions = _ridge_with_roll_guard(FrozenRidge, frame, {}, {})

    assert FrozenRidge.calls == [2, 1]
    assert positions.tolist() == [0, 0, 1]

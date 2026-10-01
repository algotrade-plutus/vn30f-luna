from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.adapters.strategies import (
    Ec2LunaReplayParameters,
    generate_luna_ec2_targets,
)


def _frame(monday_open: float = 99.0) -> pd.DataFrame:
    rows = [
        ("2024-01-05 14:20:00", 100.0, "VN30F2401"),
        ("2024-01-05 14:25:00", 100.0, "VN30F2401"),
        ("2024-01-05 14:30:00", 100.0, "VN30F2401"),
        ("2024-01-05 14:45:00", 100.0, "VN30F2401"),
        ("2024-01-08 09:00:00", monday_open, "VN30F2401"),
        ("2024-01-08 09:15:00", monday_open, "VN30F2401"),
        ("2024-01-08 09:20:00", monday_open, "VN30F2401"),
        ("2024-01-08 14:00:00", 100.0, "VN30F2401"),
        ("2024-01-08 14:20:00", 100.0, "VN30F2401"),
        ("2024-01-08 14:25:00", 100.0, "VN30F2401"),
        ("2024-01-08 14:30:00", 100.0, "VN30F2401"),
    ]
    return pd.DataFrame(
        {
            "Datetime": pd.to_datetime([item[0] for item in rows]),
            "Open": [item[1] for item in rows],
            "High": [item[1] + 0.5 for item in rows],
            "Low": [item[1] - 0.5 for item in rows],
            "Close": [item[1] for item in rows],
            "Volume": [100] * len(rows),
            "Contract": [item[2] for item in rows],
        }
    )


def test_regular_monday_short_then_prepositions_tuesday_long() -> None:
    result = generate_luna_ec2_targets(
        _frame(),
        Ec2LunaReplayParameters(quantity=8, use_fomo_gatekeeper=False),
    )

    assert result.targets[datetime(2024, 1, 8, 9, 20)] == -8
    assert result.targets[datetime(2024, 1, 8, 14, 25)] == 8
    assert result.targets[datetime(2024, 1, 8, 14, 30)] == 8


def test_positive_monday_gap_does_not_open_calendar_short() -> None:
    result = generate_luna_ec2_targets(
        _frame(monday_open=101.0),
        Ec2LunaReplayParameters(quantity=8, use_fomo_gatekeeper=False),
    )

    assert result.targets[datetime(2024, 1, 8, 9, 20)] == 0

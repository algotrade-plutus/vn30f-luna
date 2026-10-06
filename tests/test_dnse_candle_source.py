from __future__ import annotations

import pandas as pd

from src.adapters.data.dnse_candle_source import normalize_bars, payload_to_frame


def test_normalize_repairs_swapped_high_low() -> None:
    frame = pd.DataFrame(
        {
            "Datetime": [pd.Timestamp("2024-01-02 09:00:00")],
            "Open": [1548.0],
            "High": [1548.0],
            "Low": [1553.9],
            "Close": [1553.9],
            "Volume": [5293],
        }
    )

    normalized = normalize_bars(frame)

    assert normalized.loc[0, "High"] == 1553.9
    assert normalized.loc[0, "Low"] == 1548.0
    assert normalized.loc[0, "Open"] == 1548.0
    assert normalized.loc[0, "Close"] == 1553.9


def test_payload_to_frame_converts_epoch_seconds_to_naive_local_time() -> None:
    payload = {
        "t": [1704160800],  # 2024-01-02 09:00:00 UTC+7
        "o": [100.0],
        "h": [101.0],
        "l": [99.0],
        "c": [100.5],
        "v": [10.0],
    }

    frame = payload_to_frame(payload)

    assert frame["Datetime"].iloc[0] == pd.Timestamp("2024-01-02 09:00:00")
    assert frame["Datetime"].dt.tz is None
    assert list(frame.columns) == ["Datetime", "Open", "High", "Low", "Close", "Volume"]

from __future__ import annotations

import pandas as pd

from src.adapters.data.dnse_candle_source import (
    add_front_month_contract,
    align_to_bar_clock,
    normalize_bars,
    payload_to_frame,
)


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


def test_align_to_bar_clock_relabels_first_index_bar_to_0900() -> None:
    frame = pd.DataFrame(
        {
            "Datetime": pd.to_datetime(["2023-04-12 09:15", "2023-04-12 09:30"]),
            "Open": [1083.15, 1080.89],
            "High": [1084.0, 1083.0],
            "Low": [1080.0, 1080.5],
            "Close": [1080.84, 1082.73],
            "Volume": [10, 20],
        }
    )

    aligned = align_to_bar_clock(frame)

    assert aligned["Datetime"].tolist() == list(pd.to_datetime(["2023-04-12 09:00", "2023-04-12 09:30"]))
    assert aligned.loc[0, "Close"] == 1080.84


def test_align_to_bar_clock_merges_bars_in_one_bucket() -> None:
    frame = pd.DataFrame(
        {
            "Datetime": pd.to_datetime(["2023-04-12 09:00", "2023-04-12 09:15"]),
            "Open": [1.0, 2.0],
            "High": [3.0, 5.0],
            "Low": [0.5, 1.5],
            "Close": [2.0, 4.0],
            "Volume": [10, 20],
        }
    )

    aligned = align_to_bar_clock(frame)

    assert len(aligned) == 1
    assert aligned.iloc[0][["Open", "High", "Low", "Close", "Volume"]].tolist() == [1.0, 5.0, 0.5, 4.0, 30]


def test_add_front_month_contract_rolls_after_expiry_session() -> None:
    # 2024-04-18 (third Thursday) was a holiday, so the April contract expired on 2024-04-17.
    frame = pd.DataFrame({"Datetime": pd.to_datetime(["2024-04-17 14:30", "2024-04-19 09:00"])})

    assert add_front_month_contract(frame)["Contract"].tolist() == ["VN30F2404", "VN30F2405"]

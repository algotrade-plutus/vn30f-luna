from __future__ import annotations

import pandas as pd

from src.adapters.data.dnse_candle_source import cache_path, save_cached_bars
from src.adapters.data.dnse_minute_bars import bars_10m, bars_30m, load_futures_minutes


def minutes(stamps: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Datetime": pd.to_datetime(stamps),
            "Open": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": [10.0] * len(closes),
        }
    )


SESSION = minutes(
    ["2024-03-12 11:29", "2024-03-12 11:30", "2024-03-12 14:29", "2024-03-12 14:30", "2024-03-12 14:45"],
    [100.0, 101.0, 102.0, 103.0, 104.0],
)


def test_10m_merges_stubs_into_previous_bar_and_keeps_atc_apart() -> None:
    out = bars_10m(SESSION).set_index("Datetime")

    assert list(out.index.strftime("%H:%M")) == ["11:20", "14:20", "14:45"]
    assert out.loc["2024-03-12 11:20", "Close"] == 101.0
    assert out.loc["2024-03-12 14:20", "Volume"] == 20.0
    assert out.loc["2024-03-12 14:45", "Close"] == 104.0


def test_30m_keeps_the_1130_stub_and_puts_atc_in_the_1430_bar() -> None:
    out = bars_30m(SESSION).set_index("Datetime")

    assert list(out.index.strftime("%H:%M")) == ["11:00", "11:30", "14:00", "14:30"]
    assert out.loc["2024-03-12 11:00", "Close"] == 100.0
    assert out.loc["2024-03-12 14:30", "Open"] == 103.0
    assert out.loc["2024-03-12 14:30", "Close"] == 104.0


def test_sessions_without_1m_bars_take_5m_bars(tmp_path) -> None:
    one = minutes(["2023-03-21 09:00", "2023-03-21 09:01"], [1000.0, 1001.0])
    five = minutes(
        ["2023-03-21 09:00", "2023-03-22 09:00", "2023-03-22 09:05"],
        [1000.0, 1010.0, 1011.0],
    )
    save_cached_bars(one, cache_path("derivative", "VN30F1M", 1, tmp_path))
    save_cached_bars(five, cache_path("derivative", "VN30F1M", 5, tmp_path))

    out = load_futures_minutes(tmp_path)

    assert out.groupby(out["Datetime"].dt.date)["Resolution"].unique().map(list).to_dict() == {
        pd.Timestamp("2023-03-21").date(): [1],
        pd.Timestamp("2023-03-22").date(): [5],
    }
    assert len(out) == 4
    # March 2023 expired on Thursday 16/03, so these sessions trade April.
    assert out["Contract"].unique().tolist() == ["VN30F2304"]

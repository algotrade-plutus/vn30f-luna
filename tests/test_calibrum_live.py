from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.adapters.strategies.calendar_mtw_signal_source import Leg, build_positions
from src.lab.calibrum_1m import live, pipeline
from src.lab.calibrum_1m.grid import completes_bar, next_print


def test_next_print_skips_lunch_auction_wait_and_close() -> None:
    at = pd.Timestamp
    assert next_print(at("2026-10-22 10:17")) == at("2026-10-22 10:17")
    assert next_print(at("2026-10-22 08:40")) == at("2026-10-22 09:00")
    assert next_print(at("2026-10-22 11:31")) == at("2026-10-22 13:00")
    assert next_print(at("2026-10-22 14:31")) == at("2026-10-22 14:45")
    assert next_print(at("2026-10-23 14:46")) == at("2026-10-26 09:00")  # Friday to Monday


def test_last_row_closes_its_bar_only_when_the_next_print_is_in_another_bar() -> None:
    labels = pd.Series(pd.to_datetime(["2026-10-22 09:00"] * 2 + ["2026-10-22 09:30"] * 2))

    assert completes_bar(labels).tolist() == [False, True, False, True]
    assert completes_bar(labels, pd.Timestamp("2026-10-22 09:30")).tolist() == [False, True, False, False]
    assert completes_bar(labels, pd.Timestamp("2026-10-22 10:00")).tolist() == [False, True, False, True]


def test_open_end_keeps_a_leg_whose_exit_is_beyond_the_data() -> None:
    bars = pd.DataFrame({
        "Datetime": pd.to_datetime(["2026-10-19 14:10", "2026-10-19 14:20", "2026-10-20 09:00"]),
        "Close": [1.0, 2.0, 3.0],
    })
    leg = Leg("W0X1", 1, pd.Timestamp("2026-10-19 14:20"), pd.Timestamp("2026-10-23 10:00"))

    assert build_positions(bars, [leg])[0]["Position"].tolist() == [0.0, 0.0, 0.0]
    assert build_positions(bars, [leg], open_end=True)[0]["Position"].tolist() == [0.0, 1.0, 1.0]


@pytest.fixture(scope="module")
def history():
    if not live.LIVE_CONFIG.exists():
        pytest.skip("config/calibrum_live.toml not written")
    try:
        market = pipeline.load_market(pd.Timestamp("2026-10-21").date())
        index_minutes = pipeline.load_index_minutes()
    except Exception as exc:  # cached DNSE bars are not in the repository
        pytest.skip(f"DNSE cache unavailable: {exc}")
    return market, index_minutes, live.load_params()


def test_live_window_matches_the_full_history(history) -> None:
    """The live target at a minute equals the backtest position at that minute (sessions with index bars)."""
    market, index_minutes, params = history
    full = {
        "calendar": pipeline.calendar_mtw_positions(market),
        "basis": pipeline.basis_positions(market, params.basis_window, params.basis_z_entry),
        "momentum": pipeline.momentum_positions(market, params.model, params.momentum_theta),
    }
    full["vote"] = pipeline.vote(full["calendar"], full["basis"], full["momentum"])
    stamps = market.minutes["Datetime"]
    with_index = ~market.no_index & (stamps >= "2025-06-01").to_numpy()
    rng = np.random.default_rng(23)
    rows = sorted(rng.choice(np.flatnonzero(with_index), 40, replace=False))

    mismatches = []
    for row in rows:
        now = stamps.iloc[row] + pd.Timedelta(minutes=1)
        got = live.targets(market.minutes, index_minutes, now, params)
        for name, positions in full.items():
            if getattr(got, name) != int(positions[row]):
                mismatches.append((stamps.iloc[row], name, getattr(got, name), int(positions[row])))
    assert not mismatches

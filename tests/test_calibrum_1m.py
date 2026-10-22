from __future__ import annotations

import numpy as np
import pandas as pd

from src.lab.calibrum_1m import basis, momentum
from src.lab.calibrum_1m.grid import completes_bar, crosses_roll, last_row_of_contract, spread_to_minutes


def test_bar_decision_takes_effect_on_the_bars_last_minute() -> None:
    labels = pd.Series(pd.to_datetime(
        ["2024-03-12 09:00"] * 3 + ["2024-03-12 09:30"] * 2
    ))
    by_label = pd.Series([1.0, -1.0], index=pd.to_datetime(["2024-03-12 09:00", "2024-03-12 09:30"]))

    assert completes_bar(labels).tolist() == [False, False, True, False, True]
    assert spread_to_minutes(labels, by_label).tolist() == [0.0, 0.0, 1.0, 1.0, -1.0]


def test_contract_end_and_roll_crossing() -> None:
    contracts = pd.Series(["F1", "F1", "F2", "F2"])

    assert last_row_of_contract(contracts).tolist() == [False, True, False, False]
    assert crosses_roll(np.array([1.0, 1.0, 0.0, 0.0]), contracts).tolist() == [False, False, True, False]
    assert not crosses_roll(np.array([1.0, 0.0, 1.0, 1.0]), contracts).any()


def test_ridge_with_zero_penalty_is_least_squares_on_standardised_features() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 3))
    y = x @ np.array([0.5, -0.2, 0.1]) + 0.3 + rng.normal(scale=0.1, size=400)

    model = momentum.fit_ridge(x, y, lam=0.0)
    z = model.standardize(x)
    expected = np.linalg.lstsq(np.c_[np.ones(len(z)), z], y, rcond=None)[0]

    assert np.allclose([model.beta0, *model.beta], expected)
    assert np.all(np.abs(momentum.fit_ridge(x, y, lam=10.0).beta) < np.abs(model.beta))


def test_momentum_enters_on_decisions_and_stops_at_any_minute() -> None:
    close = np.array([100.0, 100.0, 95.0, 89.0, 89.0, 89.0])
    decision = np.array([True, False, False, False, True, False])
    score = np.array([0.5, np.nan, np.nan, np.nan, 0.5, np.nan])
    no_cut = np.zeros(6, dtype=bool)

    out = momentum.positions(close, decision, score, no_cut, theta=0.2, stop_points=10.0)

    # Long at the first decision, stopped at the minute 11 points down, re-entered at the next decision.
    assert out.tolist() == [1, 1, 1, 0, 1, 1]


def test_basis_reverses_after_min_hold_and_flat_rows_reset() -> None:
    close = np.full(6, 100.0)
    decision = np.ones(6, dtype=bool)
    z = np.array([-2.0, 0.5, 2.0, 2.0, 0.5, -2.0])
    flat = np.array([False, False, False, False, True, False])

    out = basis.positions(close, decision, z, flat, z_entry=1.5, min_hold=2)

    assert out.tolist() == [1, 1, -1, -1, 0, 1]

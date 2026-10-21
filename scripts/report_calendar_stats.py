#!/usr/bin/env python3
"""Per-leg Calendar session statistics on the in-sample DNSE cache, for report chapter 1."""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from src.domain.strategy.calendar_rules import (  # noqa: E402
    is_expiry_thursday,
    is_pre_holiday,
    is_regular_monday,
    is_start_of_month,
)

FUTURES = WORKSPACE / "data/dnse/derivative_vn30f1m_30m.parquet"
START, END = "2021-06-01", "2022-12-30 23:59"
PERMUTATIONS = 20_000


def daily_sessions() -> pd.DataFrame:
    bars = pd.read_parquet(FUTURES)
    bars["Datetime"] = pd.to_datetime(bars["Datetime"])
    bars = bars[(bars.Datetime >= START) & (bars.Datetime <= END)]
    days = bars.groupby(bars.Datetime.dt.date).agg(open=("Open", "first"), close=("Close", "last"))
    days["previous_close"] = days.close.shift()
    days = days.dropna()
    days["close_to_close"] = days.close - days.previous_close
    days["open_to_close"] = days.close - days.open
    days["gap"] = days.open - days.previous_close
    return days


def describe(name: str, values: pd.Series, population: pd.Series, rng: np.random.Generator) -> None:
    n = len(values)
    mean = values.mean()
    t_stat = mean / (values.std(ddof=1) / np.sqrt(n))
    draws = np.array([rng.choice(population.values, n, replace=False).mean() for _ in range(PERMUTATIONS)])
    p_value = (draws <= mean).mean() if mean < 0 else (draws >= mean).mean()
    print(f"{name:22s} n={n:4d}  mean={mean:+7.2f}  up={(values > 0).mean():4.0%}  t={t_stat:+5.2f}  perm p={p_value:.3f}")


def main() -> None:
    days = daily_sessions()
    dates = list(days.index)
    rng = np.random.default_rng(0)
    print(f"Sessions: {len(days)}, std close-to-close: {days.close_to_close.std():.1f} points")

    long_legs = {
        "Tuesday or Wednesday": np.array([d.weekday() in (1, 2) for d in dates]),
        "First 2 sessions": np.array([is_start_of_month(d) for d in dates]),
        "Expiry Thursday": np.array([is_expiry_thursday(d) for d in dates]),
        "Pre-holiday": np.array([is_pre_holiday(d) for d in dates]),
    }
    for name, mask in long_legs.items():
        describe(name, days.close_to_close[mask], days.close_to_close, rng)
    special = long_legs["First 2 sessions"] | long_legs["Expiry Thursday"] | long_legs["Pre-holiday"]
    describe("Any special day", days.close_to_close[special], days.close_to_close, rng)

    gap_down = (days.gap <= 0).to_numpy()
    monday = np.array([is_regular_monday(d) for d in dates]) & gap_down
    describe("Monday, gap <= 0", days.open_to_close[monday], days.open_to_close[gap_down], rng)


if __name__ == "__main__":
    main()

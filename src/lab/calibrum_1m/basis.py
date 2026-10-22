"""Basis sleeve: z-score of futures minus VN30 on 30-minute bars (PROTOCOL.md section 3.3).

    Basis_t = C_t(VN30F1M raw) - C_t(VN30), VN30 joined as of t
    Z_t     = (Basis_t - mean_W) / (std_W + 1e-6), at least 15 bars

The window restarts with every contract, and a contract trades only once it
has W bars. Sessions without index bars are left out of the series.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_PERIODS = 15
ATC_BAR = "14:30"


def zscores(futures_30m: pd.DataFrame, index_30m: pd.DataFrame, window: int) -> pd.Series:
    """Z by 30-minute bar label; NaN where the sleeve may not trade."""
    covered_days = set(index_30m["Datetime"].dt.date)
    bars = futures_30m.loc[futures_30m["Datetime"].dt.date.isin(covered_days), ["Datetime", "Close", "Contract"]]
    merged = pd.merge_asof(
        bars.sort_values("Datetime"),
        index_30m[["Datetime", "Close"]].rename(columns={"Close": "Spot"}).sort_values("Datetime"),
        on="Datetime",
        direction="backward",
    )
    basis = merged["Close"] - merged["Spot"]
    segment = merged["Contract"].ne(merged["Contract"].shift()).cumsum()
    grouped = basis.groupby(segment)
    mean = grouped.transform(lambda s: s.rolling(window, min_periods=MIN_PERIODS).mean())
    std = grouped.transform(lambda s: s.rolling(window, min_periods=MIN_PERIODS).std())
    z = (basis - mean) / (std + 1e-6)
    tradable = merged.groupby(segment).cumcount().ge(window)
    return pd.Series(z.where(tradable).to_numpy(), index=merged["Datetime"])


def positions(
    close: np.ndarray,
    decision: np.ndarray,
    z: np.ndarray,
    flat: np.ndarray,
    z_entry: float,
    z_exit: float = 0.0,
    min_hold: int = 2,
    stop_points: float = 14.0,
) -> np.ndarray:
    """Basis position on the minute grid.

    Decisions happen on rows that close a 30-minute bar other than 14:30. The
    stop is checked at every minute close and fills there. ``flat`` rows (an
    expiry session, or a session without index bars) hold no position.
    """
    out = np.zeros(len(close))
    current, held, entry = 0, 0, 0.0
    for i in range(len(close)):
        if flat[i]:
            current, held = 0, 0
            continue
        if current and current * (close[i] - entry) <= -stop_points:
            current, held = 0, 0
            continue
        if decision[i] and np.isfinite(z[i]):
            if current:
                held += 1
                if z[i] <= -z_entry and current == -1 and held >= min_hold:
                    current, held, entry = 1, 0, close[i]
                elif z[i] >= z_entry and current == 1 and held >= min_hold:
                    current, held, entry = -1, 0, close[i]
                elif abs(z[i]) <= z_exit and held >= min_hold:
                    current, held = 0, 0
            elif z[i] <= -z_entry:
                current, held, entry = 1, 0, close[i]
            elif z[i] >= z_entry:
                current, held, entry = -1, 0, close[i]
        out[i] = current
    return out

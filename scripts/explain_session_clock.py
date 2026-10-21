#!/usr/bin/env python3
"""Clock view of one session: what is known at each bar close, what each sleeve computes, what is traded.

Recomputes the Ridge score and the Shinji z-score with the same formulas as the frozen package, so the decision
behind each position can be read. Positions themselves come from the production path
(`generate_calibrum_position_stream`). Lab, DNSE data, majority vote.

    uv run python scripts/explain_session_clock.py --date 2021-06-03
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from lab_common import PACKAGE_DIR, load_research_frames  # noqa: E402
from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    _FrameFeed,
    _load_frozen_module,
    generate_calibrum_position_stream,
)


def ridge_score(frozen, frame: pd.DataFrame, model: dict) -> pd.Series:
    """Score on regular bars, exactly as in the frozen _ridge_positions."""
    hour_min = frame["Datetime"].dt.strftime("%H:%M")
    regular = frame.loc[hour_min.isin(frozen.REGULAR_CLOCKS)]
    close, open_ = regular["Close"].astype(float), regular["Open"].astype(float)
    high, low, volume = regular["High"].astype(float), regular["Low"].astype(float), regular["Volume"].astype(float)
    true_range = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(
        axis=1, skipna=False
    )
    atr14 = true_range.shift(1).rolling(14, min_periods=14).mean()
    day = regular["Datetime"].dt.normalize()
    first_open = open_.where(hour_min.loc[regular.index] == "09:00").groupby(day).transform("first")
    vwap = frozen._safe_ratio(
        (((high + low + close) / 3.0) * volume).groupby(day).cumsum(), volume.groupby(day).cumsum()
    )
    up = close.diff().clip(lower=0) ** 2
    down = close.diff().clip(upper=0) ** 2
    up4, down4 = up.rolling(4, min_periods=4).sum(), down.rolling(4, min_periods=4).sum()
    features = np.column_stack([
        frozen._safe_ratio(close - vwap, atr14),
        frozen._safe_ratio(close - first_open, atr14),
        frozen._safe_ratio(close - close.rolling(4, min_periods=4).mean(), atr14),
        frozen._safe_ratio(up4 - down4, up4 + down4),
        frozen._safe_ratio(close - open_, atr14),
    ])
    scaled = np.clip((features - model["ridge_centers"]) / model["ridge_scales"], -8.0, 8.0)
    score = model["ridge_intercept"] + scaled @ model["ridge_coef"]
    return pd.Series(score, index=regular.index).reindex(frame.index)


def shinji_z(futures: pd.DataFrame, spot: pd.DataFrame, window: int = 40) -> pd.Series:
    """Basis z-score per contract (Shinji roll guard), on sessions with index bars."""
    spot_days = set(spot["Datetime"].dt.date)
    out = pd.Series(np.nan, index=futures.index)
    covered = futures[futures["Datetime"].dt.date.isin(spot_days)]
    for _, segment in covered.groupby(covered["Contract"].ne(covered["Contract"].shift()).cumsum()):
        merged = pd.merge_asof(
            segment.sort_values("Datetime"),
            spot[["Datetime", "Close"]].rename(columns={"Close": "Spot"}).sort_values("Datetime"),
            on="Datetime",
            direction="backward",
        )
        basis = pd.Series(merged["Close"].to_numpy(float) - merged["Spot"].to_numpy(float))
        mean = basis.rolling(window, min_periods=15).mean()
        std = basis.rolling(window, min_periods=15).std() + 1e-6
        out.loc[segment.index] = ((basis - mean) / std).to_numpy()
    return out


def close_time(label: pd.Timestamp) -> str:
    if label.strftime("%H:%M") == "14:30":
        return "14:45"
    if label.strftime("%H:%M") == "11:30":
        return "11:30"
    return (label + timedelta(minutes=30)).strftime("%H:%M")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2021-06-03")
    args = parser.parse_args()
    session = date.fromisoformat(args.date)

    futures, spot, _ = load_research_frames("dnse", date(2021, 6, 1), date(2022, 12, 30), allow_fetch=False)
    stream, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR)
    frozen = _load_frozen_module(Path(PACKAGE_DIR))
    model = frozen._load_model(Path(PACKAGE_DIR) / "PS_V30_Vien_Calibrum_model.pt")
    clean = frozen._clean_frame(_FrameFeed(futures), "VN30F1M/30m")
    score = ridge_score(frozen, clean, model)
    z = shinji_z(clean.assign(Contract=futures["Contract"].to_numpy()), spot)

    table = pd.DataFrame({
        "Bar": stream.Datetime.dt.strftime("%H:%M"),
        "Known at": [close_time(t) for t in stream.Datetime],
        "Close": stream.Close,
        "Ridge score": score.round(2),
        "R": stream.Ridge,
        "Shinji Z": z.round(2),
        "S": stream.Shinji,
        "C": stream.Calendar,
        "R+S+C": stream.Ridge + stream.Shinji + stream.Calendar,
        "Pos (vote)": stream.Position,
    })
    table["Held next 30 min"] = table["Pos (vote)"]
    rows = stream.Datetime.dt.date == session
    start = int(np.flatnonzero(rows)[0]) - 1
    view = table.iloc[start : int(np.flatnonzero(rows)[-1]) + 1]
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(view.to_string(index=False))
    print(f"\nSession {session}; first row is the last bar of the previous session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

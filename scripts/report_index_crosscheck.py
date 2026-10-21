#!/usr/bin/env python3
"""Cross-check DNSE VN30 index bars against index ticks in algotradeDB, for report chapter 2."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(WORKSPACE / "scripts"))

from lab_common import load_research_frames  # noqa: E402
from src.adapters.data import PostgresResearchSource, align_to_bar_clock  # noqa: E402
from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    apply_session_rules,
    generate_calibrum_position_stream,
)
from src.lab.backtest import BacktestConfig, evaluate  # noqa: E402

SPOT = WORKSPACE / "data/dnse/index_vn30_30m.parquet"
PACKAGE_DIR = WORKSPACE / "PS_V30_Vien_Calibrum"
START, END = date(2021, 6, 1), date(2026, 10, 1)
PERIODS = {
    "In-sample": (date(2021, 6, 1), date(2022, 12, 30)),
    "OOS": (date(2023, 1, 1), date(2024, 12, 19)),
    "Forward": (date(2026, 1, 1), date(2026, 10, 1)),
}


def load_db_index() -> pd.DataFrame:
    source = PostgresResearchSource()
    try:
        years = [
            source.load_index_bars(max(START, date(year, 1, 1)), min(END, date(year, 12, 31)))
            for year in range(START.year, END.year + 1)
        ]
    finally:
        source.pool.close()
    frame = pd.concat(years, ignore_index=True)
    frame["Datetime"] = pd.to_datetime(frame["Datetime"]).astype("datetime64[ns]")
    for column in ("Open", "High", "Low", "Close"):
        frame[column] = frame[column].astype(float)
    frame["Volume"] = frame["Volume"].astype("int64")
    return frame


def flat(frame: pd.DataFrame) -> pd.Series:
    return (frame.Open == frame.High) & (frame.High == frame.Low) & (frame.Low == frame.Close)


def basis_metrics(futures: pd.DataFrame, spot: pd.DataFrame):
    stream, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR)
    position = apply_session_rules(stream["Shinji"].to_numpy(), stream.Datetime)
    frame = pd.DataFrame({"Datetime": stream.Datetime, "Close": stream.Close, "Position": position})
    return position, evaluate(frame, BacktestConfig(round_trip_fee_points=0.8, max_position=1.0)).metrics


def main() -> None:
    dnse = align_to_bar_clock(pd.read_parquet(SPOT))
    dnse = dnse[(dnse.Datetime.dt.date >= START) & (dnse.Datetime.dt.date <= END)].copy()
    dnse["Datetime"] = dnse["Datetime"].astype("datetime64[ns]")
    db = load_db_index()

    for name, frame in (("DNSE", dnse), ("DB", db)):
        label = frame.Datetime.dt.strftime("%H:%M")
        share = pd.crosstab(label, frame.Datetime.dt.year, values=flat(frame), aggfunc="mean") * 100
        print(f"\n{name}: share of flat index bars (O = H = L = C), % by bar and year")
        print(share.round(1).fillna("-").to_string())

    merged = dnse.merge(db[["Datetime", "Close"]], on="Datetime", suffixes=("", "_db"))
    merged["diff"] = merged.Close - merged.Close_db
    year = merged.Datetime.dt.year
    summary = pd.DataFrame({
        "bars": merged.groupby(year).size(),
        "median |diff|": merged["diff"].abs().groupby(year).median().round(2),
        "% > 1 pt": ((merged["diff"].abs() > 1).groupby(year).mean() * 100).round(1),
    })
    print("\nClose, DNSE minus DB, by year")
    print(summary.to_string())
    flat_close = merged[flat(merged)]
    print(f"Flat DNSE bars: median |diff| {flat_close['diff'].abs().median():.2f} points")
    big = merged[merged["diff"].abs() > 1]
    print(f"Bars > 1 point: {len(big)}, most in one session: {big.Datetime.dt.date.value_counts().max()}")
    print(f"1% and 99% quantiles of diff: {np.round(merged['diff'].quantile([0.01, 0.99]).to_numpy(), 2)}")

    print("\nBasis sleeve, lab, 1 contract, DNSE futures with each index source")
    for period, (start, end) in PERIODS.items():
        futures, spot, _ = load_research_frames("dnse", start, end, allow_fetch=False)
        db_spot = db[(db.Datetime.dt.date >= start) & (db.Datetime.dt.date <= end)].reset_index(drop=True)
        db_spot["Datetime"] = db_spot["Datetime"].astype(spot["Datetime"].dtype)
        pos_dnse, m_dnse = basis_metrics(futures, spot)
        pos_db, m_db = basis_metrics(futures, db_spot)
        print(
            f"{period:<10} DNSE {m_dnse.profit_after_fee:+7.1f} pts, Sharpe {m_dnse.sharpe_after_fee:.2f} | "
            f"DB {m_db.profit_after_fee:+7.1f} pts, Sharpe {m_db.sharpe_after_fee:.2f} | "
            f"same position on {(pos_dnse == pos_db).mean():.1%} of bars"
        )


if __name__ == "__main__":
    main()

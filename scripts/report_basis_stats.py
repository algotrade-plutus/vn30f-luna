#!/usr/bin/env python3
"""Basis (VN30F1M minus VN30) statistics on the in-sample DNSE cache, for report chapter 1."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
FUTURES = WORKSPACE / "data/dnse/derivative_vn30f1m_30m.parquet"
SPOT = WORKSPACE / "data/dnse/index_vn30_30m.parquet"
START, END = "2021-06-01", "2022-12-30 23:59"


def expiry_of(day: pd.Timestamp) -> pd.Timestamp:
    first = day.replace(day=1)
    return first + pd.Timedelta(days=(3 - first.weekday()) % 7 + 14)


def next_expiry(day: pd.Timestamp) -> pd.Timestamp:
    expiry = expiry_of(day)
    return expiry if day <= expiry else expiry_of(day + pd.offsets.MonthBegin(1))


def main() -> None:
    futures = pd.read_parquet(FUTURES)
    spot = pd.read_parquet(SPOT)
    for frame in (futures, spot):
        frame["Datetime"] = pd.to_datetime(frame["Datetime"])
    merged = pd.merge_asof(
        futures.sort_values("Datetime"),
        spot[["Datetime", "Close"]].rename(columns={"Close": "Spot"}).sort_values("Datetime"),
        on="Datetime",
        direction="backward",
    )
    merged = merged[(merged.Datetime >= START) & (merged.Datetime <= END)].dropna()
    basis = merged.Close - merged.Spot

    print(f"Bars: {len(basis)}")
    print(f"Share with |basis| <= 1 point: {(basis.abs() <= 1).mean():.1%}")
    print(f"Share with futures above spot: {(basis > 0).mean():.1%}")
    print(f"Mean basis: {basis.mean():.2f} points")
    print("Quantiles of |basis|:", basis.abs().quantile([0.5, 0.75, 0.9]).round(1).to_dict())

    sessions = merged.Datetime.dt.normalize()
    days_to_expiry = (sessions.map(next_expiry) - sessions).dt.days
    buckets = pd.cut(days_to_expiry, [-1, 2, 7, 14, 21, 40])
    table = pd.DataFrame({"bucket": buckets, "basis": basis, "abs_basis": basis.abs()})
    summary = table.groupby("bucket", observed=True).agg(
        mean_basis=("basis", "mean"), mean_abs_basis=("abs_basis", "mean"), bars=("basis", "size")
    )
    print(summary.round(2))


if __name__ == "__main__":
    main()

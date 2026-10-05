#!/usr/bin/env python3
"""Render a minimal price/fill and net-equity chart from a Calibrum report."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from src.adapters.data import PostgresResearchSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="Path to a Calibrum Plutus JSON report")
    parser.add_argument(
        "--output",
        default="reports/figures/calibrum_forward_2026-08-25_2026-10-01_trades",
        help="Output path without extension, relative to workspace unless absolute",
    )
    return parser.parse_args()


def _workspace_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE / path


def _load_bars(start: date, end: date) -> pd.DataFrame:
    database = PostgresResearchSource()
    try:
        return database.load_front_month_bars(start, end)
    finally:
        database.pool.close()


def main() -> None:
    args = parse_args()
    report_path = _workspace_path(args.report)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    start = date.fromisoformat(report["start_date"])
    end = date.fromisoformat(report["end_date"])
    bars = _load_bars(start, end)
    bars["Datetime"] = pd.to_datetime(bars["Datetime"])
    fills = pd.DataFrame(report["fills"])
    if not fills.empty:
        fills["timestamp"] = pd.to_datetime(fills["timestamp"])
        fills["price"] = fills["price"].astype(float)
        fills["side"] = fills["side"].astype(str).str.lower()
    daily = pd.DataFrame(report["daily_equity"])
    daily["date"] = pd.to_datetime(daily["date"])

    figure, (price_axis, equity_axis) = plt.subplots(
        2,
        1,
        figsize=(12, 7),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 2]},
        layout="constrained",
    )
    price_axis.plot(bars["Datetime"], bars["Close"], color="#1f2937", linewidth=1.2)
    if not fills.empty:
        buy = fills.loc[fills["side"] == "buy"]
        sell = fills.loc[fills["side"] == "sell"]
        price_axis.scatter(
            buy["timestamp"], buy["price"], marker="^", s=42, color="#16803c",
            label="Buy fill", zorder=3,
        )
        price_axis.scatter(
            sell["timestamp"], sell["price"], marker="v", s=42, color="#bb1e2d",
            label="Sell fill", zorder=3,
        )
    price_axis.set_ylabel("VN30F points")
    price_axis.set_title(
        "Calibrum forward replay — price and Plutus fills\n"
        "1 contract | raw front-month roll diagnostic | causal one-bar delay"
    )
    price_axis.legend(loc="upper left", frameon=True)
    price_axis.grid(True, alpha=0.3)

    initial = float(report["initial_capital"])
    equity_axis.plot(
        daily["date"], daily["equity"] / initial,
        color="#1769aa", linewidth=1.7,
        label=(
            f"Net equity — return {report['return_pct']:+.2f}% | "
            f"Sharpe {report['sharpe']:.2f}"
        ),
    )
    equity_axis.axhline(1.0, color="#6b7280", linewidth=0.8, linestyle="--")
    equity_axis.set_ylabel("Equity / initial capital")
    equity_axis.set_xlabel("Date")
    equity_axis.legend(loc="upper left", frameon=True)
    equity_axis.grid(True, alpha=0.3)
    equity_axis.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    equity_axis.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    figure.autofmt_xdate()

    output = _workspace_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output.with_suffix(".png"), dpi=180, bbox_inches="tight")
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)
    print(f"PNG: {output.with_suffix('.png')}")
    print(f"PDF: {output.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()

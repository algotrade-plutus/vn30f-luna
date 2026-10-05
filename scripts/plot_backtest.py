#!/usr/bin/env python3
"""Render the Step 4 in-sample equity figure from a Plutus report.

The figure deliberately contains one net-of-Plutus-charges curve.  It does not
invent a gross or fee-free comparator, and it does not splice the separately
funded out-of-sample account into the in-sample account.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
REPORT_PATH = WORKSPACE / "reports" / "step4_insample_report.json"
FIGURES = WORKSPACE / "reports" / "figures"


def _load() -> tuple[dict, pd.DataFrame]:
    if not REPORT_PATH.is_file():
        raise FileNotFoundError(f"Run `make step4` first: {REPORT_PATH}")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    frame = pd.DataFrame(report["daily_equity"])
    if frame.empty:
        raise ValueError("The Step 4 report has no daily equity observations")
    frame["date"] = pd.to_datetime(frame["date"])
    return report, frame


def main() -> None:
    report, frame = _load()
    initial_capital = float(report["initial_capital"])
    equity_index = frame["equity"] / initial_capital

    figure, axis = plt.subplots(figsize=(12.5, 5.2))
    axis.plot(
        frame["date"],
        equity_index,
        color="#1f77b4",
        linewidth=1.7,
        label=(
            f"Calibrum IS — Sharpe {float(report['sharpe']):.2f} "
            f"| net return {float(report['return_pct']):.1f}%"
        ),
    )
    axis.axhline(1.0, color="#6b7280", linestyle="--", linewidth=1.0)
    axis.set_xlabel("Date")
    axis.set_ylabel("Equity / initial capital")
    axis.grid(True, color="#a3a3a3", linewidth=0.7, alpha=0.9)
    axis.legend(loc="upper left", frameon=True)
    figure.autofmt_xdate(rotation=30, ha="right")
    figure.text(
        0.99,
        0.015,
        "Execution: modelled soft fill; no historical order-book depth",
        ha="right",
        va="bottom",
        fontsize=8.5,
        color="#4b5563",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))

    FIGURES.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf"):
        destination = FIGURES / f"step4_insample_equity.{suffix}"
        figure.savefig(destination, dpi=200, bbox_inches="tight")
        print(f"Saved {destination}")
    plt.close(figure)


if __name__ == "__main__":
    main()

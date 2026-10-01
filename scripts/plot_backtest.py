#!/usr/bin/env python3
"""Plot the equity series already emitted by the real Plutus research runs."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
REPORTS = WORKSPACE / "reports"
FIGURES = REPORTS / "figures"


def _load(name: str) -> tuple[dict, pd.DataFrame]:
    path = REPORTS / name
    if not path.is_file():
        raise FileNotFoundError(f"Run the corresponding backtest first: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    frame = pd.DataFrame(report["daily_equity"])
    frame["date"] = pd.to_datetime(frame["date"])
    return report, frame


def main() -> None:
    in_sample, is_frame = _load("step4_insample_report.json")
    out_sample, oos_frame = _load("step6_outsample_report.json")
    FIGURES.mkdir(parents=True, exist_ok=True)

    figure, axis = plt.subplots(figsize=(14, 6))
    axis.plot(
        is_frame["date"],
        is_frame["equity"] / 1_000_000,
        label=f"In-sample — Sharpe {in_sample['sharpe']:.2f}",
        color="#2563eb",
        linewidth=1.5,
    )
    # OOS starts from a fresh 100m account by design; do not splice it into the
    # IS wealth curve as though it were one continuously traded account.
    axis.plot(
        oos_frame["date"],
        oos_frame["equity"] / 1_000_000,
        label=f"Out-of-sample — Sharpe {out_sample['sharpe']:.2f}",
        color="#ea580c",
        linewidth=1.5,
    )
    axis.axhline(100, color="#64748b", linestyle="--", linewidth=1, label="Initial 100m VND")
    axis.axvline(pd.Timestamp("2023-01-01"), color="#0f172a", linestyle=":", linewidth=1)
    axis.set_title("Alpha Luna — equity from real Plutus ExchangeSession runs")
    axis.set_xlabel("Date")
    axis.set_ylabel("Derivatives deposit (million VND)")
    axis.grid(alpha=0.25)
    axis.legend(loc="upper left")
    axis.text(
        0.99,
        0.02,
        "Execution evidence: MODELLED_SOFT_NO_BOOK_DEPTH",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        color="#475569",
    )
    figure.tight_layout()
    destination = FIGURES / "plutus_backtest_performance.png"
    figure.savefig(destination, dpi=160, bbox_inches="tight")
    plt.close(figure)
    print(f"Saved {destination}")


if __name__ == "__main__":
    main()

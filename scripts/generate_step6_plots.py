#!/usr/bin/env python3
"""Step 6 figure: Sharpe after fee by period for each sleeve and for the two ensembles (lab, per contract)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from generate_report_plots import COLORS, INK_2, OUT_DIR, style  # noqa: E402
from lab_common import PACKAGE_DIR, load_research_frames  # noqa: E402
from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    apply_session_rules,
    generate_calibrum_position_stream,
)
from src.lab.backtest import BacktestConfig, evaluate  # noqa: E402

PERIODS = {
    "In-sample\n2021-06 to 2022-12": (date(2021, 6, 1), date(2022, 12, 30)),
    "OOS\n2023 to 2024": (date(2023, 1, 1), date(2024, 12, 19)),
    "Forward\n2026-01 to 2026-10": (date(2026, 1, 1), date(2026, 10, 1)),
}


def sharpe(stamps: pd.Series, close: pd.Series, position: np.ndarray, scale: int) -> float:
    stream = pd.DataFrame({"Datetime": stamps, "Close": close, "Position": position})
    return evaluate(stream, BacktestConfig(round_trip_fee_points=0.8, max_position=float(scale))).metrics.sharpe_after_fee


def main() -> int:
    style()
    rows: dict[str, dict[str, float]] = {}
    for label, (start, end) in PERIODS.items():
        futures, spot, _ = load_research_frames("dnse", start, end, allow_fetch=False)
        vote, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR)
        total, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR, ensemble_mode="sum")
        # Code names in the stream: Ridge = Momentum, Shinji = Basis (report names).
        row = {
            label: sharpe(vote.Datetime, vote.Close, apply_session_rules(vote[name].to_numpy(), vote.Datetime), 1)
            for label, name in (("Momentum", "Ridge"), ("Basis", "Shinji"), ("Calendar", "Calendar"))
        }
        row["Vote"] = sharpe(vote.Datetime, vote.Close, vote.Position.to_numpy(), 1)
        row["Sum"] = sharpe(total.Datetime, total.Close, total.Position.to_numpy(), 3)
        rows[label] = row
    table = pd.DataFrame(rows).T
    print(table.round(2))

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6), sharey=True)
    x = np.arange(len(table))
    for ax, names, title in (
        (axes[0], ["Momentum", "Basis", "Calendar"], "Single sleeves"),
        (axes[1], ["Sum", "Vote"], "Ensembles"),
    ):
        for name in names:
            values = table[name].to_numpy()
            ax.plot(x, values, color=COLORS[name], lw=2, marker="o", markersize=8, label=name)
            ax.annotate(
                f"{name} {values[-1]:+.2f}", (x[-1], values[-1]), xytext=(10, 0),
                textcoords="offset points", va="center", fontsize=11,
            )
        ax.axhline(0, color=INK_2, lw=0.8)
        ax.set_xticks(x, table.index)
        ax.set_xlim(-0.3, len(table) - 0.3)
        ax.set_title(title)
        ax.legend(loc="lower left")
    axes[0].set_ylabel("Sharpe after fee")
    fig.suptitle("Sharpe by period, lab, per contract", x=0.01, ha="left", fontweight="bold", fontsize=14)
    fig.tight_layout()
    path = OUT_DIR / "step6_sharpe_by_period.png"
    fig.savefig(path, dpi=200)
    print(f"Figure: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

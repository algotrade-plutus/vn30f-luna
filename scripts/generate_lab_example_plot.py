#!/usr/bin/env python3
"""Illustrate lab bar accounting on one session (vote, 2021-06-03): price, held position, fees and net per bar."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from generate_report_plots import INK, INK_2, OUT_DIR, SURFACE, style  # noqa: E402
from lab_common import load_research_frames, run_lab_backtest  # noqa: E402

SESSION = date(2021, 6, 3)
LONG = "#2a78d6"
GAIN, LOSS = "#2a78d6", "#e34948"


def main() -> int:
    style()
    futures, spot, _ = load_research_frames("dnse", date(2021, 6, 1), date(2022, 12, 30), allow_fetch=False)
    result, _, _ = run_lab_backtest(futures, spot, ensemble_mode="vote")
    frame = result.frame.reset_index(drop=True)
    day = frame.index[frame.Datetime.dt.date == SESSION]
    rows = frame.loc[day[0] - 1 : day[-1]].reset_index(drop=True)  # previous close + the session
    x = np.arange(len(rows))
    labels = [f"{t:%m-%d}\n{t:%H:%M}" if i == 0 else f"{t:%H:%M}" for i, t in enumerate(rows.Datetime)]

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(12, 7.4), sharex=True, gridspec_kw={"height_ratios": [2.2, 1.3]})
    for i in range(1, len(rows)):
        if rows.ExecutedPosition[i] != 0:
            top.axvspan(x[i - 1], x[i], color=LONG, alpha=0.12, lw=0)
    top.plot(x, rows.Close, color=INK, lw=2, marker="o", markersize=6, zorder=3)
    top.set_ylabel("Close (index points)")
    top.set_title("Lab accounting on one session: vote, 3 June 2021")
    span = rows.Close.max() - rows.Close.min()
    for i in range(1, len(rows)):
        change = rows.Position[i] - rows.Position[i - 1]
        if change:
            text = "Exit to flat\nfee 0.4" if rows.Position[i] == 0 else "Buy\nfee 0.4"
            top.annotate(
                text, (x[i], rows.Close[i]), xytext=(0, 34 if change > 0 else -46), textcoords="offset points",
                ha="center", fontsize=11, color=INK,
                arrowprops={"arrowstyle": "-", "color": INK_2, "lw": 1},
            )
    top.text(0.5, rows.Close.max() + 0.06 * span, "shaded = position held (long 1 contract)", fontsize=10, color=INK_2)
    top.set_ylim(rows.Close.min() - 0.25 * span, rows.Close.max() + 0.25 * span)

    net = rows.NetGain.to_numpy().copy()
    net[0] = 0.0  # previous session's last bar is context only
    colors = [GAIN if value >= 0 else LOSS for value in net]
    bottom.bar(x[1:], net[1:], color=colors[1:], width=0.6)
    for i in range(1, len(rows)):
        if net[i] != 0:
            text = f"{net[i]:+.1f}"
            if rows.FeeCost[i] and rows.GrossGain[i]:
                text = f"{rows.GrossGain[i]:+.1f} − {rows.FeeCost[i]:.1f} = {net[i]:+.1f}"
            bottom.annotate(text, (x[i], net[i]), xytext=(0, 4 if net[i] > 0 else -16),
                            textcoords="offset points", ha="center", fontsize=10, color=INK)
    bottom.axhline(0, color=INK_2, lw=0.8)
    bottom.set_ylim(net.min() - 4, net.max() + 3)
    bottom.set_ylabel("Net per bar (points)")
    bottom.set_title(f"Net = held position × price change − fee.  Session total D = {net.sum():+.1f} points")
    bottom.set_xticks(x, labels)
    fig.tight_layout()
    path = OUT_DIR / "step2_lab_example.png"
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    print(rows[["Datetime", "Close", "Position", "ExecutedPosition", "GrossGain", "FeeCost", "NetGain"]].to_string())
    print(f"Figure: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

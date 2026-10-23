#!/usr/bin/env python3
"""Deck figure: where each sleeve and the C+B+M vote are long or short over one week.

Top panel: VN30F1M minute close. Below, one lane per sleeve and one for the
vote, blue where long and orange where short (step-5 parameters). The x-axis
counts trading minutes, so lunch breaks and nights take no space.

    uv run python scripts/plot_calibrum_positions.py --start 2026-08-10 --end 2026-08-14
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for path in (str(WORKSPACE), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

from run_calibrum_1m import _optimised_sleeves  # noqa: E402
from src.lab.calibrum_1m import pipeline  # noqa: E402

FIGURES = WORKSPACE / "reports" / "calibrum_1m" / "figures"
SURFACE, INK, MUTED, GRID, LANE = "#F3F1EA", "#14213D", "#5B6577", "#D9D3C3", "#E6E2D6"
LONG, SHORT = "#2a78d6", "#eb6834"
LANES = (("C", "Calendar"), ("B", "Basis"), ("M", "Momentum"), ("V", "Vote C+B+M"))
DPI = 200


def _runs(values: np.ndarray) -> list[tuple[int, int, float]]:
    """(start, stop, value) for each run of equal non-zero values."""
    edges = np.flatnonzero(np.diff(values) != 0) + 1
    starts = np.r_[0, edges]
    stops = np.r_[edges, len(values)]
    return [(a, b, values[a]) for a, b in zip(starts, stops) if values[a] != 0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2026-08-10")
    parser.add_argument("--end", default="2026-08-14")
    args = parser.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end) + pd.Timedelta(days=1)

    market = pipeline.load_market(end.date())
    sleeves, _ = _optimised_sleeves(market)
    frame = pd.DataFrame({"t": market.minutes["Datetime"], "close": market.close, **sleeves})
    frame["V"] = np.sign(frame["C"] + frame["B"] + frame["M"])
    frame = frame[(frame["t"] >= start) & (frame["t"] < end)].reset_index(drop=True)
    x = np.arange(len(frame))
    day_starts = frame.index[frame["t"].dt.date.ne(frame["t"].dt.date.shift())].to_numpy()

    plt.rcParams.update({"font.family": "Arial", "font.size": 17, "axes.edgecolor": GRID})
    size_px = (1664, 620)
    fig = plt.figure(figsize=(2 * size_px[0] / DPI, 2 * size_px[1] / DPI))
    fig.patch.set_facecolor(SURFACE)
    grid = fig.add_gridspec(1 + len(LANES), 1, height_ratios=[3.2] + [0.55] * len(LANES), hspace=0.18)

    price = fig.add_subplot(grid[0])
    price.plot(x, frame["close"], color=INK, linewidth=1.4)
    price.set_ylabel("VN30F1M", color=MUTED)
    price.grid(axis="y", color=GRID, linewidth=1)
    axes = [price]
    for row, (key, name) in enumerate(LANES, start=1):
        lane = fig.add_subplot(grid[row], sharex=price)
        lane.set_facecolor(LANE)
        for a, b, value in _runs(frame[key].to_numpy()):
            lane.axvspan(a, b, color=LONG if value > 0 else SHORT, linewidth=0)
        lane.set_yticks([])
        lane.set_ylabel(name, rotation=0, ha="right", va="center", color=INK,
                        fontweight="bold" if key == "V" else "normal", labelpad=12)
        axes.append(lane)
    for ax in axes:
        ax.set_facecolor(ax.get_facecolor() if ax is not price else SURFACE)
        for day in day_starts[1:]:
            ax.axvline(day, color=MUTED, linewidth=1)
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(False)
        ax.set_xlim(0, len(frame) - 1)
    for ax in axes[:-1]:
        ax.tick_params(labelbottom=False)
    ends = np.r_[day_starts[1:], len(frame)]
    axes[-1].set_xticks((day_starts + ends) / 2)
    axes[-1].set_xticklabels([frame["t"].iloc[d].strftime("%a %d %b") for d in day_starts])
    handles = [plt.Rectangle((0, 0), 1, 1, color=LONG), plt.Rectangle((0, 0), 1, 1, color=SHORT)]
    price.legend(handles, ["Long", "Short"], loc="upper left", frameon=False, ncol=2, labelcolor=INK)

    FIGURES.mkdir(parents=True, exist_ok=True)
    out = FIGURES / f"positions_{args.start}_{args.end}.png"
    fig.savefig(out, dpi=DPI, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.15)
    print(out)
    for key, name in LANES:
        values = frame[key].to_numpy()
        print(f"{name:12s} long {np.mean(values > 0):.0%}  short {np.mean(values < 0):.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

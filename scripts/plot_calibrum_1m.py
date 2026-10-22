#!/usr/bin/env python3
"""Deck figure: cumulative in-sample profit in VND of the seven combinations (step 4, starting parameters).

Reads reports/calibrum_1m/in_sample_baseline.json and writes
reports/calibrum_1m/figures/in_sample_equity.png at twice its slide size.
Two panels share one y-axis: the sleeves alone, then the pairs and all three.
Colours are the dataviz reference palette, checked all-pairs per panel on the
deck surface; every line is labelled at its end.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[1]
SOURCE = WORKSPACE / "reports" / "calibrum_1m" / "in_sample_baseline.json"
OUT = WORKSPACE / "reports" / "calibrum_1m" / "figures" / "in_sample_equity.png"
MILLION_VND_PER_POINT = 0.1  # 1 point = 100,000 VND

SURFACE, INK, MUTED, GRID = "#F3F1EA", "#14213D", "#5B6577", "#D9D3C3"
PANELS = (
    ("Each sleeve alone", {"C": "#2a78d6", "B": "#eb6834", "M": "#1baf7a"}),
    ("Pairs and all three", {"C+B": "#e87ba4", "C+M": "#008300", "B+M": "#eda100", "C+B+M": "#6250d6"}),
)
NAMES = {"C": "Calendar", "B": "Basis", "M": "Momentum"}
SIZE_PX = (1664, 600)


def main() -> int:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    curves = {
        combo: pd.Series(days).rename(index=pd.Timestamp).sort_index().cumsum() * MILLION_VND_PER_POINT
        for combo, days in payload["daily_net_points"].items()
    }
    top = max(curve.max() for curve in curves.values())
    bottom = min(0.0, min(curve.min() for curve in curves.values()))

    plt.rcParams.update({"font.family": "Arial", "font.size": 17, "axes.edgecolor": GRID})
    dpi = 200
    fig, axes = plt.subplots(1, 2, figsize=(2 * SIZE_PX[0] / dpi, 2 * SIZE_PX[1] / dpi), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    for ax, (title, colours) in zip(axes, PANELS):
        ax.set_facecolor(SURFACE)
        for combo, colour in colours.items():
            curve = curves[combo]
            width = 3.2 if combo == "C+B+M" else 2.2
            ax.plot(curve.index, curve.to_numpy(), color=colour, linewidth=width, solid_capstyle="round")
            label = NAMES.get(combo, combo)
            ax.annotate(
                f"{label}  {curve.iloc[-1]:+.0f}M",
                xy=(curve.index[-1], curve.iloc[-1]),
                xytext=(8, 0),
                textcoords="offset points",
                va="center",
                color=INK,
                fontweight="bold" if combo == "C+B+M" else "normal",
            )
        ax.set_title(title, loc="left", color=MUTED, fontsize=17, pad=12)
        ax.axhline(0, color=MUTED, linewidth=1)
        ax.grid(axis="y", color=GRID, linewidth=1)
        ax.set_ylim(bottom - 5, top + 10)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.set_xlim(curve.index[0], curve.index[-1] + pd.Timedelta(days=260))
    axes[0].set_ylabel("Cumulative net profit, million VND", color=MUTED)
    axes[0].yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0f}"))
    fig.tight_layout(w_pad=3)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=dpi, facecolor=SURFACE)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

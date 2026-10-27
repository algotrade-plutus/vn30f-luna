#!/usr/bin/env python3
"""Deck figure: drawdown of C+B+M against holding VN30F1M, step 6.

Each period is scored on its own, as in score_periods: equity starts at 100
million VND at the period's first session, profits are not reinvested, and the
drawdown is equity over its running peak minus one. The longest drawdown of
each period (sessions from a peak to the next new peak, an open one at the end
included, as plutus.evaluation.metrics.longest_drawdown_duration counts it) is
bracketed with its length, and the deepest point is labelled.

Reads reports/calibrum_1m/oos2.json and benchmarks.json; writes
reports/calibrum_1m/figures/full_drawdown.png.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from scripts.plot_calibrum_1m import (  # noqa: E402
    ACCENT,
    BENCHMARKS,
    DPI,
    FONT,
    FONT_SIZE,
    FIGURES,
    GRID,
    INK,
    MUTED,
    REPORTS,
    SHADE,
    SURFACE,
)
from src.lab.calibrum_1m import pipeline  # noqa: E402

COMBO, COLOUR = "C+B+M", ACCENT
NAMES = {"in_sample": "In-sample", "valid": "Valid", "oos1": "OOS 1", "oos2": "OOS 2"}
CAPITAL_MILLION = 100.0
POINT_MILLION = 0.1


def _daily(payload: dict, name: str) -> pd.Series:
    return pd.Series(payload[name]).rename(index=pd.Timestamp).sort_index()


def drawdown(daily_points: pd.Series) -> pd.Series:
    """Equity over its running peak minus one, in percent, from 100 million VND at the first session."""
    equity = CAPITAL_MILLION + daily_points.cumsum() * POINT_MILLION
    peak = equity.cummax().clip(lower=CAPITAL_MILLION)
    return (equity / peak - 1.0) * 100.0


def longest(daily_points: pd.Series) -> tuple[int, pd.Timestamp, pd.Timestamp]:
    """Longest run below a peak in sessions, with the peak session and the session it ends on.

    The starting capital is the peak before the first session, as in Plutus.
    """
    equity = CAPITAL_MILLION + daily_points.cumsum() * POINT_MILLION
    best, peak, peak_at = (0, daily_points.index[0], daily_points.index[0]), CAPITAL_MILLION, -1
    for i, (day, value) in enumerate(equity.items()):
        if value > peak:
            peak, peak_at = value, i
        elif i - peak_at > best[0]:
            start = daily_points.index[peak_at] if peak_at >= 0 else daily_points.index[0]
            best = (i - peak_at, start, day)
    return best


def main() -> int:
    strategy = json.loads((REPORTS / "oos2.json").read_text(encoding="utf-8"))
    combos = pd.DataFrame(strategy["combos"])
    daily = _daily(strategy["daily_net_points"], COMBO)
    hold = _daily(json.loads((REPORTS / "benchmarks.json").read_text(encoding="utf-8"))["daily_net_points"], "VN30F1M")
    windows = pipeline.periods(pipeline.load_config())

    plt.rcParams.update({"font.family": FONT, "font.size": FONT_SIZE, "axes.edgecolor": GRID})
    fig, ax = plt.subplots(figsize=(2 * 1664 / DPI, 2 * 640 / DPI))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    first, last = daily.index[0], daily.index[-1]
    ax.axvspan(pd.Timestamp("2025-01-01"), last, color=SHADE, linewidth=0)

    parts, holds = [], []
    for name, (start, end) in windows.items():
        inside = daily[(daily.index >= start) & (daily.index <= end)]
        reference = hold.reindex(inside.index, fill_value=0.0)
        parts.append((name, start, inside, drawdown(inside)))
        holds.append(drawdown(reference))
    bottom = min(min(series.min() for series in holds), min(part[3].min() for part in parts))
    top = 0.0

    for (name, start, inside, under), reference in zip(parts, holds):
        if start > first:
            ax.axvline(start, color=GRID, linewidth=1.5)
        ax.text(max(start, first) + pd.Timedelta(days=20), 0.17 * -bottom, NAMES[name], color=MUTED, fontsize=16)
        ax.fill_between(under.index, under.to_numpy(), 0.0, color=COLOUR, alpha=0.35, linewidth=0, step="post")
        ax.plot(under.index, under.to_numpy(), color=COLOUR, linewidth=2.0, drawstyle="steps-post")
        colour, dash = BENCHMARKS["VN30F1M"]
        ax.plot(reference.index, reference.to_numpy(), color=colour, linewidth=1.6, linestyle=dash)

        row = combos[(combos["combo"] == COMBO) & (combos["period"] == name)].iloc[0]
        sessions, peak_day, end_day = longest(inside)
        assert sessions == int(row["longest_drawdown_sessions"]), (name, sessions, row["longest_drawdown_sessions"])
        deepest = under.idxmin()
        ax.annotate(f"{under.min():.1f}%".replace("-", "\u2212"), xy=(deepest, under.min()), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", color=INK, fontsize=15,
                    bbox={"boxstyle": "round,pad=0.2", "facecolor": SURFACE, "edgecolor": "none"})
        # The longest drawdown sits in its own lane above zero, clear of the curves.
        level = 0.04 * -bottom
        ax.annotate("", xy=(peak_day, level), xytext=(end_day, level),
                    arrowprops={"arrowstyle": "|-|", "color": INK, "linewidth": 1.4, "mutation_scale": 6})
        ax.text(end_day + pd.Timedelta(days=12), level, f"{sessions} sessions",
                ha="left", va="center", color=INK, fontsize=15, fontweight="bold")

    ax.plot([], [], color=COLOUR, linewidth=2.0, label=f"{COMBO} drawdown")
    ax.plot([], [], color=BENCHMARKS["VN30F1M"][0], linestyle=BENCHMARKS["VN30F1M"][1], linewidth=1.6,
            label="VN30F1M hold drawdown")
    ax.plot([], [], color=INK, marker="|", markersize=10, linewidth=1.4, label="Longest drawdown")
    ax.legend(loc="lower left", frameon=False, labelcolor=INK, ncol=3, bbox_to_anchor=(0, -0.02))

    ax.axhline(0, color=MUTED, linewidth=1)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_ylim(bottom * 1.18, top + 0.25 * -bottom)
    ax.set_xticks([pd.Timestamp(year=y, month=1, day=1) for y in range(first.year + 1, last.year + 1)])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_xlim(first, last + pd.Timedelta(days=30))
    ax.set_ylabel("Below previous peak, % of equity", color=MUTED)
    ax.set_yticks(range(int(bottom // 10) * 10, 1, 10))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0f}%".replace("-", "\u2212")))
    fig.tight_layout()
    out = FIGURES / "full_drawdown.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

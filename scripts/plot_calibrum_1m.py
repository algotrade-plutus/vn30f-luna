#!/usr/bin/env python3
"""Deck figures: cumulative profit in million VND of the seven combinations.

- in_sample_equity_*.png (step 4): in-sample with the starting parameters,
  from reports/calibrum_1m/in_sample_baseline.json.
- full_equity_*.png: in-sample to OOS 2 with the step-5 parameters,
  from reports/calibrum_1m/oos2.json, with the periods marked and the
  out-of-sample years shaded.
- period_equity_<period>.png (steps 5 and 6): one period at a time with the
  step-5 parameters, each sleeve and all three, every curve starting at zero
  at the period's first session.

Each figure is split into two wide images, written at twice their slide size:
the sleeves alone (``*_sleeves.png``), then the pairs and all three (``*_combos.png``). Colours are the dataviz
reference palette, checked all-pairs per panel on the deck surface; every line
is labelled at its end. Buy-and-hold VN30F1M and VN30 (one contract's worth,
reports/calibrum_1m/benchmarks.json) are drawn in grey on both panels, rebased
to zero at the figure's first session.
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
REPORTS = WORKSPACE / "reports" / "calibrum_1m"
FIGURES = REPORTS / "figures"
MILLION_VND_PER_POINT = 0.1  # 1 point = 100,000 VND

SURFACE, INK, MUTED, GRID, SHADE = "#F3F1EA", "#14213D", "#5B6577", "#D9D3C3", "#E6E2D6"
PANELS = (
    ("Each sleeve alone", {"C": "#2a78d6", "B": "#eb6834", "M": "#1baf7a"}),
    ("Pairs and all three", {"C+B": "#e87ba4", "C+M": "#008300", "B+M": "#eda100", "C+B+M": "#6250d6"}),
)
NAMES = {"C": "Calendar", "B": "Basis", "M": "Momentum", "VN30F1M": "VN30F1M hold", "VN30": "VN30 hold"}
BENCHMARKS = {"VN30F1M": (INK, (0, (1.5, 2.5))), "VN30": (MUTED, (0, (6, 3)))}
PERIODS = (
    ("In-sample", "2020-06-01"),
    ("Valid", "2023-01-01"),
    ("OOS 1", "2025-01-01"),
    ("OOS 2", "2026-01-01"),
)
DPI = 200


def _curves(source: Path) -> dict[str, pd.Series]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    return {
        combo: pd.Series(days).rename(index=pd.Timestamp).sort_index().cumsum() * MILLION_VND_PER_POINT
        for combo, days in payload["daily_net_points"].items()
    }


def _benchmarks(first: pd.Timestamp, last: pd.Timestamp) -> dict[str, pd.Series]:
    source = REPORTS / "benchmarks.json"
    if not source.exists():
        return {}
    payload = json.loads(source.read_text(encoding="utf-8"))["daily_net_points"]
    out = {}
    for name, days in payload.items():
        daily = pd.Series(days).rename(index=pd.Timestamp).sort_index()
        out[name] = daily[(daily.index >= first) & (daily.index <= last)].cumsum() * MILLION_VND_PER_POINT
    return out


def _label_positions(ends: dict[str, float], gap: float) -> dict[str, float]:
    """Spread end labels apart by at least ``gap`` while keeping their order."""
    placed: dict[str, float] = {}
    previous = None
    for combo, value in sorted(ends.items(), key=lambda item: item[1]):
        position = value if previous is None else max(value, previous + gap)
        placed[combo] = position
        previous = position
    return placed


def draw(source: Path, out_stem: Path, size_px: tuple[int, int], mark_periods: bool) -> list[Path]:
    """One wide figure per panel: ``<stem>_sleeves.png`` and ``<stem>_combos.png``."""
    curves = _curves(source)
    first = min(curve.index[0] for curve in curves.values())
    last = max(curve.index[-1] for curve in curves.values())
    references = _benchmarks(first, last)
    written = []
    plt.rcParams.update({"font.family": "Arial", "font.size": 17, "axes.edgecolor": GRID})
    for (title, colours), suffix in zip(PANELS, ("sleeves", "combos")):
        shown = {**{combo: curves[combo] for combo in colours}, **references}
        top = max(series.max() for series in shown.values())
        bottom = min(0.0, min(series.min() for series in shown.values()))
        span = top - bottom

        fig, ax = plt.subplots(figsize=(2 * size_px[0] / DPI, 2 * size_px[1] / DPI))
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)
        if mark_periods:
            ax.axvspan(pd.Timestamp("2025-01-01"), last, color=SHADE, linewidth=0)
            for name, start in PERIODS:
                stamp = pd.Timestamp(start)
                if stamp > first:
                    ax.axvline(stamp, color=GRID, linewidth=1.5)
                ax.text(max(stamp, first) + pd.Timedelta(days=20), top + 0.06 * span, name, color=MUTED, fontsize=16)
        for combo, colour in colours.items():
            curve = curves[combo]
            ax.plot(curve.index, curve.to_numpy(), color=colour, linewidth=3.2 if combo == "C+B+M" else 2.4,
                    solid_capstyle="round")
        for name, (colour, dash) in BENCHMARKS.items():
            if name in references:
                ax.plot(references[name].index, references[name].to_numpy(), color=colour, linewidth=1.8,
                        linestyle=dash)
        ends = {name: series.iloc[-1] for name, series in shown.items()}
        for combo, y in _label_positions(ends, gap=0.06 * span).items():
            ax.annotate(
                f"{NAMES.get(combo, combo)}  {ends[combo]:+.0f}M",
                xy=(shown[combo].index[-1], y),
                xytext=(10, 0),
                textcoords="offset points",
                va="center",
                color=MUTED if combo in BENCHMARKS else INK,
                fontweight="bold" if combo == "C+B+M" else "normal",
                annotation_clip=False,
            )
        ax.axhline(0, color=MUTED, linewidth=1)
        ax.grid(axis="y", color=GRID, linewidth=1)
        ax.set_ylim(bottom - 0.03 * span, top + (0.14 if mark_periods else 0.05) * span)
        ax.set_xticks([pd.Timestamp(year=y, month=1, day=1) for y in range(first.year + 1, last.year + 1)])
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.set_xlim(first, last + (last - first) * 0.17)
        ax.set_ylabel("Cumulative net profit, million VND", color=MUTED)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0f}"))
        fig.tight_layout()
        out = out_stem.with_name(f"{out_stem.name}_{suffix}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=DPI, facecolor=SURFACE)
        plt.close(fig)
        written.append(out)
    return written


PERIOD_LINES = {"C": "#2a78d6", "B": "#eb6834", "M": "#1baf7a", "C+B+M": "#6250d6"}


def draw_period(source: Path, start: str, end: str, out: Path, size_px: tuple[int, int] = (1664, 640)) -> Path:
    """Cumulative profit inside one period: each sleeve, all three, and buy and hold, all from zero."""
    payload = json.loads(source.read_text(encoding="utf-8"))["daily_net_points"]
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    curves = {}
    for name in PERIOD_LINES:
        daily = pd.Series(payload[name]).rename(index=pd.Timestamp).sort_index()
        curves[name] = daily[(daily.index >= first) & (daily.index <= last)].cumsum() * MILLION_VND_PER_POINT
    first, last = min(c.index[0] for c in curves.values()), max(c.index[-1] for c in curves.values())
    references = _benchmarks(first, last)
    shown = {**curves, **references}
    top = max(0.0, max(series.max() for series in shown.values()))
    bottom = min(0.0, min(series.min() for series in shown.values()))
    span = top - bottom

    plt.rcParams.update({"font.family": "Arial", "font.size": 17, "axes.edgecolor": GRID})
    fig, ax = plt.subplots(figsize=(2 * size_px[0] / DPI, 2 * size_px[1] / DPI))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for name, colour in PERIOD_LINES.items():
        ax.plot(curves[name].index, curves[name].to_numpy(), color=colour,
                linewidth=3.4 if name == "C+B+M" else 2.4, solid_capstyle="round")
    for name, (colour, dash) in BENCHMARKS.items():
        if name in references:
            ax.plot(references[name].index, references[name].to_numpy(), color=colour, linewidth=1.8, linestyle=dash)
    ends = {name: series.iloc[-1] for name, series in shown.items()}
    for name, y in _label_positions(ends, gap=0.065 * span).items():
        ax.annotate(f"{NAMES.get(name, name)}  {ends[name]:+.0f}M", xy=(shown[name].index[-1], y), xytext=(10, 0),
                    textcoords="offset points", va="center", annotation_clip=False,
                    color=MUTED if name in BENCHMARKS else INK, fontweight="bold" if name == "C+B+M" else "normal")
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_ylim(bottom - 0.04 * span, top + 0.06 * span)
    if (last - first).days > 400:
        ticks, fmt = [pd.Timestamp(year=y, month=1, day=1) for y in range(first.year + 1, last.year + 1)], "%Y"
    else:
        ticks = [d for d in pd.date_range(first.normalize().replace(day=1), last, freq="MS") if d.month in (1, 4, 7, 10)]
        fmt = "%b %Y"
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_xlim(first, last + (last - first) * 0.2)
    ax.set_ylabel("Cumulative net profit, million VND", color=MUTED)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0f}".replace("-", "\u2212")))
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    return out


def main() -> int:
    for path in draw(REPORTS / "in_sample_baseline.json", FIGURES / "in_sample_equity", (1664, 640), mark_periods=False):
        print(path)
    if (REPORTS / "oos2.json").exists():
        for path in draw(REPORTS / "oos2.json", FIGURES / "full_equity", (1664, 640), mark_periods=True):
            print(path)
        for name, (start, end) in {"in_sample": ("2020-06-01", "2022-12-31"), "valid": ("2023-01-01", "2024-12-31"),
                                   "oos1": ("2025-01-01", "2025-12-31"), "oos2": ("2026-01-01", "2026-12-31")}.items():
            print(draw_period(REPORTS / "oos2.json", start, end, FIGURES / f"period_equity_{name}.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

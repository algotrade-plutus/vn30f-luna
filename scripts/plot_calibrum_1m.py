#!/usr/bin/env python3
"""Deck figures: cumulative profit in million VND of the seven combinations.

- in_sample_equity_*.png (step 4): in-sample with the starting parameters,
  from reports/calibrum_1m/in_sample_baseline.json.
- full_equity_*.png: in-sample to OOS 2 with the step-5 parameters,
  from reports/calibrum_1m/oos2.json, with the periods marked and the
  out-of-sample years shaded.
- period_equity_<period>_*.png (steps 5 and 6): one period at a time with the
  step-5 parameters, the same two panels, every curve starting at zero at the
  period's first session.
- yearly_in_sample.png (step 4): in-sample net profit by year of the seven combinations.
- correlation_*.png: daily-profit correlation of the sleeves as heatmaps
  (in-sample with the starting values; each period with the step-5 ones).

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

# White, as the live dashboard: grey grid and text, one blue accent.
SURFACE, INK, MUTED, GRID, SHADE = "#FFFFFF", "#222222", "#888888", "#E1E1E1", "#F4F4F4"
ACCENT, ORANGE = "#3b5998", "#e08a3c"
FONT, FONT_SIZE = ["Verdana", "DejaVu Sans"], 15  # DejaVu fills glyphs Verdana lacks (⇔, θ)
PANELS = (
    ("Each sleeve alone", {"C": ACCENT, "B": ORANGE, "M": "#1baf7a"}),
    ("Pairs and all three", {"C+B": "#e87ba4", "C+M": "#008300", "B+M": "#eda100", "C+B+M": ACCENT}),
)
NAMES = {"C": "Calendar", "B": "Basis", "M": "Momentum", "VN30F1M": "VN30F1M hold", "VN30": "VN30 hold"}
BENCHMARKS = {"VN30F1M": (MUTED, (0, (1.5, 2.5))), "VN30": ("#BBBBBB", (0, (6, 3)))}
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
    plt.rcParams.update({"font.family": FONT, "font.size": FONT_SIZE, "axes.edgecolor": GRID})
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


def draw_period(source: Path, start: str, end: str, out_stem: Path, size_px: tuple[int, int] = (1664, 640)) -> list[Path]:
    """Cumulative profit inside one period, every line from zero: ``<stem>_sleeves.png`` and ``<stem>_combos.png``."""
    payload = json.loads(source.read_text(encoding="utf-8"))["daily_net_points"]
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    curves = {}
    for name in payload:
        daily = pd.Series(payload[name]).rename(index=pd.Timestamp).sort_index()
        curves[name] = daily[(daily.index >= lo) & (daily.index <= hi)].cumsum() * MILLION_VND_PER_POINT
    first, last = min(c.index[0] for c in curves.values()), max(c.index[-1] for c in curves.values())
    references = _benchmarks(first, last)
    written = []
    plt.rcParams.update({"font.family": FONT, "font.size": FONT_SIZE, "axes.edgecolor": GRID})
    for (_, colours), suffix in zip(PANELS, ("sleeves", "combos")):
        shown = {**{name: curves[name] for name in colours}, **references}
        top = max(0.0, max(series.max() for series in shown.values()))
        bottom = min(0.0, min(series.min() for series in shown.values()))
        span = top - bottom
        fig, ax = plt.subplots(figsize=(2 * size_px[0] / DPI, 2 * size_px[1] / DPI))
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)
        for name, colour in colours.items():
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
            ticks = [d for d in pd.date_range(first.normalize().replace(day=1), last, freq="MS") if d.month in (4, 7, 10)]
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
        out = out_stem.with_name(f"{out_stem.name}_{suffix}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=DPI, facecolor=SURFACE)
        plt.close(fig)
        written.append(out)
    return written


def draw_correlation(matrices: dict[str, dict], out: Path, size_px: tuple[int, int]) -> Path:
    """Daily-profit correlation of the three sleeves as a full matrix, one per title, on a fixed -1..+1 scale.

    Diverging blue (negative) to orange (positive) through a neutral grey at zero;
    every cell carries its value, and the colour scale under the matrices reads by itself.
    """
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("diverging", [ACCENT, SHADE, ORANGE])
    names = ["C", "B", "M"]
    labels = [NAMES[n] for n in names]
    plt.rcParams.update({"font.family": FONT, "font.size": FONT_SIZE + 1})
    fig, axes = plt.subplots(1, len(matrices), figsize=(2 * size_px[0] / DPI, 2 * size_px[1] / DPI))
    axes = [axes] if len(matrices) == 1 else list(axes)
    fig.patch.set_facecolor(SURFACE)
    for ax, (title, matrix) in zip(axes, matrices.items()):
        values = pd.DataFrame(matrix).loc[names, names].to_numpy(float)
        image = ax.imshow(values, cmap=cmap, vmin=-1, vmax=1)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{values[i, j]:+.2f}".replace("-", "\u2212").replace("+1.00", "1.00"), ha="center",
                        va="center", color=SURFACE if i == j else INK, fontsize=18, fontweight="bold")
        ax.set_xticks(range(3), labels, color=INK)
        ax.set_yticks(range(3), labels if ax is axes[0] else [""] * 3, color=INK)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xticks([0.5, 1.5], minor=True)
        ax.set_yticks([0.5, 1.5], minor=True)
        ax.grid(which="minor", color=SURFACE, linewidth=6)
        ax.tick_params(which="both", length=0)
        ax.set_title(title, color=INK, fontsize=22, pad=14)
    fig.tight_layout(rect=(0, 0.2, 1, 0.94))
    left = min(ax.get_position().x0 for ax in axes)
    right = max(ax.get_position().x1 for ax in axes)
    bar = fig.add_axes((left, 0.1, right - left, 0.035))
    scale = fig.colorbar(image, cax=bar, orientation="horizontal", ticks=[-1, 0, 1])
    scale.ax.set_xticklabels(["\u22121\nopposite", "0\nunrelated", "+1\ntogether"], color=MUTED, fontsize=FONT_SIZE)
    scale.ax.tick_params(length=0)
    ends = scale.ax.get_xticklabels()
    ends[0].set_horizontalalignment("left")
    ends[-1].set_horizontalalignment("right")
    scale.outline.set_visible(False)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    return out


def draw_yearly(yearly: dict[str, dict], out: Path, size_px: tuple[int, int]) -> Path:
    """Net profit by year of the seven combinations as grouped bars, one blue per year, light to dark.

    Only the bars of all three carry their value; C+B+M sits on a grey band.
    """
    combos = ["C", "B", "M", "C+B", "C+M", "B+M", "C+B+M"]
    years = sorted(yearly["C+B+M"])
    shades = ["#B4C1DE", "#7489BC", ACCENT][-len(years):]
    labels = {"2020": "2020 (Jun–Dec)"}
    plt.rcParams.update({"font.family": FONT, "font.size": FONT_SIZE + 1, "axes.edgecolor": GRID})
    fig, ax = plt.subplots(figsize=(2 * size_px[0] / DPI, 2 * size_px[1] / DPI))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    width = 0.27
    centres = [i + (0.4 if i >= 3 else 0) + (0.4 if i >= 6 else 0) for i in range(len(combos))]
    ax.axvspan(centres[-1] - 0.5, centres[-1] + 0.5, color=SHADE, linewidth=0)
    top = max(v for combo in combos for v in yearly[combo].values()) * MILLION_VND_PER_POINT
    for k, (year, colour) in enumerate(zip(years, shades)):
        xs = [c + (k - 1) * width for c in centres]
        values = [yearly[combo][year] * MILLION_VND_PER_POINT for combo in combos]
        ax.bar(xs, values, width=width, color=colour, edgecolor=SURFACE, linewidth=2, label=labels.get(year, year))
        ax.annotate(f"{values[-1]:.0f}", xy=(xs[-1], values[-1]), xytext=(0, 6), textcoords="offset points",
                    ha="center", va="bottom", color=INK, fontsize=FONT_SIZE - 3)
    ax.set_xticks(centres, combos, color=INK)
    for tick in ax.get_xticklabels()[-1:]:
        tick.set_fontweight("bold")
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_ylim(0, top * 1.22)
    ax.set_xlim(centres[0] - 0.6, centres[-1] + 0.6)
    ax.tick_params(colors=MUTED, length=0)
    ax.tick_params(axis="x", colors=INK)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_ylabel("Net profit, million VND", color=MUTED)
    ax.legend(loc="upper left", ncol=len(years), frameon=False, labelcolor=INK, handlelength=1.2, columnspacing=1.4)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    return out


def main() -> int:
    for path in draw(REPORTS / "in_sample_baseline.json", FIGURES / "in_sample_equity", (1664, 640), mark_periods=False):
        print(path)
    yearly = json.loads((REPORTS / "in_sample_baseline.json").read_text(encoding="utf-8"))["yearly_net_points"]
    print(draw_yearly(yearly, FIGURES / "yearly_in_sample.png", (980, 520)))
    if (REPORTS / "oos2.json").exists():
        for path in draw(REPORTS / "oos2.json", FIGURES / "full_equity", (1664, 640), mark_periods=True):
            print(path)
        for name, (start, end) in {"in_sample": ("2020-06-01", "2022-12-31"), "valid": ("2023-01-01", "2024-12-31"),
                                   "oos1": ("2025-01-01", "2025-12-31"), "oos2": ("2026-01-01", "2026-12-31")}.items():
            for path in draw_period(REPORTS / "oos2.json", start, end, FIGURES / f"period_equity_{name}"):
                print(path)
        periods = json.loads((REPORTS / "oos2.json").read_text(encoding="utf-8"))["correlation"]
        titles = {"in_sample": "In-sample", "valid": "Valid 2023–24", "oos1": "2025", "oos2": "2026"}
        print(draw_correlation({titles[k]: periods[k] for k in titles}, FIGURES / "correlation_periods.png", (1664, 520)))
    baseline = json.loads((REPORTS / "in_sample_baseline.json").read_text(encoding="utf-8"))["correlation"]
    print(draw_correlation({"In-sample, starting values": baseline}, FIGURES / "correlation_in_sample.png", (620, 600)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

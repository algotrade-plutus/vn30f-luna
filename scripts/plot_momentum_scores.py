#!/usr/bin/env python3
"""Deck figure: where the Momentum threshold θ sits among the in-sample scores.

Histogram of |s| over every regular 30-minute bar of in-sample, with θ at the
q = 0.7, 0.8 and 0.9 quantiles; bars at or past the chosen θ (q = 0.9) are the
ones Momentum trades. Writes reports/calibrum_1m/figures/momentum_score_quantiles.png.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from scripts.plot_calibrum_1m import ACCENT, DPI, FIGURES, FONT, FONT_SIZE, GRID, INK, MUTED, SURFACE  # noqa: E402
from scripts.run_calibrum_1m import _model  # noqa: E402
from src.lab.calibrum_1m import pipeline  # noqa: E402

KEPT, OUT_OF_TRADE = ACCENT, "#D5D9E0"
QUANTILES = (0.7, 0.8, 0.9)
X_MAX = 0.6


def main() -> int:
    config = pipeline.load_config()
    start, end = pipeline.periods(config)["in_sample"]
    market = pipeline.load_market(end.date())
    scores = pipeline.momentum_scores(market, _model())
    scores = scores[(scores.index >= start) & (scores.index <= end + pd.Timedelta(days=1))].abs().dropna()
    thetas = {q: float(scores.quantile(q)) for q in QUANTILES}
    chosen = thetas[0.9]

    plt.rcParams.update({"font.family": FONT, "font.size": FONT_SIZE + 1, "axes.edgecolor": GRID})
    fig, ax = plt.subplots(figsize=(2 * 1664 / DPI, 2 * 600 / DPI))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    edges = np.arange(0.0, X_MAX + 0.01, 0.01)
    counts, _ = np.histogram(scores.clip(upper=X_MAX - 1e-9), bins=edges)
    for left, count in zip(edges[:-1], counts):
        ax.bar(left, count, width=0.0085, align="edge", color=KEPT if left >= chosen - 1e-9 else OUT_OF_TRADE, linewidth=0)
    top = counts.max()
    heights = {0.7: 1.40, 0.8: 1.26, 0.9: 1.12}
    for q, theta in thetas.items():
        strong = q == 0.9
        ax.axvline(theta, ymax=heights[q] / 1.5, color=INK if strong else MUTED, linewidth=2.4 if strong else 1.6,
                   linestyle="-" if strong else (0, (4, 3)))
        ax.text(theta, top * heights[q], f"q = {q} → θ = {theta:.3f}", ha="center", va="center",
                color=INK if strong else MUTED, fontsize=20 if strong else 18, fontweight="bold" if strong else "normal",
                bbox={"boxstyle": "round,pad=0.25", "facecolor": SURFACE, "edgecolor": "none"})
    traded = int((scores >= chosen).sum())
    share = traded / len(scores)
    ax.text(0.37, top * 0.62, f"Traded: {traded:,} bars ({share:.0%}), |s| ≥ θ", color=KEPT, fontsize=22, fontweight="bold")
    ax.text(0.37, top * 0.50, f"Not traded: {len(scores) - traded:,} bars ({1 - share:.0%})", color=MUTED, fontsize=22)
    ax.set_xlim(0, X_MAX)
    ax.set_ylim(0, top * 1.5)
    ax.set_xlabel("|s|, strength of the Momentum score (bars past 0.6 drawn at 0.6)", color=MUTED)
    ax.set_ylabel("Number of 30-minute bars", color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    out = FIGURES / "momentum_score_quantiles.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    print(out, len(scores), thetas, traded, int((scores > X_MAX).sum()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

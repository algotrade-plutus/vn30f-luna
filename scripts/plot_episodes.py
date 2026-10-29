#!/usr/bin/env python3
"""Deck figures: the Basis and Momentum rules on one in-sample episode each, in the dashboard's session-chart style.

Top: VN30F1M every minute (and VN30 for Basis), shaded while the sleeve holds
long (green) or short (red), with a triangle at each fill. Bottom: the signal on
30-minute bars against its entry level.

- basis_episode.png: the basis with its mean +/- z_in standard deviations over
  the last W bars, so the band is where |Z| < z_in (W, z_in from basis_grid.json).
- momentum_episode.png: the score ŷ of each regular bar against +/- θ
  (θ from momentum_threshold.json).

The legends name the parameters, not their values: the slides illustrate the entry and exit rules.
Profit labels are before costs. Writes to reports/calibrum_1m/figures/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from scripts.plot_calibrum_1m import (  # noqa: E402
    ACCENT,
    DPI,
    FIGURES,
    FONT,
    GRID,
    INK,
    MILLION_VND_PER_POINT,
    MUTED,
    ORANGE,
    REPORTS,
    SURFACE,
)
from scripts.run_calibrum_1m import _model  # noqa: E402
from src.adapters.data.dnse_minute_bars import load_index_minutes  # noqa: E402
from src.lab.calibrum_1m import basis, momentum, pipeline  # noqa: E402

# The dashboard's session chart: black price, green long, red short.
LONG, SHORT, PRICE, SPOT, BAND, WEAK = "#00aa00", "#cc0000", "#222222", "#999999", "#EBEBEB", "#B4C1DE"
SIZE_PX = (1664, 640)
# Basis starts just after the previous short stopped out (13:11), so every fill shown opens or closes inside the window.
BASIS_WINDOW = (pd.Timestamp("2021-05-11 13:15"), pd.Timestamp("2021-05-14 14:45"))
MOMENTUM_WINDOW = (pd.Timestamp("2022-04-25 09:00"), pd.Timestamp("2022-04-26 14:45"))


class Episode:
    """The minutes of one window with the sleeve's position, its fills and its 30-minute bars."""

    def __init__(self, market: pipeline.Market, held_all: np.ndarray, start: pd.Timestamp, end: pd.Timestamp):
        shown = ((market.minutes["Datetime"] >= start) & (market.minutes["Datetime"] <= end)).to_numpy()
        self.stamps = market.minutes.loc[shown, "Datetime"].reset_index(drop=True)
        self.price, self.held = market.close[shown], held_all[shown]
        self.before = held_all[np.flatnonzero(shown)[0] - 1]
        self.fills = [i for i in range(len(self.stamps)) if self.held[i] != self._previous(i)]
        # Each 30-minute bar sits at its last minute, where its decision fills.
        self.bar_end = pd.Series(np.arange(len(self.stamps))).groupby(market.labels_30m.to_numpy()[shown]).last()

    def _previous(self, i: int) -> float:
        return self.held[i - 1] if i else self.before

    def is_buy(self, i: int) -> bool:
        return self.held[i] > self._previous(i)

    def gain_million(self, i: int, entry_price: float) -> float:
        """Profit before costs of the position closed at fill ``i``."""
        return (self.price[i] - entry_price) * self._previous(i) * MILLION_VND_PER_POINT


def _figure() -> tuple[plt.Figure, plt.Axes, plt.Axes]:
    plt.rcParams.update({"font.family": FONT, "font.size": 15, "axes.edgecolor": GRID})
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(2 * SIZE_PX[0] / DPI, 2 * SIZE_PX[1] / DPI), sharex=True,
                                      gridspec_kw={"height_ratios": [1.15, 1]})
    fig.patch.set_facecolor(SURFACE)
    return fig, top, bottom


def _draw_positions(episode: Episode, top: plt.Axes, bottom: plt.Axes) -> None:
    """Shade both panels while holding and mark each fill on the price line."""
    held = episode.held
    for ax in (top, bottom):
        ax.set_facecolor(SURFACE)
        first = 0
        for i in range(1, len(held) + 1):
            if i == len(held) or held[i] != held[first]:
                if held[first]:
                    ax.axvspan(first, i, color=LONG if held[first] > 0 else SHORT, alpha=0.08, linewidth=0)
                first = i
    top.plot(np.arange(len(held)), episode.price, color=PRICE, linewidth=1.5)
    offset = 0.06 * (np.nanmax(episode.price) - np.nanmin(episode.price))
    for i in episode.fills:
        buy = episode.is_buy(i)
        top.scatter(i, episode.price[i] + (-offset if buy else offset), marker="^" if buy else "v", s=170,
                    color=LONG if buy else SHORT, zorder=4)


def _finish(fig: plt.Figure, top: plt.Axes, bottom: plt.Axes, episode: Episode, signal_label: str,
            handles: list, out: Path) -> Path:
    days = episode.stamps.dt.date
    starts = [i for i in range(len(days)) if i == 0 or days[i] != days[i - 1]]
    bottom.set_xticks(starts, [pd.Timestamp(days[i]).strftime("%a %d/%m") for i in starts])
    for ax in (top, bottom):
        ax.set_axisbelow(True)
        for i in starts[1:]:
            ax.axvline(i, color="#E6E6E6", linewidth=1, zorder=0)
        ax.grid(axis="y", color="#F2F2F2")
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    top.set_xlim(0, len(days))
    top.set_ylabel("Price, points", color=MUTED)
    bottom.set_ylabel(signal_label, color=MUTED)
    fig.legend(handles=handles, loc="upper left", ncol=len(handles), frameon=False, fontsize=13,
               bbox_to_anchor=(0.045, 1.0), handlelength=1.4, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    return out


def _position_handles() -> list:
    return [
        Patch(color=LONG, alpha=0.3, label="holding long"),
        Patch(color=SHORT, alpha=0.3, label="holding short"),
        Line2D([], [], marker="^", color=LONG, lw=0, ms=10, label="buy"),
        Line2D([], [], marker="v", color=SHORT, lw=0, ms=10, label="sell"),
    ]


def _basis_bars(market: pipeline.Market, window: int) -> pd.DataFrame:
    """Basis, its rolling mean and standard deviation per 30-minute bar, as basis.zscores builds Z."""
    futures, index = market.futures_30m, market.index_30m
    bars = futures.loc[futures["Datetime"].dt.date.isin(set(index["Datetime"].dt.date)), ["Datetime", "Close", "Contract"]]
    merged = pd.merge_asof(
        bars.sort_values("Datetime"),
        index[["Datetime", "Close"]].rename(columns={"Close": "Spot"}).sort_values("Datetime"),
        on="Datetime",
        direction="backward",
    )
    merged["basis"] = merged["Close"] - merged["Spot"]
    segment = merged["Contract"].ne(merged["Contract"].shift()).cumsum()
    grouped = merged.groupby(segment)["basis"]
    merged["mean"] = grouped.transform(lambda s: s.rolling(window, min_periods=basis.MIN_PERIODS).mean())
    merged["std"] = grouped.transform(lambda s: s.rolling(window, min_periods=basis.MIN_PERIODS).std())
    return merged


def basis_episode(market: pipeline.Market) -> Path:
    chosen = json.loads((REPORTS / "basis_grid.json").read_text(encoding="utf-8"))
    window, z_entry = int(chosen["window"]), float(chosen["z_entry"])
    episode = Episode(market, pipeline.basis_positions(market, window, z_entry), *BASIS_WINDOW)

    index_minutes = load_index_minutes()[["Datetime", "Close"]].rename(columns={"Datetime": "IndexTime", "Close": "Spot"})
    joined = pd.merge_asof(episode.stamps.to_frame(), index_minutes, left_on="Datetime", right_on="IndexTime",
                           direction="backward")
    # VN30 prints from about 09:15: blank until the day's first index print rather than yesterday's close.
    spot = joined["Spot"].where(joined["IndexTime"].dt.date == joined["Datetime"].dt.date).to_numpy(float)

    bars = _basis_bars(market, window)
    bars = bars[bars["Datetime"].isin(episode.bar_end.index)].copy()
    bars["x"] = bars["Datetime"].map(episode.bar_end)
    low, high = bars["mean"] - z_entry * bars["std"], bars["mean"] + z_entry * bars["std"]

    fig, top, bottom = _figure()
    top.plot(np.arange(len(spot)), spot, color=SPOT, linewidth=1.3)
    _draw_positions(episode, top, bottom)
    bottom.fill_between(bars["x"], low, high, color=BAND, linewidth=0)
    bottom.plot(bars["x"], bars["mean"], color=MUTED, linewidth=1.2, linestyle=(0, (4, 3)))
    bottom.plot(bars["x"], bars["basis"], color=ORANGE, linewidth=2.4)
    entry_price = None
    for k, i in enumerate(episode.fills):
        buy = episode.is_buy(i)
        bar = bars.loc[bars["x"] <= i].iloc[-1]
        bottom.scatter(bar["x"], bar["basis"], marker="^" if buy else "v", s=170, color=LONG if buy else SHORT, zorder=4)
        side = "below" if buy else "above"
        if entry_price is None:
            text = f"Basis {side} the band: {'buy' if buy else 'sell'}"
        else:
            text = (f"{side.capitalize()} the band: take profit {episode.gain_million(i, entry_price):+.1f}M VND,\n"
                    f"{'buy back and go long' if buy else 'sell and go short'}")
        entry_price = episode.price[i]
        bottom.annotate(text, xy=(bar["x"], bar["basis"]), xytext=(-12 if buy and k else 12, -16 if buy else 16),
                        textcoords="offset points", fontsize=13, color=INK, va="top" if buy else "bottom",
                        ha="right" if buy and k else "left")
    bottom.set_ylim(min(low.min(), bars["basis"].min()) - 9, max(high.max(), bars["basis"].max()) + 10)
    handles = [
        Line2D([], [], color=PRICE, lw=2, label="VN30F1M"),
        Line2D([], [], color=SPOT, lw=2, label="VN30"),
        *_position_handles(),
        Line2D([], [], color=ORANGE, lw=2.4, label="basis F − I"),
        Patch(color="#DDDDDD", label="mean ± z_in sd"),
    ]
    return _finish(fig, top, bottom, episode, "Basis F − I, points", handles, FIGURES / "basis_episode.png")


def momentum_episode(market: pipeline.Market) -> Path:
    theta = float(json.loads((REPORTS / "momentum_threshold.json").read_text(encoding="utf-8"))["theta"])
    model = _model()
    episode = Episode(market, pipeline.momentum_positions(market, model, theta), *MOMENTUM_WINDOW)
    scores = pipeline.momentum_scores(market, model)
    bars = pd.DataFrame({"t": episode.bar_end.index, "x": episode.bar_end.to_numpy()})
    bars = bars[bars["t"].dt.strftime("%H:%M").isin(momentum.REGULAR_CLOCKS)].copy()
    bars["score"] = bars["t"].map(scores)

    fig, top, bottom = _figure()
    _draw_positions(episode, top, bottom)
    bottom.axhspan(-theta, theta, color=BAND, linewidth=0)
    bottom.axhline(0, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    bottom.bar(bars["x"], bars["score"], width=18, color=[ACCENT if abs(s) >= theta else WEAK for s in bars["score"]])
    entry_price = None
    for i in episode.fills:
        buy = episode.is_buy(i)
        bar = bars.loc[bars["x"] <= i].iloc[-1]
        opening = bool(episode.held[i])
        if opening:
            text = f"ŷ {'above +' if buy else 'below −'}θ: {'buy' if buy else 'sell'}"
        else:
            text = (f"ŷ turns {'positive' if buy else 'negative'}:\n"
                    f"{'buy back' if buy else 'sell'}, {episode.gain_million(i, entry_price):+.1f}M VND")
        entry_price = episode.price[i]
        below = bar["score"] < 0
        bottom.annotate(text, xy=(bar["x"], bar["score"]), xytext=(-16 if opening else 14, -6 if below else 14),
                        textcoords="offset points", fontsize=13, color=INK, va="top" if below else "bottom",
                        ha="right" if opening else "left")
    handles = [
        Line2D([], [], color=PRICE, lw=2, label="VN30F1M"),
        *_position_handles(),
        Patch(color=ACCENT, label="|ŷ| ≥ θ"),
        Patch(color=WEAK, label="|ŷ| < θ"),
        Patch(color="#DDDDDD", label="−θ to +θ"),
    ]
    return _finish(fig, top, bottom, episode, "Score ŷ", handles, FIGURES / "momentum_episode.png")


def main() -> int:
    config = pipeline.load_config()
    _, end = pipeline.periods(config)["in_sample"]
    market = pipeline.load_market(end.date())
    print(basis_episode(market))
    print(momentum_episode(market))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

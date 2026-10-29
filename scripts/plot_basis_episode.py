#!/usr/bin/env python3
"""Deck figure: the Basis rules on one in-sample week, in the dashboard's session-chart style.

Top: VN30F1M and VN30 every minute, shaded while Basis holds long (green) or
short (red), with a triangle at each fill. Bottom: the basis on 30-minute bars
with its mean +/- z_in standard deviations over the last W bars, so the band is
where |Z| < z_in. W and z_in are the step-5 choice in
reports/calibrum_1m/basis_grid.json. Writes
reports/calibrum_1m/figures/basis_episode.png.
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

from scripts.plot_calibrum_1m import DPI, FIGURES, FONT, GRID, INK, MILLION_VND_PER_POINT, MUTED, ORANGE, REPORTS, SURFACE  # noqa: E402
from src.adapters.data.dnse_minute_bars import load_index_minutes  # noqa: E402
from src.lab.calibrum_1m import basis, pipeline  # noqa: E402

# The dashboard's session chart: black price, green long, red short.
LONG, SHORT, PRICE, SPOT, BAND = "#00aa00", "#cc0000", "#222222", "#999999", "#EBEBEB"
# Starts just after the previous short stopped out (13:11), so every fill shown opens or closes inside the window.
START, END = pd.Timestamp("2021-05-11 13:15"), pd.Timestamp("2021-05-14 14:45")
SIZE_PX = (1664, 640)


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


def main() -> int:
    chosen = json.loads((REPORTS / "basis_grid.json").read_text(encoding="utf-8"))
    window, z_entry = int(chosen["window"]), float(chosen["z_entry"])
    config = pipeline.load_config()
    _, end = pipeline.periods(config)["in_sample"]
    market = pipeline.load_market(end.date())
    held_all = pipeline.basis_positions(market, window, z_entry)

    shown = ((market.minutes["Datetime"] >= START) & (market.minutes["Datetime"] <= END)).to_numpy()
    stamps = market.minutes.loc[shown, "Datetime"].reset_index(drop=True)
    price, held = market.close[shown], held_all[shown]
    before = held_all[np.flatnonzero(shown)[0] - 1]
    fills = [i for i in range(len(stamps)) if held[i] != (held[i - 1] if i else before)]

    index_minutes = load_index_minutes()[["Datetime", "Close"]].rename(columns={"Datetime": "IndexTime", "Close": "Spot"})
    joined = pd.merge_asof(stamps.to_frame(), index_minutes, left_on="Datetime", right_on="IndexTime", direction="backward")
    # VN30 prints from about 09:15: blank until the day's first index print rather than yesterday's close.
    spot = joined["Spot"].where(joined["IndexTime"].dt.date == joined["Datetime"].dt.date).to_numpy(float)

    bars = _basis_bars(market, window)
    last_minute = pd.Series(np.arange(len(stamps))).groupby(market.labels_30m.to_numpy()[shown]).last()
    bars = bars[bars["Datetime"].isin(last_minute.index)].copy()
    bars["x"] = bars["Datetime"].map(last_minute)
    low, high = bars["mean"] - z_entry * bars["std"], bars["mean"] + z_entry * bars["std"]

    plt.rcParams.update({"font.family": FONT, "font.size": 15, "axes.edgecolor": GRID})
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(2 * SIZE_PX[0] / DPI, 2 * SIZE_PX[1] / DPI), sharex=True,
                                      gridspec_kw={"height_ratios": [1.15, 1]})
    fig.patch.set_facecolor(SURFACE)
    for ax in (top, bottom):
        ax.set_facecolor(SURFACE)
        first = 0
        for i in range(1, len(stamps) + 1):
            if i == len(stamps) or held[i] != held[first]:
                if held[first]:
                    ax.axvspan(first, i, color=LONG if held[first] > 0 else SHORT, alpha=0.08, linewidth=0)
                first = i

    x = np.arange(len(stamps))
    top.plot(x, spot, color=SPOT, linewidth=1.3)
    top.plot(x, price, color=PRICE, linewidth=1.5)
    offset = 0.06 * (np.nanmax(price) - np.nanmin(price))
    bottom.fill_between(bars["x"], low, high, color=BAND, linewidth=0)
    bottom.plot(bars["x"], bars["mean"], color=MUTED, linewidth=1.2, linestyle=(0, (4, 3)))
    bottom.plot(bars["x"], bars["basis"], color=ORANGE, linewidth=2.4)

    entry_price = None
    for k, i in enumerate(fills):
        buy = held[i] > (held[i - 1] if i else before)
        colour, marker = (LONG, "^") if buy else (SHORT, "v")
        top.scatter(i, price[i] + (-offset if buy else offset), marker=marker, s=170, color=colour, zorder=4)
        bar = bars.loc[bars["x"] <= i].iloc[-1]
        bottom.scatter(bar["x"], bar["basis"], marker=marker, s=170, color=colour, zorder=4)
        side = "above" if not buy else "below"
        if entry_price is None:
            text = f"Basis {side} the band: {'buy' if buy else 'sell'}"
        else:
            gain = (price[i] - entry_price) * (-1 if buy else 1) * MILLION_VND_PER_POINT
            text = (f"{side.capitalize()} the band: take profit {gain:+.1f}M VND,\n"
                    f"{'buy back and go long' if buy else 'sell and go short'}")
        entry_price = price[i]
        bottom.annotate(text, xy=(bar["x"], bar["basis"]), xytext=(-12 if buy and k else 12, -16 if buy else 16),
                        textcoords="offset points", fontsize=13, color=INK, va="top" if buy else "bottom",
                        ha="right" if buy and k else "left")

    days = stamps.dt.date
    starts = [i for i in range(len(stamps)) if i == 0 or days[i] != days[i - 1]]
    bottom.set_xticks(starts, [pd.Timestamp(days[i]).strftime("%a %d/%m") for i in starts])
    for ax in (top, bottom):
        for i in starts[1:]:
            ax.axvline(i, color="#E6E6E6", linewidth=1)
        ax.grid(axis="y", color="#F2F2F2")
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    bottom.set_ylim(min(low.min(), bars["basis"].min()) - 9, max(high.max(), bars["basis"].max()) + 10)
    top.set_xlim(0, len(stamps))
    top.set_ylabel("Price, points", color=MUTED)
    bottom.set_ylabel("Basis F − I, points", color=MUTED)
    handles = [
        Line2D([], [], color=PRICE, lw=2, label="VN30F1M"),
        Line2D([], [], color=SPOT, lw=2, label="VN30"),
        Patch(color=LONG, alpha=0.3, label="holding long"),
        Patch(color=SHORT, alpha=0.3, label="holding short"),
        Line2D([], [], marker="^", color=LONG, lw=0, ms=10, label="buy"),
        Line2D([], [], marker="v", color=SHORT, lw=0, ms=10, label="sell"),
        Line2D([], [], color=ORANGE, lw=2.4, label="basis F − I"),
        Patch(color="#DDDDDD", label=f"mean ± {z_entry:g} sd, last {window} bars"),
    ]
    fig.legend(handles=handles, loc="upper left", ncol=len(handles), frameon=False, fontsize=13,
               bbox_to_anchor=(0.045, 1.0), handlelength=1.4, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out = FIGURES / "basis_episode.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    print(out, [(str(stamps[i]), held[i], price[i]) for i in fills])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

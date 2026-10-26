#!/usr/bin/env python3
"""Step 7: the Calendar v1 bot (the rules before the Calibrum redesign) on the PaperTrade account, 24 Aug to 23 Oct 2026.

Recomputes the reported paper results from the account's fills
(research/paper-trading/calendar_fills.csv, exported from the platform's REST
transactions endpoint) and the DNSE minute bars of step 2. The account is
marked at each session's close with the VN30F1M close; returns are on the 500
million VND paper capital, Sharpe on daily returns (sqrt 250, 3% risk-free).
Holding 8 contracts uses roll-adjusted closes (the roll gap is not profit),
from the last close before the bot's first trade and from the first session of
the August contract, where the chart starts.

Writes reports/paper/calendar.json; --chart PATH also draws the README chart.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from src.adapters.data.dnse_minute_bars import load_futures_minutes, roll_adjust_front_month  # noqa: E402

FILLS = WORKSPACE / "research" / "paper-trading" / "calendar_fills.csv"
OUT = WORKSPACE / "reports" / "paper"
CAPITAL = 500e6
MULTIPLIER = 100_000  # VND per index point per contract
HOLD = 8  # contracts the bot mostly traded
START, END = pd.Timestamp("2026-08-24"), pd.Timestamp("2026-10-23")
CHART_FROM = "VN30F2608"  # the chart starts when the August contract becomes the front month
RISK_FREE = 0.03


def daily_closes() -> tuple[pd.Series, pd.Series, pd.Series]:
    """Raw and roll-adjusted VN30F1M session closes, and the front-month contract of each session."""
    minutes = load_futures_minutes()
    minutes = minutes[(minutes["Datetime"] >= "2026-06-01") & (minutes["Datetime"] < END + pd.Timedelta(days=1))]
    adjusted, _ = roll_adjust_front_month(minutes.reset_index(drop=True))
    day = minutes["Datetime"].dt.normalize()
    raw = minutes.groupby(day)["Close"].last()
    contract = minutes.groupby(day)["Contract"].last()
    return raw, adjusted.groupby(adjusted["Datetime"].dt.normalize())["Close"].last(), contract


def equity(fills: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
    """Position and net profit after fees at each session close, in VND."""
    days = close.loc[START:END].index
    signed = np.where(fills["side"] == "BUY", 1, -1) * fills["quantity"]
    position, cash, rows, i = 0, 0.0, [], 0
    for day in days:
        session_end = day + pd.Timedelta(hours=15)
        while i < len(fills) and fills["time"].iloc[i] <= session_end:
            cash -= signed[i] * fills["price"].iloc[i] * MULTIPLIER + fills["fee_vnd"].iloc[i]
            position += signed[i]
            i += 1
        rows.append((day, position, cash + position * close[day] * MULTIPLIER))
    return pd.DataFrame(rows, columns=["day", "position", "pnl"]).set_index("day")


def summarise(fills: pd.DataFrame, curve: pd.DataFrame, adjusted: pd.Series, contract: pd.Series) -> dict:
    nav = CAPITAL + curve["pnl"]
    returns = nav.pct_change().fillna(nav.iloc[0] / CAPITAL - 1.0)
    sharpe = (returns.mean() - RISK_FREE / 250) / returns.std() * np.sqrt(250)
    closing = fills[fills["realized_pnl_vnd"] != 0]
    before_start = adjusted.loc[: START - pd.Timedelta(days=1)].iloc[-1]
    chart_start = contract[contract == CHART_FROM].index[0]
    end = adjusted.loc[END]
    return {
        "first_fill": str(fills["time"].iloc[0]),
        "last_fill": str(fills["time"].iloc[-1]),
        "fills": int(len(fills)),
        "contracts_traded": int(fills["quantity"].sum()),
        "net_profit_million_vnd": float(curve["pnl"].iloc[-1] / 1e6),
        "realized_after_fees_million_vnd": float((fills["realized_pnl_vnd"].sum() - fills["fee_vnd"].sum()) / 1e6),
        "fees_million_vnd": float(fills["fee_vnd"].sum() / 1e6),
        "net_return": float(curve["pnl"].iloc[-1] / CAPITAL),
        "sharpe_ratio": float(sharpe),
        "max_drawdown": float(-(nav / nav.cummax() - 1.0).min()),
        "round_trips": int(len(closing)),
        "round_trips_won": int((closing["realized_pnl_vnd"] > 0).sum()),
        "final_position": int(curve["position"].iloc[-1]),
        "hold_from_bot_start_million_vnd": float((end - before_start) * HOLD * MULTIPLIER / 1e6),
        "chart_start": str(chart_start.date()),
        "hold_from_chart_start_million_vnd": float((end - adjusted.loc[chart_start]) * HOLD * MULTIPLIER / 1e6),
    }


def draw(curve: pd.DataFrame, adjusted: pd.Series, chart_start: pd.Timestamp, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    from scripts.plot_calibrum_1m import DPI, GRID, INK, MUTED, SURFACE

    days = adjusted.loc[chart_start:END].index
    bot = (curve["pnl"] / 1e6).reindex(days).fillna(0.0)
    hold = (adjusted.loc[days] - adjusted.loc[chart_start]) * HOLD * MULTIPLIER / 1e6
    bot_start = adjusted.loc[: START - pd.Timedelta(days=1)].index[-1]  # both lines are marked at closes

    plt.rcParams.update({"font.family": "Arial", "font.size": 18, "axes.edgecolor": GRID})
    fig, ax = plt.subplots(figsize=(2 * 1664 / DPI, 2 * 600 / DPI))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.axvspan(days[0], bot_start, color="#E6E2D6", linewidth=0)
    ax.plot(bot.index, bot.values, color="#2a78d6", linewidth=3.4, solid_capstyle="round")
    ax.plot(hold.index, hold.values, color=INK, linewidth=1.8, linestyle=(0, (1.5, 2.5)))
    ax.axhline(0, color=MUTED, linewidth=1)
    top, bottom = max(bot.max(), hold.max()), min(bot.min(), hold.min())
    label_y = top + 0.06 * (top - bottom)
    ax.axvline(bot_start, color=MUTED, linewidth=1.6, linestyle=(0, (4, 3)))
    ax.text(days[0] + pd.Timedelta(days=1), label_y, "August contract, before the bot", color=MUTED, fontsize=18, va="top")
    ax.text(bot_start + pd.Timedelta(days=1), label_y, f"Bot starts, {START:%d %b}", color=INK, fontsize=18,
            va="top", fontweight="bold")
    for series, text, colour, weight in (
        (bot, f"Calendar v1 bot  {bot.iloc[-1]:+.0f}M", INK, "bold"),
        (hold, f"Holding {HOLD} VN30F1M from {chart_start:%d %b}  {hold.iloc[-1]:+.0f}M", MUTED, "normal"),
    ):
        ax.annotate(text.replace("-", "−"), xy=(series.index[-1], series.iloc[-1]), xytext=(12, 0),
                    textcoords="offset points", va="center", color=colour, fontweight=weight, annotation_clip=False)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_xticks([chart_start, *pd.date_range("2026-08-03", END, freq="14D")])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_xlim(days[0], days[-1] + (days[-1] - days[0]) * 0.26)
    ax.set_ylim(bottom - 0.05 * (top - bottom), top + 0.08 * (top - bottom))
    ax.set_ylabel("Cumulative net profit, million VND", color=MUTED)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}".replace("-", "−")))
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chart", type=Path, help="also draw the chart to this PNG")
    args = parser.parse_args()

    fills = pd.read_csv(FILLS, parse_dates=["time"]).sort_values("time", kind="stable").reset_index(drop=True)
    raw, adjusted, contract = daily_closes()
    curve = equity(fills, raw)
    summary = summarise(fills, curve, adjusted, contract)
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {**summary, "daily": {str(d.date()): {"position": int(p), "pnl_vnd": float(v)}
                                    for d, p, v in curve.itertuples()}}
    (OUT / "calendar.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for key, value in summary.items():
        print(f"{key:36s} {round(value, 4) if isinstance(value, float) else value}")
    if args.chart:
        draw(curve, adjusted, pd.Timestamp(summary["chart_start"]), args.chart)
        print(f"chart: {args.chart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Report figures for steps 4 and 5: sleeves, vote pairs and ensembles on the in-sample lab run.

Every configuration is shown per contract: the equal-weight sum (up to 3 contracts) is divided by 3.
Writes PNGs to image/report/ and prints the metrics tables.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from lab_common import PACKAGE_DIR, load_research_frames  # noqa: E402
from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    apply_session_rules,
    generate_calibrum_position_stream,
)
from src.lab.backtest import BacktestConfig, evaluate  # noqa: E402

OUT_DIR = WORKSPACE / "image" / "report"
START, END = date(2021, 6, 1), date(2022, 12, 30)
FEE = 0.8

# Chart tokens (validated with the dataviz palette validator on the #FBFAF5 surface).
SURFACE = "#FBFAF5"
INK = "#14213D"
INK_2 = "#5B6577"
GRID = "#E6E2D6"
REFERENCE = "#9AA3B2"
COLORS = {
    "Momentum": "#2a78d6",
    "Basis": "#eb6834",
    "Calendar": "#1baf7a",
    "M+B": "#6250d6",
    "M+C": "#e87ba4",
    "B+C": "#008300",
    "Vote": "#e34948",
    "Sum": "#eda100",
}
GROUPS = {
    "Single sleeves": ["Momentum", "Basis", "Calendar"],
    "Pairs (vote)": ["M+B", "M+C", "B+C"],
    "Ensembles": ["Vote", "Sum"],
}
LABEL_OFFSETS = {"M+C": (-10, -4), "M+B": (10, 8), "B+C": (10, -12)}
LABEL_LEFT = {"M+C"}
DIVERGING = LinearSegmentedColormap.from_list("loss_gain", ["#e34948", "#f0efec", "#2a78d6"])


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "Arial",
            "font.size": 11,
            "text.color": INK,
            "axes.labelcolor": INK_2,
            "axes.edgecolor": GRID,
            "axes.facecolor": SURFACE,
            "figure.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 13,
            "axes.titlelocation": "left",
            "legend.frameon": False,
        }
    )


def build_configs(futures: pd.DataFrame, spot: pd.DataFrame) -> dict[str, dict]:
    vote, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR)
    total, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR, ensemble_mode="sum")
    stamps = vote.Datetime
    # Code names in the stream: Ridge = Momentum, Shinji = Basis (report names).
    r, s, c = (vote[name].to_numpy() for name in ("Ridge", "Shinji", "Calendar"))
    positions = {
        "Momentum": (apply_session_rules(r, stamps), 1),
        "Basis": (apply_session_rules(s, stamps), 1),
        "Calendar": (apply_session_rules(c, stamps), 1),
        "M+B": (apply_session_rules(np.sign(r + s), stamps), 1),
        "M+C": (apply_session_rules(np.sign(r + c), stamps), 1),
        "B+C": (apply_session_rules(np.sign(s + c), stamps), 1),
        "Vote": (vote.Position.to_numpy(), 1),
        "Sum": (total.Position.to_numpy(), 3),
    }
    configs = {}
    for name, (position, scale) in positions.items():
        stream = pd.DataFrame({"Datetime": stamps, "Close": vote.Close, "Position": position})
        result = evaluate(stream, BacktestConfig(round_trip_fee_points=FEE, max_position=float(scale)))
        frame = result.frame
        pnl = pd.Series(frame.NetPnl.to_numpy() / scale, index=frame.Datetime)
        configs[name] = {
            "result": result,
            "scale": scale,
            "pnl": pnl,
            "drawdown": pnl - pnl.cummax(),
            "daily": result.aggregates.daily.NetGain / scale,
        }
    configs["_sleeves"] = {"Momentum": r, "Basis": s, "Calendar": c, "Close": vote.Close.to_numpy()}
    return configs


def label_end(ax, series: pd.Series, text: str, color: str) -> None:
    ax.annotate(
        text,
        xy=(series.index[-1], series.iloc[-1]),
        xytext=(6, 0),
        textcoords="offset points",
        va="center",
        fontsize=10,
        color=INK,
        bbox={"boxstyle": "round,pad=0.2", "fc": SURFACE, "ec": color, "lw": 1.2},
    )


def plot_step4_ensembles(configs: dict, path: Path) -> None:
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(12, 6.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]}
    )
    for name in GROUPS["Ensembles"]:
        cfg = configs[name]
        top.plot(cfg["pnl"].index, cfg["pnl"].to_numpy(), color=COLORS[name], lw=1.8, label=name)
        label_end(top, cfg["pnl"], f"{name} {cfg['pnl'].iloc[-1]:+,.0f}", COLORS[name])
        bottom.plot(cfg["drawdown"].index, cfg["drawdown"].to_numpy(), color=COLORS[name], lw=1.4, label=name)
    top.set_title("Cumulative net points per contract, in-sample 2021-06 to 2022-12 (lab)")
    top.set_ylabel("Net points")
    top.legend(loc="upper left")
    bottom.set_title("Drawdown")
    bottom.set_ylabel("Points")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_step5_grid(configs: dict, path: Path) -> None:
    fig, axes = plt.subplots(
        2, 3, figsize=(16, 7.5), sharex=True, sharey="row", gridspec_kw={"height_ratios": [3, 1.3]}
    )
    reference = configs["Vote"]
    for column, (group, names) in enumerate(GROUPS.items()):
        top, bottom = axes[0, column], axes[1, column]
        if group != "Ensembles":
            top.plot(reference["pnl"].index, reference["pnl"].to_numpy(), color=REFERENCE, lw=1.2, label="Vote (reference)")
            bottom.plot(reference["drawdown"].index, reference["drawdown"].to_numpy(), color=REFERENCE, lw=1.0)
        for name in names:
            cfg = configs[name]
            top.plot(cfg["pnl"].index, cfg["pnl"].to_numpy(), color=COLORS[name], lw=1.6, label=name)
            bottom.plot(cfg["drawdown"].index, cfg["drawdown"].to_numpy(), color=COLORS[name], lw=1.2)
        top.set_title(group)
        top.legend(loc="upper left", fontsize=10)
        top.tick_params(axis="x", labelrotation=30)
        bottom.tick_params(axis="x", labelrotation=30)
    axes[0, 0].set_ylabel("Cumulative net points")
    axes[1, 0].set_ylabel("Drawdown (points)")
    fig.suptitle("Sleeves, pairs and ensembles, per contract, in-sample (lab)", x=0.01, ha="left", fontweight="bold", fontsize=14)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def metrics_table(configs: dict) -> pd.DataFrame:
    rows = []
    for name in COLORS:
        cfg = configs[name]
        m = cfg["result"].metrics
        scale = cfg["scale"]
        rows.append(
            {
                "Config": name,
                "Net (pts)": m.profit_after_fee / scale,
                "Sharpe": m.sharpe_after_fee,
                "MDD (pts)": m.mdd_points / scale,
                "Trades": m.total_trading_quantity / scale,
                "Hit rate": m.hit_rate,
                "Margin (bps)": m.margin_after_fee,
            }
        )
    return pd.DataFrame(rows).set_index("Config")


def plot_risk_return(table: pd.DataFrame, path: Path) -> None:
    group_colors = {"Single sleeves": "#2a78d6", "Pairs (vote)": "#eb6834", "Ensembles": "#1baf7a"}
    fig, ax = plt.subplots(figsize=(10, 6.5))
    for group, names in GROUPS.items():
        sub = table.loc[names]
        ax.scatter(
            sub["MDD (pts)"], sub["Net (pts)"], s=sub["Sharpe"] * 90, color=group_colors[group],
            edgecolor=SURFACE, linewidth=2, label=group, zorder=3,
        )
        for name, row in sub.iterrows():
            ax.annotate(
                f"{name}  Sharpe {row['Sharpe']:.2f}", (row["MDD (pts)"], row["Net (pts)"]),
                xytext=LABEL_OFFSETS.get(name, (10, 4)), textcoords="offset points", fontsize=10, color=INK,
                ha="right" if name in LABEL_LEFT else "left",
            )
    ax.set_xlabel("Max drawdown (points, lower is better)")
    ax.set_ylabel("Net points after fee")
    ax.set_title("Profit against drawdown, per contract, in-sample (lab); marker size = Sharpe")
    ax.legend(loc="upper right")
    ax.margins(x=0.25, y=0.12)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_correlation(configs: dict, path: Path) -> None:
    names = GROUPS["Single sleeves"]
    daily = pd.DataFrame({name: configs[name]["daily"] for name in names})
    corr = daily.corr()
    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    image = ax.imshow(corr.to_numpy(), cmap=DIVERGING, vmin=-1, vmax=1)
    ax.set_xticks(range(3), names)
    ax.set_yticks(range(3), names)
    ax.grid(False)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{corr.iloc[i, j]:+.2f}", ha="center", va="center", fontsize=13, color=INK)
    ax.set_title("Correlation of daily net PnL, in-sample (lab)")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_monthly(configs: dict, path: Path) -> None:
    names = GROUPS["Single sleeves"] + ["Vote"]
    monthly = pd.DataFrame(
        {name: configs[name]["result"].aggregates.monthly.NetGain / configs[name]["scale"] for name in names}
    ).T
    labels = [stamp.strftime("%y-%m") for stamp in monthly.columns]
    limit = float(np.nanmax(np.abs(monthly.to_numpy())))
    fig, ax = plt.subplots(figsize=(16, 3.6))
    image = ax.imshow(monthly.to_numpy(), cmap=DIVERGING, vmin=-limit, vmax=limit, aspect="auto")
    ax.set_yticks(range(len(names)), names)
    ax.set_xticks(range(len(labels)), labels, rotation=0, fontsize=9)
    ax.grid(False)
    for i in range(monthly.shape[0]):
        for j in range(monthly.shape[1]):
            ax.text(j, i, f"{monthly.iat[i, j]:+.0f}", ha="center", va="center", fontsize=8.5, color=INK)
    ax.set_title("Net points per month, per contract, in-sample (lab); blue = gain, red = loss")
    fig.colorbar(image, ax=ax, fraction=0.02, pad=0.01)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_agreement(configs: dict, path: Path) -> pd.DataFrame:
    sleeves = configs["_sleeves"]
    total = sleeves["Momentum"] + sleeves["Basis"] + sleeves["Calendar"]
    close = sleeves["Close"]
    forward = np.r_[np.diff(close), np.nan]  # next-bar change, earned by a position taken at this close
    direction = np.sign(total)
    frame = pd.DataFrame({"level": np.abs(total), "edge": direction * forward}).dropna()
    summary = frame.groupby("level").agg(share=("edge", "size"), edge=("edge", "mean"))
    summary["share"] = summary["share"] / summary["share"].sum() * 100
    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 4.6))
    levels = [int(level) for level in summary.index]
    left.bar(levels, summary["share"], color="#2a78d6", width=0.6)
    left.set_title("Share of bars by agreement |M + B + C|")
    left.set_ylabel("% of bars")
    traded = [level for level in levels if level > 0]
    right.bar(traded, summary.loc[traded, "edge"], color="#2a78d6", width=0.6)
    right.axhline(0, color=INK_2, lw=0.8)
    right.set_title("Mean next-bar points in the agreed direction")
    right.set_ylabel("Points per bar, before fees")
    for ax, column, fmt, shown in ((left, "share", "{:.1f}%", levels), (right, "edge", "{:+.2f}", traded)):
        ax.set_xticks(shown, [str(level) for level in shown])
        ax.set_xlabel("Number of sleeves on the net side (0 = no position)")
        for level in shown:
            value = summary.loc[level, column]
            ax.annotate(fmt.format(value), (level, value), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return summary


def plot_rolling_sharpe(configs: dict, path: Path, window: int = 60) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.6))
    for name in GROUPS["Single sleeves"]:
        daily = configs[name]["daily"]
        rolling = daily.rolling(window).mean() / daily.rolling(window).std() * np.sqrt(252)
        rolling.index = pd.to_datetime(rolling.index)
        ax.plot(rolling.index, rolling.to_numpy(), color=COLORS[name], lw=1.6, label=name)
    ax.axhline(0, color=INK_2, lw=0.8)
    ax.set_title(f"Rolling {window}-session Sharpe, in-sample (lab)")
    ax.set_ylabel("Sharpe")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    style()

    futures, spot, _ = load_research_frames("dnse", START, END, allow_fetch=False)
    configs = build_configs(futures, spot)
    table = metrics_table(configs)

    plot_step4_ensembles(configs, out / "step4_ensembles_equity.png")
    plot_step5_grid(configs, out / "step5_equity_grid.png")
    plot_risk_return(table, out / "step5_risk_return.png")
    plot_correlation(configs, out / "step5_correlation.png")
    plot_monthly(configs, out / "step5_monthly_pnl.png")
    agreement = plot_agreement(configs, out / "step5_agreement.png")
    plot_rolling_sharpe(configs, out / "step5_rolling_sharpe.png")

    with pd.option_context("display.float_format", "{:,.2f}".format, "display.width", 120):
        print(table)
        print()
        print(agreement)
        daily = pd.DataFrame({name: configs[name]["daily"] for name in GROUPS["Single sleeves"]})
        print()
        print(daily.corr())
    print(f"Figures: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

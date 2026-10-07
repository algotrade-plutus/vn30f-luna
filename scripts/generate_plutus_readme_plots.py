#!/usr/bin/env python3
"""Generate 8 Plutus backtest plots (Equity & Daily Profit for IS, OOS, Forward, Full) for README."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]

REPORTS = [
    {
        "id": "is",
        "name": "In-Sample",
        "path": WORKSPACE / "reports" / "calibrum_raw_roll_guards_insample_2021-2022_1contract_100m.json",
        "title": "In-Sample Plutus Backtest (2021 - 2022)",
    },
    {
        "id": "oos",
        "name": "Out-of-Sample",
        "path": WORKSPACE / "reports" / "calibrum_raw_roll_guards_oos_2023-2024_1contract_100m.json",
        "title": "Out-of-Sample Plutus Backtest (2023 - 2024)",
    },
    {
        "id": "forward",
        "name": "Forward",
        "path": WORKSPACE / "reports" / "calibrum_raw_roll_guards_forward_2025-01-01_2026-10-01_1contract_100m.json",
        "title": "Forward Walk Plutus Backtest (2025 - 2026)",
    },
    {
        "id": "full",
        "name": "Full Period",
        "path": WORKSPACE / "reports" / "calibrum_raw_roll_guards_full_2021-2026_1contract_100m.json",
        "title": "Full Life-Cycle Plutus Backtest (2021 - 2026)",
    },
]


def plot_plutus_equity(report_data: dict, title: str = "", figsize=(14, 5)):
    daily = report_data["daily_equity"]
    dates = pd.to_datetime([x["date"] for x in daily])
    initial = float(report_data["initial_capital"])
    equities = np.array([float(x["equity"]) for x in daily])
    net_equity = equities / initial

    figure, axis = plt.subplots(figsize=figsize)
    sharpe = float(report_data["sharpe"])
    ret_pct = float(report_data["return_pct"])
    axis.plot(
        dates,
        net_equity,
        color="#1f77b4",
        linewidth=1.8,
        label=f"Net Equity (Plutus) — Sharpe: {sharpe:.2f} | Return: {ret_pct:+.2f}%",
    )
    axis.axhline(1.0, color="#6b7280", linestyle="--", linewidth=1.0)
    axis.set_xlabel("Time")
    axis.set_ylabel("Return (Equity / Initial)")
    axis.grid(True)
    axis.legend(loc="upper left")
    if title:
        axis.set_title(title)
    figure.tight_layout()
    return figure


def plot_plutus_daily_profit(report_data: dict, title: str = "", figsize=(14, 5)):
    daily = report_data["daily_equity"]
    dates = pd.to_datetime([x["date"] for x in daily])
    initial = float(report_data["initial_capital"])
    equities = np.array([float(x["equity"]) for x in daily])
    cum_net_vnd = equities - initial
    cum_net_pts = cum_net_vnd / 100_000.0
    num_days = len(daily)

    figure, axis = plt.subplots(figsize=figsize)
    last_pts = cum_net_pts[-1] if len(cum_net_pts) else 0.0
    last_vnd = cum_net_vnd[-1] if len(cum_net_vnd) else 0.0
    axis.plot(
        dates,
        cum_net_pts,
        color="#ff7f0e",
        linewidth=1.8,
        label=f"Profit after statutory charges: {last_pts:+.2f} pts ({last_vnd / 1e6:+,.1f}M VND)",
    )
    axis.set_xlabel("Time")
    axis.set_ylabel("Points (100k VND / pt)")
    axis.grid(True)
    axis.legend(loc="upper left")
    if title:
        axis.set_title(title, loc="center")
    axis.set_title(f"Số ngày: {num_days}", loc="right", fontsize=10.5, color="#1e293b", fontweight="medium")
    figure.tight_layout()
    return figure


def main() -> int:
    reports_fig_dir = WORKSPACE / "reports" / "figures"
    readme_img_dir = WORKSPACE / "image" / "README"

    reports_fig_dir.mkdir(parents=True, exist_ok=True)
    readme_img_dir.mkdir(parents=True, exist_ok=True)

    generated_files = []

    print("=== Generating 8 Plutus Backtest Plots ===")
    for item in REPORTS:
        p_id = item["id"]
        name = item["name"]
        report_path = item["path"]
        title = item["title"]

        print(f"\nProcessing {name} ({report_path.name})...")
        if not report_path.exists():
            print(f"Error: {report_path} not found!", file=sys.stderr)
            return 1

        data = json.loads(report_path.read_text(encoding="utf-8"))
        print(f"  Sessions: {len(data['daily_equity'])}")
        print(f"  Net PnL:  {data['net_pnl']:+,.0f} VND ({data['net_pnl'] / 100000:+.2f} pts)")
        print(f"  Sharpe:   {data['sharpe']:.2f}")

        equity_fig = plot_plutus_equity(data, title=title)
        equity_file = reports_fig_dir / f"{p_id}_plutus_equity.png"
        equity_fig.savefig(equity_file, dpi=180, bbox_inches="tight")
        plt.close(equity_fig)

        profit_fig = plot_plutus_daily_profit(data, title=title)
        profit_file = reports_fig_dir / f"{p_id}_plutus_daily_profit.png"
        profit_fig.savefig(profit_file, dpi=180, bbox_inches="tight")
        plt.close(profit_fig)

        for p in (equity_file, profit_file):
            readme_target = readme_img_dir / p.name
            shutil.copy2(p, readme_target)
            generated_files.append((p, readme_target))
            print(f"  Saved: {p.relative_to(WORKSPACE)} and {readme_target.relative_to(WORKSPACE)}")

    print(f"\nSuccessfully generated {len(generated_files)} Plutus plot files!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

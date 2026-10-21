#!/usr/bin/env python3
"""Generate dedicated institutional-grade visualization plots for ensemble research and Plutus 3 HD comparison.

All labels, legends, and titles are in English as requested.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, str(path))

from lab_common import (  # noqa: E402
    DEFAULT_FEE,
    PACKAGE_DIR,
    load_research_frames,
    evaluate,
)
from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    apply_session_rules,
    generate_calibrum_position_stream,
)
from src.lab.backtest import BacktestConfig  # noqa: E402


def plot_sleeves_cumulative_points(figures_dir: Path, readme_dir: Path) -> Path:
    """Plot cumulative net profit points and drawdown for individual sleeves and ensemble (English)."""
    futures, spot, _ = load_research_frames(
        "dnse", date(2021, 6, 1), date(2026, 10, 1), allow_fetch=False
    )
    pos_df, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR)
    

    def make_stream(pos_series: np.ndarray | pd.Series) -> pd.DataFrame:
        pos = apply_session_rules(np.asarray(pos_series, dtype=float), futures["Datetime"])
        return pd.DataFrame({
            "Datetime": futures["Datetime"],
            "Close": futures["Close"],
            "Position": pos,
        })
    
    series_dict = {}
    
    # 1. Ridge
    res_r = evaluate(make_stream(pos_df["Ridge"]), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))
    series_dict["Ridge H2 (1 Contract)"] = res_r.frame.set_index("Datetime")["NetPnl"]
    
    # 2. Shinji
    res_s = evaluate(make_stream(pos_df["Shinji"]), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))
    series_dict["Shinji Spread (1 Contract)"] = res_s.frame.set_index("Datetime")["NetPnl"]
    
    # 3. Calendar
    res_c = evaluate(make_stream(pos_df["Calendar"]), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))
    series_dict["Calendar Anomaly (1 Contract)"] = res_c.frame.set_index("Datetime")["NetPnl"]
    
    # 4. Baseline Vote (1 Contract)
    res_vote = evaluate(make_stream(pos_df["Position"]), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))
    series_dict["Baseline Majority Vote (1 Contract)"] = res_vote.frame.set_index("Datetime")["NetPnl"]
    
    # 5. Ensemble Sum, normalized to 1 contract: (R + S + C) / 3.
    # Fees scale linearly with |dPosition|, so this equals the 3-contract PnL / 3.
    sum_pos = (pos_df["Ridge"] + pos_df["Shinji"] + pos_df["Calendar"]).clip(-3.0, 3.0) / 3.0
    res_sum = evaluate(
        make_stream(sum_pos),
        BacktestConfig(round_trip_fee_points=DEFAULT_FEE, require_discrete_position=False),
    )
    series_dict["Ensemble Sum (normalized to 1 Contract)"] = res_sum.frame.set_index("Datetime")["NetPnl"]

    # Drawdown for Vote vs Sum
    vote_eq = series_dict["Baseline Majority Vote (1 Contract)"]
    vote_dd = vote_eq - vote_eq.cummax()
    sum_eq = series_dict["Ensemble Sum (normalized to 1 Contract)"]
    sum_dd = sum_eq - sum_eq.cummax()

    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [2.6, 1]})

    # Top: Cumulative Net Points
    ax1.plot(series_dict["Ridge H2 (1 Contract)"], label=f"Ridge H2 (1 Contract): +{res_r.metrics.profit_after_fee:.1f} pts (Sharpe {res_r.metrics.sharpe_after_fee:.2f})", color="#2563eb", linewidth=1.5, alpha=0.85)
    ax1.plot(series_dict["Shinji Spread (1 Contract)"], label=f"Shinji Spread (1 Contract): +{res_s.metrics.profit_after_fee:.1f} pts (Sharpe {res_s.metrics.sharpe_after_fee:.2f})", color="#9333ea", linewidth=1.5, alpha=0.85)
    ax1.plot(series_dict["Calendar Anomaly (1 Contract)"], label=f"Calendar Anomaly (1 Contract): +{res_c.metrics.profit_after_fee:.1f} pts (Sharpe {res_c.metrics.sharpe_after_fee:.2f})", color="#059669", linewidth=1.5, alpha=0.85)
    ax1.plot(series_dict["Baseline Majority Vote (1 Contract)"], label=f"Baseline Majority Vote (1 Contract): +{res_vote.metrics.profit_after_fee:.1f} pts (Sharpe {res_vote.metrics.sharpe_after_fee:.2f})", color="#d97706", linewidth=1.8, linestyle="--")
    ax1.plot(series_dict["Ensemble Sum (normalized to 1 Contract)"], label=f"Ensemble Sum ((R+S+C)/3, 1 Contract): +{res_sum.metrics.profit_after_fee:.1f} pts (Sharpe {res_sum.metrics.sharpe_after_fee:.2f})", color="#dc2626", linewidth=2.4)

    # Shading periods
    ax1.axvspan(pd.Timestamp("2021-06-01"), pd.Timestamp("2022-12-30"), color="#f1f5f9", alpha=0.5, label="In-Sample Period")
    ax1.axvspan(pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-19"), color="#e0f2fe", alpha=0.5, label="Out-of-Sample Period")
    ax1.axvspan(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-10-01"), color="#fef3c7", alpha=0.5, label="Forward Walk Period")

    ax1.set_title("Calibrum Sleeves vs. Ensembles: Cumulative Net Points per 1 Contract (2021 – 2026)", fontsize=14, fontweight="bold", pad=12)
    ax1.set_ylabel("Cumulative Net Gain (VN30F Index Points)", fontsize=11, fontweight="semibold")
    ax1.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="#cbd5e1", fontsize=9.5, framealpha=0.95)
    ax1.grid(True, linestyle=":", alpha=0.6)

    # Bottom: Drawdown
    ax2.plot(vote_dd, label=f"Drawdown Vote (1 Contract): Max {res_vote.metrics.mdd_points:.1f} pts", color="#d97706", linewidth=1.3, linestyle="--")
    ax2.plot(sum_dd, label=f"Drawdown Sum (1 Contract): Max {res_sum.metrics.mdd_points:.1f} pts", color="#dc2626", linewidth=1.6)
    ax2.fill_between(sum_dd.index, sum_dd, 0, color="#dc2626", alpha=0.12)
    ax2.set_title("Underwater Drawdown Profile (Index Points)", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Drawdown (Pts)", fontsize=10, fontweight="semibold")
    ax2.set_xlabel("Timeline", fontsize=11, fontweight="semibold")
    ax2.legend(loc="lower left", frameon=True, facecolor="white", fontsize=9.5)
    ax2.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    out_path = figures_dir / "ensemble_sleeves_cumulative_points.png"
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    shutil.copy2(out_path, readme_dir / out_path.name)
    return out_path


def plot_correlation_heatmaps(figures_dir: Path, readme_dir: Path) -> Path:
    """Plot clear, highly readable heatmaps for daily Net PnL and bar position correlations (English)."""
    with open(WORKSPACE / "reports" / "ensemble_research_report.json") as f:
        report = json.load(f)
    
    corr_data = report["correlations"]
    periods = ["IS", "OOS", "FWD", "FULL"]
    period_titles = [
        "In-Sample\n(2021 - 2022)",
        "Out-of-Sample\n(2023 - 2024)",
        "Forward Walk\n(2026)",
        "Full Life-Cycle\n(2021 - 2026)",
    ]
    
    labels = ["Ridge", "Shinji", "Calendar"]
    
    # We use a large, spacious figure layout (17 x 8.5) with clean square cells
    fig, axes = plt.subplots(2, 4, figsize=(17, 8.5))
    fig.suptitle("Alpha Sleeves Correlation Analysis: Cross-Regime Pearson Coefficients", fontsize=15, fontweight="bold", y=0.99)

    cmap = matplotlib.colormaps["coolwarm"].copy()
    norm = matplotlib.colors.Normalize(vmin=-0.20, vmax=1.00)

    for i, p in enumerate(periods):
        # 1. PnL Correlation Matrix (Row 0)
        pnl_dict = corr_data[p]["pnl_correlation"]
        pnl_mat = np.array([[pnl_dict[r][c] for c in labels] for r in labels])
        ax_pnl = axes[0, i]
        im_pnl = ax_pnl.imshow(pnl_mat, cmap=cmap, norm=norm)
        ax_pnl.set_title(f"{period_titles[i]}\n[Daily Net PnL]", fontsize=11, fontweight="bold", pad=8)
        ax_pnl.set_xticks(range(3))
        ax_pnl.set_yticks(range(3))
        ax_pnl.set_xticklabels(labels, fontsize=10, fontweight="semibold")
        ax_pnl.set_yticklabels(labels if i == 0 else [], fontsize=10, fontweight="semibold")
        
        # Add white cell borders and high-contrast text
        for r in range(3):
            for c in range(3):
                val = pnl_mat[r, c]
                txt_color = "white" if val > 0.65 or val < -0.4 else "#0f172a"
                font_weight = "bold" if r != c else "normal"
                sign_str = "+" if val > 0 and r != c else ""
                ax_pnl.text(c, r, f"{sign_str}{val:.3f}" if r != c else "1.00", ha="center", va="center", color=txt_color, fontsize=11, fontweight=font_weight)

        # Explicitly disable any major grid to remove the white "+" cross inside cells
        ax_pnl.grid(False)
        for sep in [0.5, 1.5]:
            ax_pnl.axhline(sep, color="white", linewidth=3.0)
            ax_pnl.axvline(sep, color="white", linewidth=3.0)

        # 2. Position Correlation Matrix (Row 1)
        pos_dict = corr_data[p]["position_correlation"]
        pos_mat = np.array([[pos_dict[r][c] for c in labels] for r in labels])
        ax_pos = axes[1, i]
        im_pos = ax_pos.imshow(pos_mat, cmap=cmap, norm=norm)
        ax_pos.set_title(f"{period_titles[i]}\n[Bar Positions]", fontsize=11, fontweight="bold", pad=8)
        ax_pos.set_xticks(range(3))
        ax_pos.set_yticks(range(3))
        ax_pos.set_xticklabels(labels, fontsize=10, fontweight="semibold")
        ax_pos.set_yticklabels(labels if i == 0 else [], fontsize=10, fontweight="semibold")
        
        for r in range(3):
            for c in range(3):
                val = pos_mat[r, c]
                txt_color = "white" if val > 0.65 or val < -0.4 else "#0f172a"
                font_weight = "bold" if r != c else "normal"
                sign_str = "+" if val > 0 and r != c else ""
                ax_pos.text(c, r, f"{sign_str}{val:.3f}" if r != c else "1.00", ha="center", va="center", color=txt_color, fontsize=11, fontweight=font_weight)

        ax_pos.grid(False)
        for sep in [0.5, 1.5]:
            ax_pos.axhline(sep, color="white", linewidth=3.0)
            ax_pos.axvline(sep, color="white", linewidth=3.0)

    # Colorbar
    fig.subplots_adjust(right=0.91, hspace=0.35, wspace=0.18)
    cbar_ax = fig.add_axes([0.93, 0.15, 0.016, 0.7])
    cbar = fig.colorbar(im_pnl, cax=cbar_ax)
    cbar.set_label("Pearson Correlation Coefficient", fontsize=11, fontweight="semibold")
    cbar.ax.tick_params(labelsize=10)

    out_path = figures_dir / "ensemble_correlation_heatmaps.png"
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)

    shutil.copy2(out_path, readme_dir / out_path.name)
    return out_path


def plot_plutus_3hd_comparison(figures_dir: Path, readme_dir: Path) -> Path:
    """Plot Plutus Equity and Drawdown curves comparing Baseline Vote (3 HD) vs Ensemble Sum (3 HD) in English."""
    reports = {
        "IS": {
            "vote": WORKSPACE / "reports" / "calibrum_plutus_insample_vote3_300m.json",
            "sum": WORKSPACE / "reports" / "calibrum_plutus_insample_sum3_300m.json",
            "title": "In-Sample Period (2021 – 2022)",
        },
        "OOS": {
            "vote": WORKSPACE / "reports" / "calibrum_plutus_oos_vote3_300m.json",
            "sum": WORKSPACE / "reports" / "calibrum_plutus_oos_sum3_300m.json",
            "title": "Out-of-Sample Period (2023 – 2024)",
        },
        "FWD": {
            "vote": WORKSPACE / "reports" / "calibrum_plutus_forward_vote3_300m.json",
            "sum": WORKSPACE / "reports" / "calibrum_plutus_forward_sum3_300m.json",
            "title": "Forward Walk Period (2026)",
        },
    }

    fig, axes = plt.subplots(3, 2, figsize=(15, 11), sharex="row")
    fig.suptitle("Plutus Exchange Execution Replay: Baseline Vote (3 Contracts) vs Ensemble Sum (3 Contracts) — Capital 300M VND", fontsize=13, fontweight="bold", y=0.99)

    for row, (period_key, p_info) in enumerate(reports.items()):
        with open(p_info["vote"]) as f:
            v_data = json.load(f)
        with open(p_info["sum"]) as f:
            s_data = json.load(f)

        v_eq_df = pd.DataFrame(v_data["daily_equity"])
        s_eq_df = pd.DataFrame(s_data["daily_equity"])

        v_eq_df["date"] = pd.to_datetime(v_eq_df["date"])
        s_eq_df["date"] = pd.to_datetime(s_eq_df["date"])

        v_eq_df.set_index("date", inplace=True)
        s_eq_df.set_index("date", inplace=True)

        v_capital = v_eq_df["equity"] / 1e6
        s_capital = s_eq_df["equity"] / 1e6

        v_dd = (v_capital - v_capital.cummax()) / v_capital.cummax() * 100
        s_dd = (s_capital - s_capital.cummax()) / s_capital.cummax() * 100

        # Equity plot (Left column)
        ax_eq = axes[row, 0]
        ax_eq.plot(v_capital, label=f"Baseline Vote (3 Contracts): +{v_data['net_pnl']/1e6:.1f}M VND (Sharpe {v_data['sharpe']:.2f})", color="#d97706", linewidth=1.6, linestyle="--")
        ax_eq.plot(s_capital, label=f"Ensemble Sum (3 Contracts): +{s_data['net_pnl']/1e6:.1f}M VND (Sharpe {s_data['sharpe']:.2f})", color="#dc2626", linewidth=2.0)
        ax_eq.set_title(f"{p_info['title']} — Net Account Equity", fontsize=11, fontweight="bold")
        ax_eq.set_ylabel("Account Equity (Million VND)", fontsize=10, fontweight="semibold")
        ax_eq.legend(loc="upper left", frameon=True, facecolor="white", fontsize=9)
        ax_eq.grid(True, linestyle=":", alpha=0.6)

        # Drawdown plot (Right column)
        ax_dd = axes[row, 1]
        ax_dd.plot(v_dd, label=f"Vote Max Drawdown: {v_data['mdd_pct']:.2f}%", color="#d97706", linewidth=1.3, linestyle="--")
        ax_dd.plot(s_dd, label=f"Sum Max Drawdown: {s_data['mdd_pct']:.2f}%", color="#dc2626", linewidth=1.6)
        ax_dd.fill_between(s_dd.index, s_dd, 0, color="#dc2626", alpha=0.15)
        ax_dd.set_title(f"{p_info['title']} — Percentage Drawdown", fontsize=11, fontweight="bold")
        ax_dd.set_ylabel("Drawdown (%)", fontsize=10, fontweight="semibold")
        ax_dd.legend(loc="lower left", frameon=True, facecolor="white", fontsize=9)
        ax_dd.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    out_path = figures_dir / "plutus_vote_vs_sum_equity.png"
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    shutil.copy2(out_path, readme_dir / out_path.name)
    return out_path


def plot_alpha_vs_filter_comparison(figures_dir: Path, readme_dir: Path) -> Path:
    """Generate visual demonstration of Additive Alpha vs Filtering mechanism (based on user's PDF)."""
    futures, spot, _ = load_research_frames(
        "dnse", date(2021, 6, 1), date(2026, 10, 1), allow_fetch=False
    )
    pos_df, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR)
    

    def make_stream(pos_series: np.ndarray | pd.Series) -> pd.DataFrame:
        pos = apply_session_rules(np.asarray(pos_series, dtype=float), futures["Datetime"])
        return pd.DataFrame({
            "Datetime": futures["Datetime"],
            "Close": futures["Close"],
            "Position": pos,
        })
    
    R = pos_df["Ridge"].to_numpy()
    C = pos_df["Calendar"].to_numpy()
    
    # 1. Ridge alone
    res_r = evaluate(make_stream(R), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))
    # 2. Calendar alone
    res_c = evaluate(make_stream(C), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))
    # 3. Additive Vote (R + C)
    res_rc_vote = evaluate(make_stream(np.sign(R + C)), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))
    # 4. Filter Approach: Ridge filtered by Calendar (Trade R only when C does not oppose)
    res_r_filt_c = evaluate(make_stream(R * (C != -R)), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))
    # 5. Strict Confirmation Filter: Trade R only when C agrees (R == C)
    res_r_strict_c = evaluate(make_stream(R * (C == R)), BacktestConfig(round_trip_fee_points=DEFAULT_FEE))

    fig, ax = plt.subplots(figsize=(13, 6.5))
    
    ax.plot(res_rc_vote.frame.set_index("Datetime")["NetPnl"], label=f"Additive Alpha: R + C (Vote) — +{res_rc_vote.metrics.profit_after_fee:.1f} pts (Sharpe {res_rc_vote.metrics.sharpe_after_fee:.2f})", color="#2563eb", linewidth=2.2)
    ax.plot(res_c.frame.set_index("Datetime")["NetPnl"], label=f"Standalone Calendar (C) — +{res_c.metrics.profit_after_fee:.1f} pts (Sharpe {res_c.metrics.sharpe_after_fee:.2f})", color="#059669", linewidth=1.5, linestyle="-.")
    ax.plot(res_r_filt_c.frame.set_index("Datetime")["NetPnl"], label=f"Filter Approach: R filtered by C (No opposition) — +{res_r_filt_c.metrics.profit_after_fee:.1f} pts (Sharpe {res_r_filt_c.metrics.sharpe_after_fee:.2f})", color="#d97706", linewidth=1.8, linestyle="--")
    ax.plot(res_r.frame.set_index("Datetime")["NetPnl"], label=f"Standalone Ridge (R) — +{res_r.metrics.profit_after_fee:.1f} pts (Sharpe {res_r.metrics.sharpe_after_fee:.2f})", color="#64748b", linewidth=1.4)
    ax.plot(res_r_strict_c.frame.set_index("Datetime")["NetPnl"], label=f"Strict Filter: R confirmed by C (R == C) — +{res_r_strict_c.metrics.profit_after_fee:.1f} pts (Sharpe {res_r_strict_c.metrics.sharpe_after_fee:.2f})", color="#94a3b8", linewidth=1.3, linestyle=":")

    ax.set_title("Empirical Verification of 'Additive Alpha vs. Signal Filter' on VN30F Data (2021 – 2026)", fontsize=13, fontweight="bold", pad=12)
    ax.set_ylabel("Cumulative Net Gain (VN30F Index Points)", fontsize=11, fontweight="semibold")
    ax.set_xlabel("Timeline", fontsize=11, fontweight="semibold")
    ax.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="#cbd5e1", fontsize=9.5)
    ax.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    out_path = figures_dir / "alpha_additive_vs_filter_comparison.png"
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    shutil.copy2(out_path, readme_dir / out_path.name)
    return out_path


def main() -> int:
    figures_dir = WORKSPACE / "reports" / "figures"
    readme_dir = WORKSPACE / "image" / "README"
    figures_dir.mkdir(parents=True, exist_ok=True)
    readme_dir.mkdir(parents=True, exist_ok=True)

    print("Generating Institutional English Visualizations...")
    p1 = plot_sleeves_cumulative_points(figures_dir, readme_dir)
    print(f"  [1/4] Saved: {p1.name}")

    p2 = plot_correlation_heatmaps(figures_dir, readme_dir)
    print(f"  [2/4] Saved: {p2.name} (Enhanced spacious layout, bold contrast)")

    p3 = plot_plutus_3hd_comparison(figures_dir, readme_dir)
    print(f"  [3/4] Saved: {p3.name}")

    p4 = plot_alpha_vs_filter_comparison(figures_dir, readme_dir)
    print(f"  [4/4] Saved: {p4.name} (Direct empirical proof of PDF thesis)")

    print("All 4 English plots generated successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

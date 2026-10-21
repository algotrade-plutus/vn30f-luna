#!/usr/bin/env python3
"""Comprehensive evaluation of Calibrum individual sleeves, pairs, correlations, and ensemble methods.

Implements Tasks T2, T3, T4, and T5:
- T2: Individual sleeves (Ridge H2, Shinji, Calendar) across IS, OOS, FWD, and Full life-cycle.
- T3: Sleeve pairs (R+S, R+C, S+C) and full ensemble (R+S+C).
- T4: Correlation matrices (daily Net PnL and bar positions) across all periods.
- T5: Ensemble method comparison (Majority Voting, Sum/Equal Weight, Consensus >= 2,
      No-Conflict, Static Weights, Dynamic Rolling, Stacking).

Execution engine: Local Lab Engine with DNSE continuous front-month data (default).
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

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
    SUMMARY_METRIC_KEYS,
    evaluate,
    format_number,
    load_research_frames,
    write_json_report,
)
from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    apply_session_rules,
    generate_calibrum_position_stream,
)
from src.lab.backtest import BacktestConfig  # noqa: E402

PERIODS: dict[str, tuple[str, str]] = {
    "IS": ("2021-06-01", "2022-12-30"),
    "OOS": ("2023-01-01", "2024-12-19"),
    "FWD": ("2026-01-01", "2026-10-01"),
    "FULL": ("2021-06-01", "2026-10-01"),
}

SLEEVE_NAMES = ("Ridge", "Shinji", "Calendar")
SLEEVE_KEYS = {"Ridge": "R", "Shinji": "S", "Calendar": "C"}


def filter_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    start_str, end_str = PERIODS[period]
    start_dt = pd.Timestamp(start_str)
    end_dt = pd.Timestamp(end_str) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    return df[(df.Datetime >= start_dt) & (df.Datetime <= end_dt)].reset_index(drop=True)


def evaluate_stream(
    stream: pd.DataFrame,
    fee: float,
    max_position: float = 1.0,
    discrete: bool = True,
) -> Any:
    cfg = BacktestConfig(
        round_trip_fee_points=fee,
        max_position=max_position,
        require_discrete_position=discrete,
    )
    return evaluate(stream, cfg)


def compute_daily_pnl_series(stream: pd.DataFrame, fee: float) -> pd.Series:
    res = evaluate_stream(stream, fee=fee, max_position=stream.Position.abs().max() or 1.0, discrete=False)
    return res.aggregates.daily.NetGain


def run_ensemble_research(
    source: str = "dnse",
    cache_dir: str | Path | None = None,
    allow_fetch: bool = False,
    fee: float = DEFAULT_FEE,
    output_report: str | Path = "reports/ensemble_research_report.json",
) -> dict[str, Any]:
    print("=" * 90)
    print("CALIBRUM SLEEVE & ENSEMBLE RESEARCH PIPELINE (STEPS 1-6 LAB)")
    print(f"Data source: {source} | Fee: {fee} pts/round-trip")
    print("=" * 90)

    # 1. Load data
    futures, spot, data_meta = load_research_frames(
        source,
        date(2021, 6, 1),
        date(2026, 10, 1),
        cache_dir=cache_dir,
        allow_fetch=allow_fetch,
    )

    # 2. Generate baseline stream containing individual sleeves
    base_stream, diagnostics = generate_calibrum_position_stream(
        futures,
        spot,
        PACKAGE_DIR,
    )
    def make_sleeve_stream(pos_series: np.ndarray | pd.Series) -> pd.DataFrame:
        # Same ATC and expiry rules as the ensemble stream
        pos = apply_session_rules(np.asarray(pos_series, dtype=float), base_stream.Datetime)
        return pd.DataFrame({
            "Datetime": base_stream.Datetime,
            "Close": base_stream.Close,
            "Position": pos,
        })

    # Pre-build sleeve streams
    sleeve_streams = {
        name: make_sleeve_stream(base_stream[name])
        for name in SLEEVE_NAMES
    }

    # -------------------------------------------------------------------------
    # PART 1 & 2: 7 Subelements (3 Sleeves, 3 Pairs, 1 Triplet)
    # -------------------------------------------------------------------------
    combos = {
        "Ridge (R)": sleeve_streams["Ridge"],
        "Shinji (S)": sleeve_streams["Shinji"],
        "Calendar (C)": sleeve_streams["Calendar"],
        "Pair R+S (Vote)": make_sleeve_stream(np.sign(base_stream.Ridge + base_stream.Shinji)),
        "Pair R+C (Vote)": make_sleeve_stream(np.sign(base_stream.Ridge + base_stream.Calendar)),
        "Pair S+C (Vote)": make_sleeve_stream(np.sign(base_stream.Shinji + base_stream.Calendar)),
        "Triplet R+S+C (Vote Baseline)": make_sleeve_stream(base_stream.Position),
    }

    results_table: list[dict[str, Any]] = []
    daily_pnls: dict[str, dict[str, pd.Series]] = {p: {} for p in PERIODS}

    for name, stream_df in combos.items():
        row_data: dict[str, Any] = {"name": name}
        for period in PERIODS:
            p_stream = filter_period(stream_df, period)
            res = evaluate_stream(p_stream, fee=fee, max_position=1.0, discrete=True)
            m = res.metrics
            daily_pnls[period][name] = res.aggregates.daily.NetGain
            row_data[f"{period}_Net"] = m.profit_after_fee
            row_data[f"{period}_Sharpe"] = m.sharpe_after_fee
            row_data[f"{period}_MDD"] = m.mdd_points
            row_data[f"{period}_Trades"] = m.total_trading_quantity
            row_data[f"{period}_HitRate"] = m.hit_rate
            row_data[f"{period}_Calmar"] = m.calmar_after_fee
            row_data[f"{period}_Sortino"] = m.sortino_after_fee
            row_data[f"{period}_ReturnYr"] = m.return_per_year
        results_table.append(row_data)

    combos_df = pd.DataFrame(results_table)

    print("\n" + "=" * 90)
    print("PHẦN 1 & 2: HIỆU SUẤT 7 TỔ HỢP ALPHA (3 RIÊNG LẺ, 3 CẶP, VÀ CẢ BA)")
    print("=" * 90)
    headers = [
        "Tổ Hợp Alpha",
        "IS Net (pts)", "IS Sharpe", "IS MDD",
        "OOS Net (pts)", "OOS Sharpe", "OOS MDD",
        "FWD Net (pts)", "FWD Sharpe", "FWD MDD",
        "Full Net (pts)", "Full Sharpe",
    ]
    print(f"{headers[0]:<30} | {headers[1]:>12} {headers[2]:>9} {headers[3]:>8} | {headers[4]:>13} {headers[5]:>10} {headers[6]:>8} | {headers[7]:>13} {headers[8]:>10} {headers[9]:>8} | {headers[10]:>14} {headers[11]:>11}")
    print("-" * 155)
    for row in results_table:
        print(
            f"{row['name']:<30} | "
            f"{format_number(row['IS_Net'], '{:12.1f}')} {format_number(row['IS_Sharpe'], '{:9.2f}')} {format_number(row['IS_MDD'], '{:8.1f}')} | "
            f"{format_number(row['OOS_Net'], '{:13.1f}')} {format_number(row['OOS_Sharpe'], '{:10.2f}')} {format_number(row['OOS_MDD'], '{:8.1f}')} | "
            f"{format_number(row['FWD_Net'], '{:13.1f}')} {format_number(row['FWD_Sharpe'], '{:10.2f}')} {format_number(row['FWD_MDD'], '{:8.1f}')} | "
            f"{format_number(row['FULL_Net'], '{:14.1f}')} {format_number(row['FULL_Sharpe'], '{:11.2f}')}"
        )

    # -------------------------------------------------------------------------
    # PART 3: Ma Trận Tương Quan (Daily PnL & Position)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print("PHẦN 3: MA TRẬN TƯƠNG QUAN GIỮA CÁC ALPHA SLEEVES")
    print("=" * 90)
    correlations: dict[str, dict[str, Any]] = {}

    for period in ("IS", "OOS", "FWD", "FULL"):
        p_df = filter_period(base_stream, period)
        # Position correlation (bar-level)
        pos_corr = p_df[list(SLEEVE_NAMES)].corr().round(3).to_dict()

        # Daily Net PnL correlation
        sleeve_pnl = pd.DataFrame({
            name: daily_pnls[period][f"{name} ({SLEEVE_KEYS[name]})"]
            for name in SLEEVE_NAMES
        })
        pnl_corr = sleeve_pnl.corr().round(3).to_dict()
        correlations[period] = {
            "pnl_correlation": pnl_corr,
            "position_correlation": pos_corr,
        }

        print(f"\n--- Kỳ {period} ({PERIODS[period][0]} → {PERIODS[period][1]}) ---")
        print("Tương quan Lãi/Lỗ theo ngày (Daily Net PnL Correlation):")
        print(sleeve_pnl.corr().round(3).to_string())
        print("\nTương quan Vị thế theo bar (Position Correlation):")
        print(p_df[list(SLEEVE_NAMES)].corr().round(3).to_string())

    # -------------------------------------------------------------------------
    # PART 4: So Sánh Nâng Cao Các Phương Pháp Ensemble
    # -------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print("PHẦN 4: SO SÁNH CÁC PHƯƠNG PHÁP ENSEMBLE (TỔNG HỢP VỊ THẾ)")
    print("=" * 90)

    # Sleeve positions as raw arrays
    R_raw = base_stream.Ridge.to_numpy(float)
    S_raw = base_stream.Shinji.to_numpy(float)
    C_raw = base_stream.Calendar.to_numpy(float)

    # Calculate static weights on IS only
    is_pnl = pd.DataFrame({
        name: daily_pnls["IS"][f"{name} ({SLEEVE_KEYS[name]})"]
        for name in SLEEVE_NAMES
    })
    invvol_w = (1.0 / is_pnl.std()).to_numpy()
    invvol_w = invvol_w / invvol_w.sum()

    sharpe_w = np.clip(is_pnl.mean() / is_pnl.std(), 0.0, None).to_numpy()
    sharpe_w = sharpe_w / sharpe_w.sum()

    cov = is_pnl.cov().to_numpy()
    mv_w = np.clip(np.linalg.solve(cov, is_pnl.mean().to_numpy()), 0.0, None)
    mv_w = mv_w / mv_w.sum()

    methods: dict[str, dict[str, Any]] = {
        "1. Majority Voting (Baseline)": {
            "stream": make_sleeve_stream(np.sign(R_raw + S_raw + C_raw)),
            "max_pos": 1.0,
            "discrete": True,
            "desc": "sign(R + S + C) ∈ {-1, 0, +1}; 1 hợp đồng",
        },
        "2. Cộng Vị Thế Đều (3 HĐ)": {
            "stream": make_sleeve_stream(R_raw + S_raw + C_raw),
            "max_pos": 3.0,
            "discrete": True,
            "desc": "R + S + C ∈ {-3..+3}; chạy 3 hợp đồng độc lập",
        },
        "3. Cộng Vị Thế Chuẩn Hóa (1 HĐ)": {
            "stream": make_sleeve_stream((R_raw + S_raw + C_raw) / 3.0),
            "max_pos": 1.0,
            "discrete": False,
            "desc": "(R + S + C) / 3 ∈ [-1, 1]; quy về 1 hợp đồng để so điểm",
        },
        "4. Đồng Thuận Tuyệt Đối (>=2 alpha)": {
            "stream": make_sleeve_stream(np.where(np.abs(R_raw + S_raw + C_raw) >= 2, np.sign(R_raw + S_raw + C_raw), 0)),
            "max_pos": 1.0,
            "discrete": True,
            "desc": "Chỉ vào lệnh khi có ít nhất 2 alpha đồng thuận; còn lại 0",
        },
        "5. Triệt Tiêu Khi Xung Đột (No-Conflict)": {
            "stream": make_sleeve_stream(
                np.where(
                    (np.maximum.reduce([R_raw, S_raw, C_raw]) > 0) & (np.minimum.reduce([R_raw, S_raw, C_raw]) < 0),
                    0,
                    np.sign(R_raw + S_raw + C_raw),
                )
            ),
            "max_pos": 1.0,
            "discrete": True,
            "desc": "Ra flat (0) ngay khi có 2 alpha phát tín hiệu ngược chiều",
        },
        "6. Trọng Số Tĩnh Inverse-Vol (IS Fit)": {
            "stream": make_sleeve_stream(np.sign(invvol_w[0] * R_raw + invvol_w[1] * S_raw + invvol_w[2] * C_raw)),
            "max_pos": 1.0,
            "discrete": True,
            "desc": f"Trọng số IS 1/vol: R={invvol_w[0]:.2f}, S={invvol_w[1]:.2f}, C={invvol_w[2]:.2f}",
        },
        "7. Trọng Số Tĩnh Sharpe (IS Fit)": {
            "stream": make_sleeve_stream(np.sign(sharpe_w[0] * R_raw + sharpe_w[1] * S_raw + sharpe_w[2] * C_raw)),
            "max_pos": 1.0,
            "discrete": True,
            "desc": f"Trọng số IS Sharpe: R={sharpe_w[0]:.2f}, S={sharpe_w[1]:.2f}, C={sharpe_w[2]:.2f}",
        },
        "8. Trọng Số Tĩnh Mean-Variance (IS Fit)": {
            "stream": make_sleeve_stream(np.sign(mv_w[0] * R_raw + mv_w[1] * S_raw + mv_w[2] * C_raw)),
            "max_pos": 1.0,
            "discrete": True,
            "desc": f"Trọng số IS Markowitz: R={mv_w[0]:.2f}, S={mv_w[1]:.2f}, C={mv_w[2]:.2f}",
        },
    }

    ensemble_rows: list[dict[str, Any]] = []
    full_metrics_export: dict[str, Any] = {}

    for m_name, m_cfg in methods.items():
        row_dict: dict[str, Any] = {
            "method": m_name,
            "description": m_cfg["desc"],
        }
        full_metrics_export[m_name] = {}
        for period in PERIODS:
            p_stream = filter_period(m_cfg["stream"], period)
            res = evaluate_stream(
                p_stream,
                fee=fee,
                max_position=m_cfg["max_pos"],
                discrete=m_cfg["discrete"],
            )
            m = res.metrics
            full_metrics_export[m_name][period] = m.as_dict()

            row_dict[f"{period}_Net"] = m.profit_after_fee
            row_dict[f"{period}_Sharpe"] = m.sharpe_after_fee
            row_dict[f"{period}_MDD"] = m.mdd_points
            row_dict[f"{period}_Sortino"] = m.sortino_after_fee
            row_dict[f"{period}_Calmar"] = m.calmar_after_fee
            row_dict[f"{period}_ReturnYr"] = m.return_per_year
            row_dict[f"{period}_ProfitFactor"] = m.profit_factor
            row_dict[f"{period}_Exposure"] = m.exposure_rate

        ensemble_rows.append(row_dict)

    ens_headers = [
        "Phương Pháp Ensemble",
        "IS Net", "IS Sh", "IS MDD",
        "OOS Net", "OOS Sh", "OOS MDD",
        "FWD Net", "FWD Sh", "FWD MDD",
        "Full Net", "Full Sh", "Full MDD",
    ]
    print(f"{ens_headers[0]:<40} | {ens_headers[1]:>9} {ens_headers[2]:>6} {ens_headers[3]:>7} | {ens_headers[4]:>9} {ens_headers[5]:>7} {ens_headers[6]:>7} | {ens_headers[7]:>9} {ens_headers[8]:>7} {ens_headers[9]:>7} | {ens_headers[10]:>9} {ens_headers[11]:>7} {ens_headers[12]:>8}")
    print("-" * 155)
    for r in ensemble_rows:
        print(
            f"{r['method']:<40} | "
            f"{format_number(r['IS_Net'], '{:9.1f}')} {format_number(r['IS_Sharpe'], '{:6.2f}')} {format_number(r['IS_MDD'], '{:7.1f}')} | "
            f"{format_number(r['OOS_Net'], '{:9.1f}')} {format_number(r['OOS_Sharpe'], '{:7.2f}')} {format_number(r['OOS_MDD'], '{:7.1f}')} | "
            f"{format_number(r['FWD_Net'], '{:9.1f}')} {format_number(r['FWD_Sharpe'], '{:7.2f}')} {format_number(r['FWD_MDD'], '{:7.1f}')} | "
            f"{format_number(r['FULL_Net'], '{:9.1f}')} {format_number(r['FULL_Sharpe'], '{:7.2f}')} {format_number(r['FULL_MDD'], '{:8.1f}')}"
        )

    # -------------------------------------------------------------------------
    # PART 5: Xuất Báo Cáo JSON
    # -------------------------------------------------------------------------
    payload = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "source": source,
        "fee": fee,
        "periods": PERIODS,
        "data_meta": data_meta,
        "combos_7_subsets": results_table,
        "correlations": correlations,
        "ensemble_methods": ensemble_rows,
        "full_metrics": full_metrics_export,
    }
    report_file = write_json_report(output_report, payload)
    print(f"\n✅ Đã lưu toàn bộ kết quả nghiên cứu vào: {report_file}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("dnse", "db"), default="dnse")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--fee", type=float, default=DEFAULT_FEE)
    parser.add_argument("--report", default="reports/ensemble_research_report.json")
    args = parser.parse_args()

    run_ensemble_research(
        source=args.source,
        cache_dir=args.cache_dir,
        allow_fetch=not args.no_fetch,
        fee=args.fee,
        output_report=args.report,
    )


if __name__ == "__main__":
    main()

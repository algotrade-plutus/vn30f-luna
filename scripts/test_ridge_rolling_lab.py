#!/usr/bin/env python3
"""Experiment: Test Ridge normalization using Rolling Z-Score vs Static Train Parameters.

Evaluates performance using src/lab/backtest on:
1. Ridge Standalone Sleeve
2. Calibrum Full Ensemble (Ridge + Shinji + Calendar)
Across In-Sample (IS: 2021-2022), Out-of-Sample (OOS: 2023-2026), and Full History.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

PACKAGE_DIR = WORKSPACE / "PS_V30_Vien_Calibrum"

from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    _CONFIG_NAME,
    _MODEL_NAME,
    _FrameFeed,
    _load_frozen_module,
    _load_json,
)
from src.lab.backtest import BacktestConfig, evaluate  # noqa: E402


def build_ridge_features(
    regular: pd.DataFrame,
    hour_min: pd.Series,
    safe_ratio_fn: Any,
) -> pd.DataFrame:
    """Compute the 5 technical features used by Ridge H2."""
    regular_hour_min = hour_min.loc[regular.index]
    close = regular["Close"].astype(float)
    open_ = regular["Open"].astype(float)
    high = regular["High"].astype(float)
    low = regular["Low"].astype(float)
    volume = regular["Volume"].astype(float)

    true_range = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    atr14 = true_range.shift(1).rolling(14, min_periods=14).mean()
    day = regular["Datetime"].dt.normalize()
    complete = (
        regular[["Open", "High", "Low", "Close", "Volume"]]
        .notna()
        .all(axis=1)
        .groupby(day)
        .cummin()
    )
    first_open = open_.where(regular_hour_min == "09:00").groupby(day).transform("first")
    vwap = safe_ratio_fn(
        ((((high + low + close) / 3.0) * volume).groupby(day).cumsum()),
        volume.groupby(day).cumsum(),
    )
    feature_vwap = safe_ratio_fn(close - vwap, atr14).where(complete)
    feature_open = safe_ratio_fn(close - first_open, atr14).where(complete)
    feature_trend = safe_ratio_fn(close - close.rolling(4, min_periods=4).mean(), atr14)
    up_squared = close.diff().clip(lower=0) ** 2
    down_squared = close.diff().clip(upper=0) ** 2
    up4 = up_squared.rolling(4, min_periods=4).sum()
    down4 = down_squared.rolling(4, min_periods=4).sum()
    feature_asymmetry = safe_ratio_fn(up4 - down4, up4 + down4)
    feature_body = safe_ratio_fn(close - open_, atr14)

    return pd.DataFrame(
        {
            "vwap": feature_vwap,
            "open": feature_open,
            "trend": feature_trend,
            "asym": feature_asymmetry,
            "body": feature_body,
        },
        index=regular.index,
    )


def compute_ridge_positions(
    working: pd.DataFrame,
    df_feat: pd.DataFrame,
    regular_index: pd.Index,
    parameters: dict[str, Any],
    model: dict[str, Any],
    *,
    normalization_mode: str = "train",  # 'train', 'rolling', 'expanding'
    window: int = 1000,
    scale_asym: bool = True,
    causal_shift: bool = False,
    min_periods: int = 20,
) -> np.ndarray:
    """Generate Ridge positions using specified feature normalization."""
    hour_min = working["Datetime"].dt.strftime("%H:%M")

    if normalization_mode == "train":
        features = df_feat.to_numpy(float)
        scaled = np.clip(
            (features - model["ridge_centers"]) / model["ridge_scales"], -8.0, 8.0
        )
    elif normalization_mode == "rolling":
        if causal_shift:
            r_mean = df_feat.shift(1).rolling(window, min_periods=min_periods).mean()
            r_std = df_feat.shift(1).rolling(window, min_periods=min_periods).std()
        else:
            r_mean = df_feat.rolling(window, min_periods=min_periods).mean()
            r_std = df_feat.rolling(window, min_periods=min_periods).std()

        if not scale_asym:
            r_mean["asym"] = 0.0
            r_std["asym"] = 1.0

        scaled_df = (df_feat - r_mean) / (r_std.replace(0, np.nan).fillna(1.0) + 1e-6)
        scaled = np.clip(scaled_df.fillna(0.0).to_numpy(float), -8.0, 8.0)
    elif normalization_mode == "expanding":
        r_mean = df_feat.expanding(min_periods=min_periods).mean()
        r_std = df_feat.expanding(min_periods=min_periods).std()
        if not scale_asym:
            r_mean["asym"] = 0.0
            r_std["asym"] = 1.0
        scaled_df = (df_feat - r_mean) / (r_std.replace(0, np.nan).fillna(1.0) + 1e-6)
        scaled = np.clip(scaled_df.fillna(0.0).to_numpy(float), -8.0, 8.0)
    else:
        raise ValueError(f"Unknown normalization_mode: {normalization_mode}")

    regular_score = model["ridge_intercept"] + scaled @ model["ridge_coef"]
    score = pd.Series(regular_score, index=regular_index).reindex(working.index).to_numpy()

    entry_threshold = float(parameters.get("ridge_entry_threshold", 0.18))
    min_hold = int(parameters.get("ridge_min_hold", 2))
    max_hold = int(parameters.get("ridge_max_hold", 8))
    stop_loss = float(parameters.get("ridge_stop_loss_pts", 10.0))

    position = np.zeros(len(working), dtype=int)
    current = 0
    bars_held = 0
    entry_price = 0.0
    clocks = hour_min.to_numpy()
    closes = working["Close"].to_numpy(float)

    for index in range(14, len(working)):
        if clocks[index] == "14:30":
            position[index] = current
            continue
        current_score = score[index]
        current_price = closes[index]
        if np.isnan(current_score):
            position[index] = current
            continue
        if current != 0:
            bars_held += 1
            unrealized = current * (current_price - entry_price)
            score_exit = bars_held >= min_hold and (
                (current == 1 and current_score < 0.0)
                or (current == -1 and current_score > 0.0)
            )
            if unrealized <= -stop_loss or score_exit or bars_held >= max_hold:
                current = 0
                bars_held = 0
                entry_price = 0.0
        if current == 0:
            if current_score >= entry_threshold:
                current = 1
                bars_held = 0
                entry_price = current_price
            elif current_score <= -entry_threshold:
                current = -1
                bars_held = 0
                entry_price = current_price
        position[index] = current

    return position


def run_ensemble(
    ridge_pos: np.ndarray,
    shinji_pos: np.ndarray,
    calendar_pos: np.ndarray,
    clean_futures: pd.DataFrame,
    weights: np.ndarray,
) -> np.ndarray:
    """Combine sleeves into standard Calibrum ensemble voting position."""
    raw_pos = np.sign(
        weights[0] * ridge_pos + weights[1] * shinji_pos + weights[2] * calendar_pos
    ).astype(int)
    clocks = clean_futures["Datetime"].dt.strftime("%H:%M").to_numpy()
    for index in np.flatnonzero(clocks == "14:30"):
        if index > 0:
            raw_pos[index] = raw_pos[index - 1]
    return raw_pos


def evaluate_stream(
    clean_futures: pd.DataFrame,
    position: np.ndarray,
    fee: float = 0.8,
) -> dict[str, Any]:
    """Evaluate full, IS, and OOS slices using src.lab.backtest."""
    cfg = BacktestConfig(round_trip_fee_points=fee)
    stream = clean_futures[["Datetime", "Close"]].copy()
    stream["Position"] = position

    def extract_metrics(sub_stream: pd.DataFrame) -> dict[str, float | int]:
        if len(sub_stream) < 50:
            return {}
        res = evaluate(sub_stream, cfg)
        m = res.metrics
        return {
            "sharpe": float(m.sharpe_after_fee),
            "margin": float(m.margin_after_fee),
            "pnl": float(m.profit_after_fee),
            "trades": int(m.long_trades + m.short_trades),
            "mdd_pts": float(m.mdd_points),
            "mdd_pct": float(m.mdd_percent),
            "hit_rate": float(m.hit_rate),
            "profit_factor": float(m.profit_factor),
        }

    full_res = extract_metrics(stream)
    is_res = extract_metrics(stream[stream["Datetime"] <= "2022-12-30 23:59:59"])
    oos_res = extract_metrics(stream[stream["Datetime"] >= "2023-01-01"])

    return {"full": full_res, "is": is_res, "oos": oos_res}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--futures",
        default="data/dnse/derivative_vn30f1m_30m.parquet",
        help="Path to VN30F1M 30m parquet",
    )
    parser.add_argument(
        "--spot",
        default="data/dnse/index_vn30_30m.parquet",
        help="Path to VN30 30m parquet",
    )
    parser.add_argument(
        "--fee",
        type=float,
        default=0.8,
        help="Round-trip fee in points (default: 0.8)",
    )
    args = parser.parse_args()

    frozen = _load_frozen_module(PACKAGE_DIR)
    config = _load_json(PACKAGE_DIR / _CONFIG_NAME)
    parameters = config["parameters"]
    model = frozen._load_model(PACKAGE_DIR / _MODEL_NAME)

    df_fut = pd.read_parquet(args.futures)
    df_spot = pd.read_parquet(args.spot)

    clean_futures = frozen._clean_frame(_FrameFeed(df_fut), "VN30F1M/30m")
    clean_spot = frozen._clean_frame(_FrameFeed(df_spot), "VN30/30m")

    hour_min = clean_futures["Datetime"].dt.strftime("%H:%M")
    regular = clean_futures.loc[hour_min.isin(frozen.REGULAR_CLOCKS)]
    df_feat = build_ridge_features(regular, hour_min, frozen._safe_ratio)

    shinji_pos = frozen._shinji_positions(clean_futures, clean_spot, parameters)
    calendar_pos = frozen._calendar_positions(clean_futures, parameters)
    weights = np.asarray(model["ensemble_weights"])

    # Define variants to evaluate
    variants = [
        ("Baseline (Train Params)", {"normalization_mode": "train"}),
        ("Rolling W=250 (asym scaled)", {"normalization_mode": "rolling", "window": 250, "scale_asym": True}),
        ("Rolling W=500 (asym scaled)", {"normalization_mode": "rolling", "window": 500, "scale_asym": True}),
        ("Rolling W=1000 (asym scaled)", {"normalization_mode": "rolling", "window": 1000, "scale_asym": True}),
        ("Rolling W=1500 (asym scaled)", {"normalization_mode": "rolling", "window": 1500, "scale_asym": True}),
        ("Rolling W=2000 (asym scaled)", {"normalization_mode": "rolling", "window": 2000, "scale_asym": True}),
        ("Rolling W=3000 (asym scaled)", {"normalization_mode": "rolling", "window": 3000, "scale_asym": True}),
        ("Expanding (asym scaled)", {"normalization_mode": "expanding", "scale_asym": True}),
        ("Rolling W=500 (asym raw)", {"normalization_mode": "rolling", "window": 500, "scale_asym": False}),
        ("Rolling W=1000 (asym raw)", {"normalization_mode": "rolling", "window": 1000, "scale_asym": False}),
        ("Rolling W=2000 (asym raw)", {"normalization_mode": "rolling", "window": 2000, "scale_asym": False}),
        ("Rolling W=1000 (causal shift)", {"normalization_mode": "rolling", "window": 1000, "scale_asym": True, "causal_shift": True}),
    ]

    ridge_results = []
    ensemble_results = []

    print("\n" + "=" * 80)
    print("CHẠY THỬ NGHIỆM CHUẨN HOÁ RIDGE (TRAIN PARAMS vs ROLLING Z-SCORE) QUA SRC/LAB")
    print("=" * 80)

    for label, kwargs in variants:
        r_pos = compute_ridge_positions(
            clean_futures, df_feat, regular.index, parameters, model, **kwargs
        )
        ens_pos = run_ensemble(r_pos, shinji_pos, calendar_pos, clean_futures, weights)

        ridge_results.append((label, evaluate_stream(clean_futures, r_pos, fee=args.fee)))
        ensemble_results.append((label, evaluate_stream(clean_futures, ens_pos, fee=args.fee)))

    print("\n[1] KẾT QUẢ RIDGE STANDALONE (SLEEVE 1 ĐƠN LẺ):")
    print("-" * 115)
    print(
        f"{'Cấu hình':<32} | {'Full Sh':<7} | {'Full PnL':<8} | {'IS Sh':<6} | {'IS PnL':<7} | {'OOS Sh':<6} | {'OOS PnL':<7} | {'MDD Pts':<7} | {'PF':<5}"
    )
    print("-" * 115)
    for label, res in ridge_results:
        f = res["full"]
        i = res["is"]
        o = res["oos"]
        print(
            f"{label:<32} | {f['sharpe']:>7.2f} | {f['pnl']:>8.1f} | {i['sharpe']:>6.2f} | {i['pnl']:>7.1f} | {o['sharpe']:>6.2f} | {o['pnl']:>7.1f} | {f['mdd_pts']:>7.1f} | {f['profit_factor']:>5.2f}"
        )

    print("\n[2] KẾT QUẢ CALIBRUM ENSEMBLE (RIDGE + SHINJI + CALENDAR):")
    print("-" * 115)
    print(
        f"{'Cấu hình':<32} | {'Full Sh':<7} | {'Full PnL':<8} | {'IS Sh':<6} | {'IS PnL':<7} | {'OOS Sh':<6} | {'OOS PnL':<7} | {'MDD Pts':<7} | {'PF':<5}"
    )
    print("-" * 115)
    for label, res in ensemble_results:
        f = res["full"]
        i = res["is"]
        o = res["oos"]
        print(
            f"{label:<32} | {f['sharpe']:>7.2f} | {f['pnl']:>8.1f} | {i['sharpe']:>6.2f} | {i['pnl']:>7.1f} | {o['sharpe']:>6.2f} | {o['pnl']:>7.1f} | {f['mdd_pts']:>7.1f} | {f['profit_factor']:>5.2f}"
        )


if __name__ == "__main__":
    main()

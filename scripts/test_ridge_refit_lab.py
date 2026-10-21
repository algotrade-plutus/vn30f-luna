#!/usr/bin/env python3
"""Comprehensive Lab Experiment: Testing Ridge Re-fitting & Walk-Forward vs Baseline.

Experiments tested:
1. Baseline Frozen Model (Train 2020-2022 parameters)
2. Rolling Window Walk-Forward Refit (Refit model on rolling past W bars)
3. Expanding Window Walk-Forward Refit (Refit model on cumulative past data, updated monthly)
Evaluated with src/lab/backtest.
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
            "atr14": atr14,
            "Close": close,
        },
        index=regular.index,
    )


def simulate_state_machine(
    working: pd.DataFrame,
    regular_index: pd.Index,
    score_series: np.ndarray,
    parameters: dict[str, Any],
) -> np.ndarray:
    score = pd.Series(score_series, index=regular_index).reindex(working.index).to_numpy()
    entry_threshold = float(parameters.get("ridge_entry_threshold", 0.18))
    min_hold = int(parameters.get("ridge_min_hold", 2))
    max_hold = int(parameters.get("ridge_max_hold", 8))
    stop_loss = float(parameters.get("ridge_stop_loss_pts", 10.0))

    clocks = working["Datetime"].dt.strftime("%H:%M").to_numpy()
    closes = working["Close"].to_numpy(float)
    position = np.zeros(len(working), dtype=int)
    current = 0
    bars_held = 0
    entry_price = 0.0

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
    raw_pos = np.sign(
        weights[0] * ridge_pos + weights[1] * shinji_pos + weights[2] * calendar_pos
    ).astype(int)
    clocks = clean_futures["Datetime"].dt.strftime("%H:%M").to_numpy()
    for index in np.flatnonzero(clocks == "14:30"):
        if index > 0:
            raw_pos[index] = raw_pos[index - 1]
    return raw_pos


def eval_stream(
    clean_futures: pd.DataFrame,
    position: np.ndarray,
    fee: float = 0.8,
) -> dict[str, Any]:
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
            "profit_factor": float(m.profit_factor),
        }

    return {
        "full": extract_metrics(stream),
        "is": extract_metrics(stream[stream["Datetime"] <= "2022-12-30 23:59:59"]),
        "oos": extract_metrics(stream[stream["Datetime"] >= "2023-01-01"]),
    }


def fit_ridge_closed_form(X: np.ndarray, y: np.ndarray, alpha: float) -> tuple[float, np.ndarray]:
    """Fit Ridge with bias unpenalized."""
    X_bias = np.column_stack([np.ones(len(X)), X])
    reg = np.eye(X_bias.shape[1]) * alpha
    reg[0, 0] = 0.0
    beta = np.linalg.solve(X_bias.T @ X_bias + reg, X_bias.T @ y)
    return float(beta[0]), beta[1:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--futures", default="data/dnse/derivative_vn30f1m_30m.parquet")
    parser.add_argument("--spot", default="data/dnse/index_vn30_30m.parquet")
    parser.add_argument("--fee", type=float, default=0.8)
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
    feat_df = build_ridge_features(regular, hour_min, frozen._safe_ratio)

    feature_cols = ["vwap", "open", "trend", "asym", "body"]
    X_raw = feat_df[feature_cols].to_numpy(float)

    # 2-bar forward return normalized by ATR14 (The true Ridge H2 target)
    close_arr = feat_df["Close"].to_numpy(float)
    atr_arr = feat_df["atr14"].to_numpy(float)
    k = 2
    y_target = (np.roll(close_arr, -k) - close_arr) / atr_arr
    y_target[-k:] = np.nan

    shinji_pos = frozen._shinji_positions(clean_futures, clean_spot, parameters)
    calendar_pos = frozen._calendar_positions(clean_futures, parameters)
    weights = np.asarray(model["ensemble_weights"])

    print("\n" + "=" * 90)
    print("THỬ NGHIỆM FIT LẠI MÔ HÌNH RIDGE (WALK-FORWARD ROLLING & EXPANDING) QUA SRC/LAB")
    print("=" * 90)

    results = []

    # 1. Baseline
    baseline_ridge = frozen._ridge_positions(clean_futures, parameters, model)
    results.append(("Baseline Frozen (Static)", eval_stream(clean_futures, baseline_ridge, fee=args.fee), eval_stream(clean_futures, run_ensemble(baseline_ridge, shinji_pos, calendar_pos, clean_futures, weights), fee=args.fee)))

    # 2. Walk-forward Rolling (Fixed Window W)
    for w in [500, 1000, 1500, 2000]:
        for alpha in [10.0, 50.0]:
            scores = np.full(len(regular), np.nan)
            step = 50  # update every ~6 trading days
            for t in range(w, len(regular), step):
                X_train = X_raw[t - w : t]
                y_train = y_target[t - w : t]
                valid = np.isfinite(X_train).all(axis=1) & np.isfinite(y_train)
                if valid.sum() < w // 2:
                    continue
                centers = np.median(X_train[valid], axis=0)
                q75, q25 = np.percentile(X_train[valid], [75, 25], axis=0)
                scales = q75 - q25
                scales[scales < 1e-4] = 1.0
                scales[3] = 1.0
                X_scaled = np.clip((X_train[valid] - centers) / scales, -8.0, 8.0)
                b0, beta = fit_ridge_closed_form(X_scaled, y_train[valid], alpha)

                eval_idx = slice(t, min(t + step, len(regular)))
                X_test = X_raw[eval_idx]
                X_test_scaled = np.clip((X_test - centers) / scales, -8.0, 8.0)
                scores[eval_idx] = b0 + X_test_scaled @ beta

            r_pos = simulate_state_machine(clean_futures, regular.index, scores, parameters)
            ens_pos = run_ensemble(r_pos, shinji_pos, calendar_pos, clean_futures, weights)
            results.append((f"Rolling WF (W={w}, a={alpha})", eval_stream(clean_futures, r_pos, fee=args.fee), eval_stream(clean_futures, ens_pos, fee=args.fee)))

    # 3. Walk-forward Expanding Window (Monthly update in OOS)
    is_end_idx = np.where(regular["Datetime"] <= "2022-12-30 23:59:59")[0][-1] + 1
    for alpha in [10.0, 50.0, 100.0]:
        scores = np.full(len(regular), np.nan)
        # IS fit
        X_is = X_raw[:is_end_idx]
        y_is = y_target[:is_end_idx]
        valid_is = np.isfinite(X_is).all(axis=1) & np.isfinite(y_is)
        centers_is = np.median(X_is[valid_is], axis=0)
        q75_is, q25_is = np.percentile(X_is[valid_is], [75, 25], axis=0)
        scales_is = q75_is - q25_is
        scales_is[scales_is < 1e-4] = 1.0
        scales_is[3] = 1.0
        X_is_scaled = np.clip((X_is[valid_is] - centers_is) / scales_is, -8.0, 8.0)
        b0_is, beta_is = fit_ridge_closed_form(X_is_scaled, y_is[valid_is], alpha)
        scores[:is_end_idx] = b0_is + np.clip((X_is - centers_is) / scales_is, -8.0, 8.0) @ beta_is

        # OOS Expanding fit every 200 bars (~ 1 month)
        step = 200
        for t in range(is_end_idx, len(regular), step):
            X_train = X_raw[:t]
            y_train = y_target[:t]
            valid = np.isfinite(X_train).all(axis=1) & np.isfinite(y_train)
            centers = np.median(X_train[valid], axis=0)
            q75, q25 = np.percentile(X_train[valid], [75, 25], axis=0)
            scales = q75 - q25
            scales[scales < 1e-4] = 1.0
            scales[3] = 1.0
            X_tr_scaled = np.clip((X_train[valid] - centers) / scales, -8.0, 8.0)
            b0, beta = fit_ridge_closed_form(X_tr_scaled, y_train[valid], alpha)

            eval_idx = slice(t, min(t + step, len(regular)))
            X_test = X_raw[eval_idx]
            X_test_scaled = np.clip((X_test - centers) / scales, -8.0, 8.0)
            scores[eval_idx] = b0 + X_test_scaled @ beta

        r_pos = simulate_state_machine(clean_futures, regular.index, scores, parameters)
        ens_pos = run_ensemble(r_pos, shinji_pos, calendar_pos, clean_futures, weights)
        results.append((f"Expanding WF (a={alpha})", eval_stream(clean_futures, r_pos, fee=args.fee), eval_stream(clean_futures, ens_pos, fee=args.fee)))

    # Output tables
    print("\n[A] RIDGE STANDALONE (SLEEVE 1):")
    print("-" * 110)
    print(f"{'Cấu hình':<30} | {'Full Sh':<7} | {'Full PnL':<8} | {'IS Sh':<6} | {'IS PnL':<7} | {'OOS Sh':<6} | {'OOS PnL':<7} | {'MDD Pts':<7} | {'PF':<5}")
    print("-" * 110)
    for label, r_res, _ in results:
        f = r_res["full"]
        i = r_res["is"]
        o = r_res["oos"]
        print(f"{label:<30} | {f['sharpe']:>7.2f} | {f['pnl']:>8.1f} | {i['sharpe']:>6.2f} | {i['pnl']:>7.1f} | {o['sharpe']:>6.2f} | {o['pnl']:>7.1f} | {f['mdd_pts']:>7.1f} | {f['profit_factor']:>5.2f}")

    print("\n[B] CALIBRUM ENSEMBLE (RIDGE + SHINJI + CALENDAR):")
    print("-" * 110)
    print(f"{'Cấu hình':<30} | {'Full Sh':<7} | {'Full PnL':<8} | {'IS Sh':<6} | {'IS PnL':<7} | {'OOS Sh':<6} | {'OOS PnL':<7} | {'MDD Pts':<7} | {'PF':<5}")
    print("-" * 110)
    for label, _, ens_res in results:
        f = ens_res["full"]
        i = ens_res["is"]
        o = ens_res["oos"]
        print(f"{label:<30} | {f['sharpe']:>7.2f} | {f['pnl']:>8.1f} | {i['sharpe']:>6.2f} | {i['pnl']:>7.1f} | {o['sharpe']:>6.2f} | {o['pnl']:>7.1f} | {f['mdd_pts']:>7.1f} | {f['profit_factor']:>5.2f}")


if __name__ == "__main__":
    main()

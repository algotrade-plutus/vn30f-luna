"""Momentum sleeve: Ridge refit on five intraday features (PROTOCOL.md section 3.2).

Features are computed on the eight regular 30-minute bars of an additive
roll-adjusted copy of the futures; positions are traded on raw prices.

    J(b0, b) = (1/n) * sum_t (y_t - b0 - z_t . b)^2 + lam * ||b||^2
    y_t      = (C[t+2] - C[t]) / ATR14[t]
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

REGULAR_CLOCKS = ("09:00", "09:30", "10:00", "10:30", "11:00", "13:00", "13:30", "14:00")
FEATURES = ("x1_vwap", "x2_open", "x3_trend", "x4_asym", "x5_body")
CLIP = 8.0
HORIZON = 2


def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator.where(denominator != 0)).replace([np.inf, -np.inf], np.nan)


def feature_frame(bars_adjusted: pd.DataFrame) -> pd.DataFrame:
    """Features and target on the regular 30-minute bars of a roll-adjusted frame.

    ``bars_adjusted`` holds Datetime, Open, High, Low, Close, Volume and Contract.
    Every feature at bar t uses bars up to t; the target uses t+1 and t+2 and is
    NaN when t+2 trades another contract.
    """
    clocks = bars_adjusted["Datetime"].dt.strftime("%H:%M")
    bars = bars_adjusted.loc[clocks.isin(REGULAR_CLOCKS)].reset_index(drop=True)
    close, open_ = bars["Close"], bars["Open"]
    high, low, volume = bars["High"], bars["Low"], bars["Volume"]
    day = bars["Datetime"].dt.normalize()

    true_range = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1, skipna=False)
    atr14 = true_range.shift().rolling(14, min_periods=14).mean()
    first_open = open_.where(bars["Datetime"].dt.strftime("%H:%M") == "09:00").groupby(day).transform("first")
    vwap = _ratio(
        ((high + low + close) / 3.0 * volume).groupby(day).cumsum(),
        volume.groupby(day).cumsum(),
    )
    up4 = (close.diff().clip(lower=0) ** 2).rolling(4, min_periods=4).sum()
    down4 = (close.diff().clip(upper=0) ** 2).rolling(4, min_periods=4).sum()

    out = bars[["Datetime", "Contract"]].copy()
    out["x1_vwap"] = _ratio(close - vwap, atr14)
    out["x2_open"] = _ratio(close - first_open, atr14)
    out["x3_trend"] = _ratio(close - close.rolling(4, min_periods=4).mean(), atr14)
    out["x4_asym"] = _ratio(up4 - down4, up4 + down4)
    out["x5_body"] = _ratio(close - open_, atr14)
    same_contract = bars["Contract"].shift(-HORIZON).eq(bars["Contract"])
    out["y"] = _ratio(close.shift(-HORIZON) - close, atr14).where(same_contract)
    return out


@dataclass(frozen=True)
class RidgeModel:
    lam: float
    median: np.ndarray
    iqr: np.ndarray
    beta0: float
    beta: np.ndarray

    def standardize(self, x: np.ndarray) -> np.ndarray:
        return np.clip((x - self.median) / self.iqr, -CLIP, CLIP)

    def score(self, x: np.ndarray) -> np.ndarray:
        """NaN wherever a feature is missing, so no decision is taken there."""
        return self.beta0 + self.standardize(x) @ self.beta


def fit_ridge(x: np.ndarray, y: np.ndarray, lam: float) -> RidgeModel:
    """Closed-form minimiser of J with an unpenalised intercept, on rows with no NaN."""
    keep = np.isfinite(x).all(axis=1) & np.isfinite(y)
    x, y = x[keep], y[keep]
    median = np.median(x, axis=0)
    q75, q25 = np.percentile(x, [75, 25], axis=0)
    iqr = np.where(q75 - q25 > 0, q75 - q25, 1.0)
    z = np.clip((x - median) / iqr, -CLIP, CLIP)
    n = len(y)
    z_mean, y_mean = z.mean(axis=0), y.mean()
    zc, yc = z - z_mean, y - y_mean
    beta = np.linalg.solve(zc.T @ zc / n + lam * np.eye(z.shape[1]), zc.T @ yc / n)
    return RidgeModel(lam, median, iqr, float(y_mean - z_mean @ beta), beta)


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation as the Pearson correlation of average ranks."""
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def cross_validate(
    frame: pd.DataFrame,
    lambdas: tuple[float, ...],
    start: pd.Timestamp,
    folds: tuple[tuple[pd.Timestamp, pd.Timestamp], ...],
    purge: int = HORIZON,
) -> pd.DataFrame:
    """Expanding-window folds inside in-sample: out-of-fold MSE and Spearman IC per lambda."""
    rows = []
    x_all = frame[list(FEATURES)].to_numpy(float)
    y_all = frame["y"].to_numpy(float)
    stamps = frame["Datetime"]
    for fold_start, fold_end in folds:
        fit_idx = np.flatnonzero((stamps >= start) & (stamps < fold_start))
        fit_idx = fit_idx[:-purge] if purge else fit_idx
        test = (
            ((stamps >= fold_start) & (stamps <= fold_end)).to_numpy()
            & np.isfinite(x_all).all(axis=1)
            & np.isfinite(y_all)
        )
        for lam in lambdas:
            model = fit_ridge(x_all[fit_idx], y_all[fit_idx], lam)
            predicted = model.score(x_all[test])
            actual = y_all[test]
            rows.append({
                "lam": lam,
                "fold": f"{fold_start:%Y-%m}",
                "mse": float(np.mean((actual - predicted) ** 2)),
                "ic": spearman(predicted, actual),
                "n_fit": len(fit_idx),
                "n_test": int(test.sum()),
            })
    return pd.DataFrame(rows)


def choose_lambda(cv: pd.DataFrame, tolerance: float = 0.01) -> float:
    """Smallest mean out-of-fold MSE; within ``tolerance`` of it, the largest lambda."""
    mean_mse = cv.groupby("lam")["mse"].mean()
    best = mean_mse.min()
    return float(mean_mse[mean_mse <= best * (1.0 + tolerance)].index.max())


def positions(
    close: np.ndarray,
    decision: np.ndarray,
    score: np.ndarray,
    expiry_cut: np.ndarray,
    theta: float,
    min_hold: int = 2,
    max_hold: int = 8,
    stop_points: float = 10.0,
) -> np.ndarray:
    """Momentum position on the minute grid.

    Decisions happen on rows that close a regular 30-minute bar; the stop is
    checked at every minute close and fills there. ``expiry_cut`` marks the row
    that closes the 14:00 bar of an expiry session, where the sleeve goes flat.
    """
    out = np.zeros(len(close))
    current, held, entry = 0, 0, 0.0
    for i in range(len(close)):
        if current and current * (close[i] - entry) <= -stop_points:
            current, held = 0, 0
        if decision[i] and np.isfinite(score[i]):
            if expiry_cut[i]:
                current, held = 0, 0
                out[i] = 0
                continue
            if current:
                held += 1
                reversed_score = (current == 1 and score[i] < 0.0) or (current == -1 and score[i] > 0.0)
                if (held >= min_hold and reversed_score) or held >= max_hold:
                    current, held = 0, 0
            if not current:
                if score[i] >= theta:
                    current, held, entry = 1, 0, close[i]
                elif score[i] <= -theta:
                    current, held, entry = -1, 0, close[i]
        elif expiry_cut[i]:
            current, held = 0, 0
        out[i] = current
    return out

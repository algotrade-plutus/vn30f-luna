#!/usr/bin/env python3
"""Run the steps of research/calibrum-1m/PROTOCOL.md, one stage at a time.

Each stage loads data only up to the last day it is allowed to see:
momentum-cv, momentum-q and basis-grid stop at the end of in-sample;
combos stops at the end of valid. Outputs go to reports/calibrum_1m/.
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

from src.lab.calibrum_1m import momentum, pipeline  # noqa: E402

OUT = WORKSPACE / "reports" / "calibrum_1m"
LAMBDAS = (0.01, 0.1, 1.0, 10.0, 100.0)
FOLDS = tuple(
    (pd.Timestamp(start), pd.Timestamp(end))
    for start, end in (
        ("2021-01-01", "2021-06-30"),
        ("2021-07-01", "2021-12-31"),
        ("2022-01-01", "2022-06-30"),
        ("2022-07-01", "2022-12-31"),
    )
)
QUANTILES = (0.70, 0.80, 0.90)
WINDOWS = (20, 30, 40, 50, 60)
Z_ENTRIES = (1.00, 1.25, 1.50, 1.75, 2.00)


def _save(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=float), encoding="utf-8")


def _model() -> momentum.RidgeModel:
    saved = json.loads((OUT / "momentum_model.json").read_text(encoding="utf-8"))["model"]
    return momentum.RidgeModel(
        lam=saved["lam"],
        median=np.array(saved["median"]),
        iqr=np.array(saved["iqr"]),
        beta0=saved["beta0"],
        beta=np.array(saved["beta"]),
    )


def momentum_cv(config: dict) -> None:
    start, end = pipeline.periods(config)["in_sample"]
    market = pipeline.load_market(end.date())
    frame = momentum.feature_frame(market.futures_30m_adjusted)
    frame = frame[frame["Datetime"] >= start].reset_index(drop=True)
    cv = momentum.cross_validate(frame, LAMBDAS, start, FOLDS)
    lam = momentum.choose_lambda(cv)
    model = momentum.fit_ridge(frame[list(momentum.FEATURES)].to_numpy(float), frame["y"].to_numpy(float), lam)

    chosen = cv[cv["lam"] == lam]
    b1 = int((chosen["ic"] <= 0).sum()) >= 2
    print("Out-of-fold MSE by lambda (rows) and fold (columns):")
    print(cv.pivot(index="lam", columns="fold", values="mse").assign(mean=lambda t: t.mean(axis=1)).round(5).to_string())
    print("\nOut-of-fold Spearman IC:")
    print(cv.pivot(index="lam", columns="fold", values="ic").assign(mean=lambda t: t.mean(axis=1)).round(4).to_string())
    print(f"\nchosen lambda: {lam}")
    print("coefficients:", dict(zip(momentum.FEATURES, np.round(model.beta, 4))), "intercept", round(model.beta0, 4))
    print(f"B1 (IC <= 0 in >= 2 of 4 folds): {'FALSIFIED' if b1 else 'not falsified'}")
    print(f"finding (protocol section 9): x2 {'positive' if model.beta[1] > 0 else 'not positive'}, "
          f"x1 VWAP {'negative' if model.beta[0] < 0 else 'not negative'}")
    _save("momentum_model", {
        "lambda_grid": LAMBDAS,
        "folds": [f"{a:%Y-%m-%d}..{b:%Y-%m-%d}" for a, b in FOLDS],
        "cv": cv.to_dict("records"),
        "fit_rows": int(np.isfinite(frame[list(momentum.FEATURES)].to_numpy(float)).all(axis=1).sum()),
        "falsified": {"B1": b1},
        "findings": {"x2_positive": bool(model.beta[1] > 0), "x1_vwap_negative": bool(model.beta[0] < 0)},
        "model": {
            "lam": lam,
            "features": momentum.FEATURES,
            "median": model.median.tolist(),
            "iqr": model.iqr.tolist(),
            "beta0": model.beta0,
            "beta": model.beta.tolist(),
        },
    })


def momentum_q(config: dict) -> None:
    windows = pipeline.periods(config)
    start, end = windows["in_sample"]
    market = pipeline.load_market(end.date())
    model = _model()
    scores = pipeline.momentum_scores(market, model)
    in_sample = scores[(scores.index >= start) & (scores.index <= end + pd.Timedelta(days=1))].abs().dropna()
    rows = []
    for q in QUANTILES:
        theta = float(in_sample.quantile(q))
        position = pipeline.momentum_positions(market, model, theta)
        metrics = pipeline.score_periods(market, position, {"in_sample": windows["in_sample"]}, config).loc["in_sample"]
        rows.append({"q": q, "theta": theta, **metrics.to_dict()})
    table = pd.DataFrame(rows).set_index("q")
    best = float(table["sharpe"].idxmax())
    print(table[["theta", "net_points", "sharpe", "mdd_points", "margin_bps", "trades", "hit_rate", "cost_points", "exposure"]].round(3).to_string())
    print(f"\nchosen q: {best} (theta {table.loc[best, 'theta']:.4f}); all three positive after cost: {bool((table['net_points'] > 0).all())}")
    _save("momentum_threshold", {"grid": table.reset_index().to_dict("records"), "q": best, "theta": table.loc[best, "theta"]})


def _region_scores(sharpe: pd.DataFrame) -> pd.DataFrame:
    """Mean Sharpe of each cell and its neighbours in a 3 x 3 frame (edge cells use what exists)."""
    values = sharpe.to_numpy()
    out = np.empty_like(values)
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            out[i, j] = values[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2].mean()
    return pd.DataFrame(out, index=sharpe.index, columns=sharpe.columns)


def _reversion_rate(z: pd.Series, z_entry: float, horizon: int = 8) -> tuple[float, int]:
    """Share of |Z| >= z_entry crossings after which |Z| falls below z_entry / 2 within ``horizon`` bars."""
    values = z.to_numpy()
    hits, events = 0, 0
    for i in range(1, len(values)):
        if not np.isfinite(values[i]) or abs(values[i]) < z_entry:
            continue
        if np.isfinite(values[i - 1]) and abs(values[i - 1]) >= z_entry:
            continue
        events += 1
        ahead = values[i + 1:i + 1 + horizon]
        hits += bool((np.abs(ahead[np.isfinite(ahead)]) < z_entry / 2).any())
    return hits / events if events else float("nan"), events


def basis_grid(config: dict) -> None:
    from src.adapters.data.dnse_minute_bars import load_index_minutes
    from src.lab.calibrum_1m import basis

    windows = pipeline.periods(config)
    start, end = windows["in_sample"]
    market = pipeline.load_market(end.date())
    rows = []
    for window in WINDOWS:
        for z_entry in Z_ENTRIES:
            position = pipeline.basis_positions(market, window, z_entry)
            metrics = pipeline.score_periods(market, position, {"in_sample": windows["in_sample"]}, config).loc["in_sample"]
            rows.append({"window": window, "z_entry": z_entry, **metrics.to_dict()})
    table = pd.DataFrame(rows)
    sharpe = table.pivot(index="window", columns="z_entry", values="sharpe")
    region = _region_scores(sharpe)
    window, z_entry = region.stack().idxmax()
    neighbours = table[
        table["window"].isin([w for w in WINDOWS if abs(WINDOWS.index(w) - WINDOWS.index(window)) <= 1])
        & table["z_entry"].isin([z for z in Z_ENTRIES if abs(Z_ENTRIES.index(z) - Z_ENTRIES.index(z_entry)) <= 1])
    ]

    z = basis.zscores(market.futures_30m, market.index_30m, int(window))
    z_in_sample = z[(z.index >= start) & (z.index <= end + pd.Timedelta(days=1))]
    rate, events = _reversion_rate(z_in_sample, float(z_entry))

    position = pipeline.basis_positions(market, int(window), float(z_entry))
    index_minutes = load_index_minutes()
    spot = pd.merge_asof(
        market.minutes[["Datetime"]],
        index_minutes[["Datetime", "Close"]].rename(columns={"Close": "Spot"}),
        on="Datetime",
        direction="backward",
    )["Spot"].to_numpy(float)
    held = np.r_[0.0, position[:-1]]
    in_window = ((market.minutes["Datetime"] >= start) & (market.minutes["Datetime"] < end + pd.Timedelta(days=1))).to_numpy()
    futures_move = held * np.r_[0.0, np.diff(market.close)]
    spot_move = held * np.r_[0.0, np.diff(spot)]
    gross = float(np.nansum(futures_move[in_window]))
    from_spot = float(np.nansum(spot_move[in_window]))

    print("In-sample Sharpe after cost, window (rows) x z_entry (columns):")
    print(sharpe.round(2).to_string())
    print("\n3 x 3 region score:")
    print(region.round(2).to_string())
    print("\nNet points:")
    print(table.pivot(index="window", columns="z_entry", values="net_points").round(0).to_string())
    print(f"\nchosen cell: window {int(window)}, z_entry {float(z_entry)}")
    print(f"neighbours all positive after cost: {bool((neighbours['net_points'] > 0).all())} ({len(neighbours)} cells)")
    print(f"B4 reversion: {rate:.1%} of {events} crossings fall below z_entry/2 within 8 bars -> "
          f"{'FALSIFIED' if rate <= 0.5 else 'not falsified'}")
    print(f"B5 decomposition: gross {gross:.1f} = basis {gross - from_spot:.1f} + index {from_spot:.1f} -> "
          f"{'FALSIFIED' if gross - from_spot <= 0 else 'not falsified'}")
    _save("basis_grid", {
        "grid": table.to_dict("records"),
        "region": {f"{w}|{z_}": float(region.loc[w, z_]) for w in region.index for z_ in region.columns},
        "window": int(window),
        "z_entry": float(z_entry),
        "neighbours_positive": bool((neighbours["net_points"] > 0).all()),
        "B4": {"reversion_rate": rate, "events": events, "falsified": rate <= 0.5},
        "B5": {"gross": gross, "from_basis": gross - from_spot, "from_index": from_spot, "falsified": gross - from_spot <= 0},
    })


STAGES = {"momentum-cv": momentum_cv, "momentum-q": momentum_q, "basis-grid": basis_grid}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=sorted(STAGES))
    args = parser.parse_args()
    STAGES[args.stage](pipeline.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

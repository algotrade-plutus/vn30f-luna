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


BASELINE = {"basis_window": 40, "basis_z_entry": 1.5, "momentum_q": 0.8}
COMBOS = ("C", "B", "M", "C+B", "C+M", "B+M", "C+B+M")


def _daily_net(market: pipeline.Market, position: np.ndarray, config: dict, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    cost = config["costs"]["points_per_contract_per_side"]
    stream = pd.DataFrame({"Datetime": market.minutes["Datetime"], "Close": market.close, "Position": position})
    frame = pipeline.evaluate(stream, pipeline.BacktestConfig(round_trip_fee_points=2 * cost)).frame
    daily = frame.groupby("SessionDate")["NetGain"].sum()
    return daily[(daily.index >= start) & (daily.index <= end)]


def in_sample_baseline(config: dict) -> None:
    """Step 4: the seven combinations on in-sample with the starting parameters (PROTOCOL.md section 9)."""
    windows = pipeline.periods(config)
    start, end = windows["in_sample"]
    market = pipeline.load_market(end.date())
    model = _model()
    scores = pipeline.momentum_scores(market, model)
    in_sample_scores = scores[(scores.index >= start) & (scores.index <= end + pd.Timedelta(days=1))].abs().dropna()
    theta = float(in_sample_scores.quantile(BASELINE["momentum_q"]))
    sleeves = {
        "C": pipeline.calendar_mtw_positions(market),
        "B": pipeline.basis_positions(market, BASELINE["basis_window"], BASELINE["basis_z_entry"]),
        "M": pipeline.momentum_positions(market, model, theta),
    }
    rows, yearly, daily_combos = [], {}, {}
    for combo in COMBOS:
        position = pipeline.vote(*(sleeves[name] for name in combo.split("+")))
        metrics = pipeline.score_periods(market, position, {"in_sample": windows["in_sample"]}, config).loc["in_sample"]
        rows.append({"combo": combo, **metrics.to_dict()})
        daily = _daily_net(market, position, config, start, end)
        daily_combos[combo] = daily
        yearly[combo] = daily.groupby(daily.index.year).sum()
    table = pd.DataFrame(rows).set_index("combo")
    daily_sleeves = pd.DataFrame({name: _daily_net(market, sleeves[name], config, start, end) for name in "CBM"})
    correlation = daily_sleeves.corr()
    print(f"baseline: {BASELINE}, momentum lambda {model.lam}, theta {theta:.4f}")
    print(table[[
        "net_points", "return_pct", "sharpe", "sortino", "information_ratio", "mdd_pct", "longest_drawdown_sessions",
        "margin_bps", "trades", "hit_rate", "exposure", "peak_margin_utilisation_pct",
    ]].round(3).to_string())
    print("\nnet points by year:")
    print(pd.DataFrame(yearly).T.round(1).to_string())
    print("\ndaily net PnL correlation:")
    print(correlation.round(2).to_string())
    _save("in_sample_baseline", {
        "parameters": {**BASELINE, "momentum_lambda": model.lam, "momentum_theta": theta},
        "combos": table.reset_index().to_dict("records"),
        "yearly_net_points": {combo: {str(k): float(v) for k, v in series.items()} for combo, series in yearly.items()},
        "correlation": correlation.round(4).to_dict(),
        "daily_net_points": {
            combo: {str(k.date()): float(v) for k, v in series.items()} for combo, series in daily_combos.items()
        },
    })


def _load(name: str) -> dict:
    return json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))


def _optimised_sleeves(market: pipeline.Market) -> tuple[dict[str, np.ndarray], dict]:
    """The three sleeves with the parameters chosen in step 5 on in-sample."""
    model = _model()
    threshold = _load("momentum_threshold")
    grid = _load("basis_grid")
    params = {
        "momentum_lambda": model.lam,
        "momentum_q": threshold["q"],
        "momentum_theta": threshold["theta"],
        "basis_window": grid["window"],
        "basis_z_entry": grid["z_entry"],
    }
    sleeves = {
        "C": pipeline.calendar_mtw_positions(market),
        "B": pipeline.basis_positions(market, params["basis_window"], params["basis_z_entry"]),
        "M": pipeline.momentum_positions(market, model, params["momentum_theta"]),
    }
    return sleeves, params


def _score_combos(market, sleeves, windows, config) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Metrics of the seven combinations per window, and daily net points over all the windows."""
    first, last = min(w[0] for w in windows.values()), max(w[1] for w in windows.values())
    rows, daily = [], {}
    for combo in COMBOS:
        position = pipeline.vote(*(sleeves[name] for name in combo.split("+")))
        metrics = pipeline.score_periods(market, position, windows, config)
        for period, values in metrics.iterrows():
            rows.append({"combo": combo, "period": period, **values.to_dict()})
        daily[combo] = _daily_net(market, position, config, first, last)
    return pd.DataFrame(rows), daily


def _momentum_ic(market: pipeline.Market, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Spearman IC of the Momentum score with its 2-bar target inside one window."""
    frame = momentum.feature_frame(market.futures_30m_adjusted)
    frame["score"] = _model().score(frame[list(momentum.FEATURES)].to_numpy(float))
    frame = frame[(frame["Datetime"] >= start) & (frame["Datetime"] < end + pd.Timedelta(days=1))]
    frame = frame.dropna(subset=["score", "y"])
    return float(frame["score"].rank().corr(frame["y"].rank()))


def _correlation(daily: dict[str, pd.Series], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    sleeves = pd.DataFrame({name: daily[name] for name in "CBM"})
    sleeves = sleeves[(sleeves.index >= start) & (sleeves.index <= end)]
    return sleeves.corr().round(4).to_dict()


def _print_period(table: pd.DataFrame, period: str) -> None:
    columns = [
        "net_million_vnd", "sharpe", "sortino", "information_ratio", "mdd_pct", "longest_drawdown_sessions",
        "margin_bps", "trades", "hit_rate", "exposure",
    ]
    print(f"\n{period}:")
    print(table[table["period"] == period].set_index("combo")[columns].round(3).to_string())


def valid(config: dict) -> None:
    """Step 6, first look: valid 2023-2024. B2, B6 and the choice of the final combination (section 3.5)."""
    windows = pipeline.periods(config)
    scoring = {name: windows[name] for name in ("in_sample", "valid")}
    market = pipeline.load_market(windows["valid"][1].date())
    sleeves, params = _optimised_sleeves(market)
    table, daily = _score_combos(market, sleeves, scoring, config)

    ic = _momentum_ic(market, *windows["valid"])
    valid_net = table[table["period"] == "valid"].set_index("combo")["net_points"]
    in_sample_sharpe = table[table["period"] == "in_sample"].set_index("combo")["sharpe"]
    falsified = {"B2_momentum_ic": ic <= 0.0}
    for name in "CBM":
        falsified[f"B6_{name}"] = bool(valid_net[name] <= 0.0)
    excluded = {name for name in "CBM" if falsified[f"B6_{name}"]}
    if falsified["B2_momentum_ic"]:
        excluded.add("M")
    candidates = [
        combo for combo in COMBOS
        if valid_net[combo] > 0.0 and not excluded & set(combo.split("+"))
    ]
    # Amended 22/10/2026 after the first look at valid (PROTOCOL.md section 9): the highest Sharpe on valid.
    valid_sharpe = table[table["period"] == "valid"].set_index("combo")["sharpe"]
    selected = max(candidates, key=lambda c: valid_sharpe[c]) if candidates else None
    selected_by_locked_rule = None
    if candidates:
        best = max(in_sample_sharpe[c] for c in candidates)
        close = [c for c in candidates if best - in_sample_sharpe[c] < 0.2]
        selected_by_locked_rule = min(close, key=lambda c: (len(c.split("+")), -in_sample_sharpe[c]))

    for period in scoring:
        _print_period(table, period)
    print(f"\nparameters: {params}")
    print(f"B2 Momentum IC on valid: {ic:.4f} -> {'FALSIFIED' if falsified['B2_momentum_ic'] else 'not falsified'}")
    for name in "CBM":
        print(f"B6 {name} valid net {valid_net[name] * 0.1:+.1f}M VND -> {'FALSIFIED' if falsified[f'B6_{name}'] else 'not falsified'}")
    print(f"excluded sleeves: {sorted(excluded) or 'none'}; candidates: {candidates}")
    print(f"selected final combination (highest valid Sharpe): {selected}; locked rule would give {selected_by_locked_rule}")
    _save("valid", {
        "parameters": params,
        "combos": table.to_dict("records"),
        "momentum_ic_valid": ic,
        "falsified": falsified,
        "excluded_sleeves": sorted(excluded),
        "candidates": candidates,
        "selected": selected,
        "selected_by_locked_rule": selected_by_locked_rule,
        "correlation": {period: _correlation(daily, *windows[period]) for period in scoring},
        "daily_net_points": {c: {str(k.date()): float(v) for k, v in s.items()} for c, s in daily.items()},
    })


def _out_of_sample(config: dict, period: str, requires: str, rerun: bool = False) -> None:
    """Open one out-of-sample window once, after everything it must not influence is saved.

    ``rerun`` recomputes an opened window with the saved choices, for reporting only.
    """
    if not (OUT / f"{requires}.json").exists():
        raise SystemExit(f"run the {requires} stage first")
    if (OUT / f"{period}.json").exists() and not rerun:
        raise SystemExit(f"{period} has already been opened; its report is {OUT / f'{period}.json'}")
    selected = _load("valid")["selected"]
    windows = pipeline.periods(config)
    order = ("in_sample", "valid", "oos1", "oos2")
    scoring = {name: windows[name] for name in order[: order.index(period) + 1]}
    market = pipeline.load_market(windows[period][1].date())
    sleeves, params = _optimised_sleeves(market)
    table, daily = _score_combos(market, sleeves, scoring, config)
    ic = _momentum_ic(market, *windows[period])
    _print_period(table, period)
    print(f"\nselected on valid: {selected}; Momentum IC on {period}: {ic:.4f}")
    print(f"last bar: {market.minutes['Datetime'].max()}")
    _save(period, {
        "parameters": params,
        "selected": selected,
        "combos": table.to_dict("records"),
        "momentum_ic": ic,
        "last_bar": str(market.minutes["Datetime"].max()),
        "correlation": {name: _correlation(daily, *windows[name]) for name in scoring},
        "daily_net_points": {c: {str(k.date()): float(v) for k, v in s.items()} for c, s in daily.items()},
    })


def oos1(config: dict, rerun: bool = False) -> None:
    """Step 6: OOS 1 (2025), opened once after the final combination is chosen and committed."""
    _out_of_sample(config, "oos1", requires="valid", rerun=rerun)


def oos2(config: dict, rerun: bool = False) -> None:
    """Step 6: OOS 2 (2026 to the last bar), opened once after OOS 1."""
    _out_of_sample(config, "oos2", requires="oos1", rerun=rerun)


def benchmarks(config: dict) -> None:
    """Buy-and-hold references for the charts, one contract's worth, in daily points (no selection uses them).

    VN30F1M: pipeline.buy_and_hold_points, the same series the information ratio
    is measured against. VN30: the index move per point, no cost.
    """
    windows = pipeline.periods(config)
    start = windows["in_sample"][0]
    market = pipeline.load_market(pd.Timestamp("2100-01-01").date())
    cost = config["costs"]["points_per_contract_per_side"]

    daily_futures = pipeline.buy_and_hold_points(market, cost, start)
    rolls = market.futures_30m.loc[market.futures_30m["Datetime"] >= start, "Contract"].nunique() - 1
    index = market.index_30m.assign(Session=market.index_30m["Datetime"].dt.normalize())
    index = index[index["Session"] >= start]
    daily_index = index.groupby("Session")["Close"].last().diff().fillna(0.0)

    print(f"VN30F1M buy and hold: {daily_futures.sum() * 0.1:+.1f}M VND, rolls {rolls}")
    print(f"VN30 index buy and hold: {daily_index.sum() * 0.1:+.1f}M VND")
    _save("benchmarks", {
        "note": "one contract's worth, daily points; VN30F1M rolled on the additive adjusted series with costs",
        "daily_net_points": {
            "VN30F1M": {str(k.date()): float(v) for k, v in daily_futures.items()},
            "VN30": {str(k.date()): float(v) for k, v in daily_index.items()},
        },
    })


STAGES = {
    "benchmarks": benchmarks,
    "momentum-cv": momentum_cv,
    "momentum-q": momentum_q,
    "basis-grid": basis_grid,
    "in-sample-baseline": in_sample_baseline,
    "valid": valid,
    "oos1": oos1,
    "oos2": oos2,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=sorted(STAGES))
    parser.add_argument("--rerun", action="store_true", help="recompute an opened OOS stage with the saved choices")
    args = parser.parse_args()
    if args.rerun and args.stage not in ("oos1", "oos2"):
        parser.error("--rerun applies to oos1 and oos2 only")
    options = {"rerun": True} if args.rerun else {}
    STAGES[args.stage](pipeline.load_config(), **options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

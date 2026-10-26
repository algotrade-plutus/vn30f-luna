"""Emit one protocol step's numbers as a plutus-verify results contract.

`plutus check` runs each step of `.plutus/manifest.yaml` in a container and compares these
metrics with the blessed values. The numbers are read from the reports the stages already
saved in `reports/calibrum_1m/`, so the stage code does not depend on plutus-verify.

    python scripts/plutus_results.py data_preparation | optimization | in_sample | out_of_sample | paper_trading
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

import pandas as pd  # noqa: E402
import plutus_verify as pv  # noqa: E402  (staged into the image by `plutus check`)

from src.adapters.data.dnse_minute_bars import load_futures_minutes, load_index_minutes  # noqa: E402
from src.lab.calibrum_1m import pipeline  # noqa: E402

REPORTS = WORKSPACE / "reports" / "calibrum_1m"
COMBOS = ("C", "B", "M", "C+B", "C+M", "B+M", "C+B+M")


def _load(name: str) -> dict:
    return json.loads((REPORTS / f"{name}.json").read_text(encoding="utf-8"))


def _key(combo: str) -> str:
    return combo.lower().replace("+", "_")


def _scores(run: pv.Run, row: dict, prefix: str, full: bool = False) -> None:
    """Return and drawdown on the 100 million VND account; profit in million VND."""
    run.metric(f"{prefix}_sharpe_ratio", float(row["sharpe"]), unit="ratio")
    run.metric(f"{prefix}_net_return", float(row["return_pct"]) / 100.0, unit="fraction")
    run.metric(f"{prefix}_max_drawdown", float(row["mdd_pct"]) / 100.0, unit="fraction")
    if full:
        run.metric(f"{prefix}_net_profit_million_vnd", float(row["net_million_vnd"]), unit="ratio")
        run.metric(f"{prefix}_sortino_ratio", float(row["sortino"]), unit="ratio")
        run.metric(f"{prefix}_information_ratio", float(row["information_ratio"]), unit="ratio")
        run.metric(f"{prefix}_longest_drawdown_sessions", float(row["longest_drawdown_sessions"]), unit="count")
        run.metric(f"{prefix}_trades", float(row["trades"]), unit="count")
        run.metric(f"{prefix}_hit_rate", float(row["hit_rate"]), unit="fraction")


def data_preparation(run: pv.Run) -> None:
    end = pipeline.periods(pipeline.load_config())["oos2"][1] + pd.Timedelta(days=1)
    futures = load_futures_minutes()
    index = load_index_minutes()
    futures = futures[futures["Datetime"] < end]
    index = index[index["Datetime"] < end]
    run.metric("futures_minute_bars", float(len(futures)), unit="count")
    run.metric("index_minute_bars", float(len(index)), unit="count")
    run.metric("futures_sessions", float(futures["Datetime"].dt.normalize().nunique()), unit="count")
    run.metadata(first_bar=str(futures["Datetime"].min()), last_bar=str(futures["Datetime"].max()))


def optimization(run: pv.Run) -> None:
    model = _load("momentum_model")["model"]
    threshold = _load("momentum_threshold")
    basis = _load("basis_grid")
    run.metric("momentum_lambda", float(model["lam"]), unit="ratio")
    run.metric("momentum_q", float(threshold["q"]), unit="fraction")
    run.metric("momentum_theta", float(threshold["theta"]), unit="ratio")
    run.metric("basis_window", float(basis["window"]), unit="count")
    run.metric("basis_z_entry", float(basis["z_entry"]), unit="ratio")
    chosen_q = next(row for row in threshold["grid"] if row["q"] == threshold["q"])
    chosen_cell = next(
        row for row in basis["grid"] if row["window"] == basis["window"] and row["z_entry"] == basis["z_entry"]
    )
    _scores(run, chosen_q, "momentum")
    _scores(run, chosen_cell, "basis")


def in_sample(run: pv.Run) -> None:
    report = _load("in_sample_baseline")
    rows = {row["combo"]: row for row in report["combos"]}
    for combo in COMBOS:
        _scores(run, rows[combo], _key(combo), full=combo == "C+B+M")
    run.metadata(parameters=report["parameters"])


def out_of_sample(run: pv.Run) -> None:
    valid = _load("valid")
    selected = valid["selected"]
    run.metadata(selected=selected, candidates=valid["candidates"])
    for period in ("valid", "oos1", "oos2"):
        rows = _load(period)["combos"]
        row = next(r for r in rows if r["combo"] == selected and r["period"] == period)
        _scores(run, row, period, full=True)


def paper_trading(run: pv.Run) -> None:
    """The Luna bot's paper account, recomputed from its fills by scripts/paper_luna.py."""
    report = json.loads((WORKSPACE / "reports" / "paper" / "luna.json").read_text(encoding="utf-8"))
    for name in ("net_profit_million_vnd", "fees_million_vnd", "sharpe_ratio",
                 "hold_from_bot_start_million_vnd", "hold_from_chart_start_million_vnd"):
        run.metric(name, float(report[name]), unit="ratio")
    for name in ("net_return", "max_drawdown"):
        run.metric(name, float(report[name]), unit="fraction")
    for name in ("fills", "round_trips", "round_trips_won", "final_position"):
        run.metric(name, float(report[name]), unit="count")
    run.metadata(first_fill=report["first_fill"], last_fill=report["last_fill"], chart_start=report["chart_start"])


STEPS = {
    "data_preparation": data_preparation,
    "optimization": optimization,
    "in_sample": in_sample,
    "out_of_sample": out_of_sample,
    "paper_trading": paper_trading,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=list(STEPS))
    args = parser.parse_args()
    with pv.step(args.step) as run:
        STEPS[args.step](run)
    print(f"plutus results written for {args.step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

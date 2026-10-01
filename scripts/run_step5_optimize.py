#!/usr/bin/env python3
"""Step 5: full local sensitivity grid without selecting on best performance."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
import itertools
import json
from pathlib import Path
import statistics
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from scripts.run_step4_insample import build_runner
from src.domain.strategy.luna_strategy import LunaParameters
from src.infrastructure.reproducibility import emit_plutus_results

FROZEN_CONFIG_PATH = WORKSPACE / "config" / "frozen_luna_v0.json"
REPORT_PATH = WORKSPACE / "reports" / "step5_optimization_report.json"


def _parameter_payload(params: LunaParameters) -> dict:
    payload = asdict(params)
    payload["session_end_time"] = params.session_end_time.isoformat()
    return payload


def run_optimization() -> dict:
    runner = build_runner()
    grid = itertools.product(
        (15, 20, 25),
        (40, 50, 60),
        (0.006, 0.008, 0.010),
        (0.009, 0.011, 0.013),
    )
    experiments: list[dict] = []
    baseline_summary: dict | None = None

    print("BƯỚC 5 — 81-POINT LOCAL SENSITIVITY GRID")
    for index, (fast, slow, threshold, fomo) in enumerate(grid, start=1):
        params = LunaParameters(
            t2_fast_bars=fast,
            t2_slow_bars=slow,
            t2_long_thresh=threshold,
            fomo_max_ret_5bar=fomo,
        )
        summary = runner.run(
            date(2021, 1, 15),
            date(2022, 12, 30),
            params,
            sample="in_sample",
        ).summary
        row = {
            "fast": fast,
            "slow": slow,
            "long_threshold": threshold,
            "fomo_return_5bar": fomo,
            "status": summary["status"],
            "return_pct": summary["return_pct"],
            "sharpe": summary["sharpe"],
            "mdd_pct": summary["mdd_pct"],
            "profit_factor": summary["profit_factor_realised_after_linked_fill_charges"],
            "peak_margin_utilisation_pct": summary["peak_margin_utilisation_pct"],
            "margin_calls": summary["margin_calls_90"],
            "exchange_rejects": summary["exchange_rejects"],
            "failures": summary["failures"],
        }
        experiments.append(row)
        if (fast, slow, threshold, fomo) == (20, 50, 0.008, 0.011):
            baseline_summary = summary
        print(
            f"[{index:02d}/81] fast={fast}, slow={slow}, threshold={threshold:.3f}, "
            f"fomo={fomo:.3f}: {summary['status']} Sharpe={summary['sharpe']:.3f}"
        )

    if baseline_summary is None:
        raise AssertionError("Baseline parameters were not present in the sensitivity grid")

    passed = sum(row["status"] == "PASSED" for row in experiments)
    all_neighbours_pass = passed == len(experiments)
    report = {
        "step": 5,
        "strategy": "luna_v0",
        "selection_rule": (
            "The baseline is the pre-existing centre point (20, 50, 0.008, 0.011); "
            "the grid is diagnostic and is not searched for the best result."
        ),
        "stability_rule": "Stable only when all 81 local grid points pass Step 1 criteria.",
        "stable_plateau": all_neighbours_pass,
        "passed_experiments": passed,
        "total_experiments": len(experiments),
        "median_sharpe": statistics.median(row["sharpe"] for row in experiments),
        "min_sharpe": min(row["sharpe"] for row in experiments),
        "max_sharpe": max(row["sharpe"] for row in experiments),
        "experiments": experiments,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    params = LunaParameters()
    frozen = {
        "version": "luna_v0_frozen",
        "frozen_after_step": 5,
        "selection_rule": report["selection_rule"],
        "sensitivity_status": "STABLE" if all_neighbours_pass else "UNSTABLE",
        "parameters": _parameter_payload(params),
        "in_sample_baseline": baseline_summary,
    }
    FROZEN_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    FROZEN_CONFIG_PATH.write_text(
        json.dumps(frozen, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    emit_plutus_results(
        WORKSPACE,
        "optimization",
        {
            "passing_grid_fraction": (passed / len(experiments), "fraction"),
            "median_sharpe_ratio": (report["median_sharpe"], "ratio"),
            "minimum_sharpe_ratio": (report["min_sharpe"], "ratio"),
        },
        artifacts=[
            {"name": "frozen_parameters", "path": "config/frozen_luna_v0.json", "kind": "json"},
            {"name": "sensitivity_report", "path": "reports/step5_optimization_report.json", "kind": "json"},
        ],
        metadata={"grid_points": len(experiments), "selection": "fixed_centre_point"},
    )
    print(
        f"Plateau: {'STABLE' if all_neighbours_pass else 'UNSTABLE'} "
        f"({passed}/{len(experiments)} pass)"
    )
    print(f"Frozen centre-point profile: {FROZEN_CONFIG_PATH}")
    print(f"Report: {REPORT_PATH}")
    return report


if __name__ == "__main__":
    run_optimization()

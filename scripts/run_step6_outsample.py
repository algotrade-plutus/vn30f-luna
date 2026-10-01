#!/usr/bin/env python3
"""Step 6: run the frozen profile once on the untouched OOS window."""
from __future__ import annotations

from dataclasses import fields
from datetime import date, time
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from scripts.run_step4_insample import build_runner
from src.domain.strategy.luna_strategy import LunaParameters
from src.infrastructure.reproducibility import emit_plutus_results

FROZEN_CONFIG_PATH = WORKSPACE / "config" / "frozen_luna_v0.json"
REPORT_PATH = WORKSPACE / "reports" / "step6_outsample_report.json"


def _load_parameters(payload: dict) -> LunaParameters:
    allowed = {field.name for field in fields(LunaParameters)}
    values = {key: value for key, value in payload.items() if key in allowed}
    raw_time = values.get("session_end_time")
    if isinstance(raw_time, str):
        values["session_end_time"] = time.fromisoformat(raw_time)
    return LunaParameters(**values)


def run_outsample_evaluation() -> dict:
    if not FROZEN_CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Missing {FROZEN_CONFIG_PATH}; run scripts/run_step5_optimize.py first"
        )
    frozen = json.loads(FROZEN_CONFIG_PATH.read_text(encoding="utf-8"))
    params = _load_parameters(frozen["parameters"])
    result = build_runner(start=date(2023, 1, 1), end=date(2024, 12, 19)).run(
        date(2023, 1, 1),
        # The frozen export ends on this complete session.  Asking for
        # 2024-12-31 would falsely imply twelve more covered calendar days.
        date(2024, 12, 19),
        params,
        sample="out_of_sample",
    )
    oos = result.summary
    baseline = frozen["in_sample_baseline"]
    baseline_sharpe = float(baseline["sharpe"])
    retention = oos["sharpe"] / baseline_sharpe * 100 if baseline_sharpe else None
    payload = result.to_dict(include_series=True)
    payload.update(
        {
            "step": 6,
            "frozen_profile": frozen["version"],
            "sensitivity_status_at_freeze": frozen["sensitivity_status"],
            "in_sample_baseline": {
                key: baseline[key]
                for key in (
                    "status",
                    "return_pct",
                    "annualized_return_pct",
                    "sharpe",
                    "mdd_pct",
                    "peak_margin_utilisation_pct",
                )
            },
            "sharpe_retention_pct": retention,
        }
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    emit_plutus_results(
        WORKSPACE,
        "out_of_sample",
        {
            "sharpe_ratio": (oos["sharpe"], "ratio"),
            "maximum_drawdown": (oos["mdd_pct"] / 100, "fraction"),
            "total_return": (oos["return_pct"] / 100, "fraction"),
            "margin_calls": (oos["margin_calls_90"], "count"),
            "exchange_rejects": (oos["exchange_rejects"], "count"),
        },
        artifacts=[
            {"name": "out_of_sample_report", "path": "reports/step6_outsample_report.json", "kind": "json"}
        ],
        metadata={"execution_evidence": oos["execution_evidence"]},
    )

    print("BƯỚC 6 — FROZEN OUT-OF-SAMPLE QUA PLUTUS EXCHANGESESSION")
    print(f"Status:              {oos['status']}")
    print(f"Complete sessions:   {oos['complete_sessions']}")
    print(f"Orders / fills:      {oos['orders']} / {oos['fills']}")
    print(f"Net PnL:             {oos['net_pnl']:+,.0f} VND")
    print(f"Return / Sharpe:     {oos['return_pct']:+.2f}% / {oos['sharpe']:.3f}")
    print(f"MDD:                 {oos['mdd_pct']:.3f}%")
    print(f"Sharpe retention:    {retention:.1f}%" if retention is not None else "Sharpe retention: n/a")
    print(f"Execution evidence:  {oos['execution_evidence']}")
    for failure in oos["failures"]:
        print(f"FAIL: {failure}")
    print(f"Report: {REPORT_PATH}")
    return payload


if __name__ == "__main__":
    run_outsample_evaluation()

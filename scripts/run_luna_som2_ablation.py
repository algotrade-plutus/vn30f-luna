#!/usr/bin/env python3
"""Test whether Luna's start-of-month-2 rule adds out-of-sample value."""
from __future__ import annotations

from dataclasses import fields, replace
from datetime import date, time
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from scripts.run_step4_insample import build_runner
from src.domain.strategy.luna_strategy import LunaParameters

FROZEN_CONFIG_PATH = WORKSPACE / "config" / "frozen_luna_v0.json"
REPORT_PATH = WORKSPACE / "reports" / "luna_som2_ablation_report.json"
PERIODS = (
    ("in_sample", date(2021, 1, 15), date(2022, 12, 30)),
    ("out_of_sample", date(2023, 1, 1), date(2024, 12, 19)),
)


def _parameters() -> LunaParameters:
    frozen = json.loads(FROZEN_CONFIG_PATH.read_text(encoding="utf-8"))
    allowed = {field.name for field in fields(LunaParameters)}
    values = {
        key: value for key, value in frozen["parameters"].items() if key in allowed
    }
    if isinstance(values.get("session_end_time"), str):
        values["session_end_time"] = time.fromisoformat(values["session_end_time"])
    return LunaParameters(**values)


def _headline(result: dict) -> dict:
    summary = result["summary"]
    return {
        key: summary[key]
        for key in (
            "status",
            "return_pct",
            "annualized_return_pct",
            "sharpe",
            "mdd_pct",
            "net_pnl",
            "orders",
            "fills",
            "peak_margin_utilisation_pct",
            "margin_calls_90",
            "forced_liquidations_100",
            "failures",
        )
    } | {"indeterminate": result["ignorance"]["indeterminate"]}


def main() -> dict:
    base = _parameters()
    variants = {
        "frozen_baseline": base,
        "som2_disabled": replace(base, use_som2=False),
    }
    report: dict[str, object] = {
        "strategy": "luna_v0",
        "test": "one-variable ablation: use_som2 True -> False; all other frozen parameters unchanged",
        "engine": "plutus.market.session.ExchangeSession",
        "broker_margin_profile": "SSI",
        "periods": {},
    }

    for name, start, end in PERIODS:
        runner = build_runner(start=start, end=end)
        rows: dict[str, dict] = {}
        for variant, params in variants.items():
            result = runner.run(start, end, params, sample=name)
            rows[variant] = _headline(
                {"summary": result.summary, "ignorance": result.ignorance}
            )
            print(
                f"{name} {variant}: Sharpe={rows[variant]['sharpe']:.3f} "
                f"return={rows[variant]['return_pct']:.3f}% "
                f"MDD={rows[variant]['mdd_pct']:.3f}% "
                f"indeterminate={rows[variant]['indeterminate']}"
            )
        baseline = rows["frozen_baseline"]
        ablated = rows["som2_disabled"]
        report["periods"][name] = {
            "baseline": baseline,
            "som2_disabled": ablated,
            "disabled_minus_baseline": {
                key: ablated[key] - baseline[key]
                for key in ("return_pct", "sharpe", "mdd_pct", "net_pnl", "fills")
            },
        }

    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(f"Report: {REPORT_PATH}")
    return report


if __name__ == "__main__":
    main()

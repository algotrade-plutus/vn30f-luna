#!/usr/bin/env python3
"""Step 4: causal in-sample replay through the real Plutus exchange session."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from src.adapters.backtesting import PlutusResearchRunner
from src.adapters.data import PlutusBarSource, PostgresResearchSource
from src.domain.strategy.luna_strategy import LunaParameters
from src.infrastructure.reproducibility import emit_plutus_results

REPORT_PATH = WORKSPACE / "reports" / "step4_insample_report.json"


def build_runner(
    initial_deposit: float = 100_000_000,
    start: date = date(2021, 1, 15),
    end: date = date(2022, 12, 30),
) -> PlutusResearchRunner:
    database = PostgresResearchSource()
    try:
        futures = database.load_front_month_bars(start, end)
        index = database.load_index_bars(start, end)
    finally:
        database.pool.close()
    return PlutusResearchRunner(
        PlutusBarSource(futures, index),
        initial_deposit=Decimal(str(initial_deposit)),
    )


def run_insample_backtest(
    initial_deposit: float = 100_000_000,
    start_date: str = "2021-01-15",
    end_date: str = "2022-12-30",
    params: LunaParameters | None = None,
    *,
    include_evidence: bool = False,
) -> dict:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    result = build_runner(initial_deposit, start, end).run(
        start,
        end,
        params,
        sample="in_sample",
    )
    return result.to_dict(include_series=include_evidence)


def main() -> None:
    result = build_runner(start=date(2021, 1, 15), end=date(2022, 12, 30)).run(
        date(2021, 1, 15), date(2022, 12, 30), sample="in_sample"
    )
    payload = result.to_dict(include_series=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    emit_plutus_results(
        WORKSPACE,
        "in_sample",
        {
            "sharpe_ratio": (result.summary["sharpe"], "ratio"),
            "maximum_drawdown": (result.summary["mdd_pct"] / 100, "fraction"),
            "total_return": (result.summary["return_pct"] / 100, "fraction"),
            "margin_calls": (result.summary["margin_calls_90"], "count"),
            "exchange_rejects": (result.summary["exchange_rejects"], "count"),
        },
        artifacts=[
            {"name": "in_sample_report", "path": "reports/step4_insample_report.json", "kind": "json"}
        ],
        metadata={"execution_evidence": result.summary["execution_evidence"]},
    )

    summary = result.summary
    print("BƯỚC 4 — IN-SAMPLE QUA PLUTUS EXCHANGESESSION")
    print(f"Status:              {summary['status']}")
    print(f"Complete sessions:   {summary['complete_sessions']}")
    print(f"Orders / fills:      {summary['orders']} / {summary['fills']}")
    print(f"Net PnL:             {summary['net_pnl']:+,.0f} VND")
    print(f"Return / Sharpe:     {summary['return_pct']:+.2f}% / {summary['sharpe']:.3f}")
    print(f"MDD:                 {summary['mdd_pct']:.3f}%")
    print(f"Peak margin:         {summary['peak_margin_utilisation_pct']:.3f}%")
    print(f"Plutus charges:      {summary['total_charges']:,.0f} VND")
    print(f"Execution evidence:  {summary['execution_evidence']}")
    for failure in summary["failures"]:
        print(f"FAIL: {failure}")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()

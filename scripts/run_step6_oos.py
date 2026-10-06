#!/usr/bin/env python3
"""Step 6: out-of-sample lab backtest using the local lab engine."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, str(path))

from lab_common import (  # noqa: E402
    add_common_arguments,
    build_base_payload,
    format_metrics,
    format_number,
    load_research_frames,
    parse_window,
    resolve_path,
    run_lab_backtest,
    safe_ratio,
    write_json_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(
        parser,
        default_start="2023-01-01",
        default_end="2024-12-19",
        default_report="reports/step6_oos_lab.json",
    )
    parser.add_argument(
        "--step4-report",
        default="reports/step4_insample_lab.json",
        help="Step 4 lab report used for retention comparison",
    )
    return parser


def load_step4_metrics(path: Path) -> dict | None:
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return None
    return metrics


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    start, end = parse_window(args, parser)

    if args.fee < 0:
        parser.error("--fee must be non-negative")

    try:
        futures, spot, data_meta = load_research_frames(
            args.source,
            start,
            end,
            cache_dir=args.cache_dir,
            allow_fetch=not args.no_fetch,
        )
        result, diagnostics, config = run_lab_backtest(futures, spot, fee=args.fee)
    except Exception as exc:  # noqa: BLE001
        print(f"Step 6 failed: {exc}", file=sys.stderr)
        return 1

    step4_path = resolve_path(args.step4_report)
    step4_metrics = load_step4_metrics(step4_path)
    comparison = {
        "step4_report": str(step4_path),
        "available": step4_metrics is not None,
    }

    if step4_metrics is not None:
        comparison["in_sample_metrics"] = {
            "profit_after_fee": step4_metrics.get("profit_after_fee"),
            "sharpe_after_fee": step4_metrics.get("sharpe_after_fee"),
            "profit_per_year": step4_metrics.get("profit_per_year"),
            "margin_after_fee": step4_metrics.get("margin_after_fee"),
        }
        comparison["retention"] = {
            "profit_after_fee": safe_ratio(
                result.metrics.profit_after_fee,
                step4_metrics.get("profit_after_fee"),
            ),
            "sharpe_after_fee": safe_ratio(
                result.metrics.sharpe_after_fee,
                step4_metrics.get("sharpe_after_fee"),
            ),
            "profit_per_year": safe_ratio(
                result.metrics.profit_per_year,
                step4_metrics.get("profit_per_year"),
            ),
            "margin_after_fee": safe_ratio(
                result.metrics.margin_after_fee,
                step4_metrics.get("margin_after_fee"),
            ),
        }

    payload = build_base_payload(
        report_name="step6_oos_lab",
        sample="out_of_sample",
        start=start,
        end=end,
        source=args.source,
        data_meta=data_meta,
        result=result,
        diagnostics=diagnostics,
        config=config,
        extra={"comparison_with_insample_lab": comparison},
    )
    report_path = write_json_report(args.report, payload)

    print("STEP 6 - OUT-OF-SAMPLE LAB BACKTEST")
    print(f"Data source: {args.source}")
    print(f"Requested window: {start.isoformat()} -> {end.isoformat()}")
    observed = payload["observed_window"]
    print(
        "Observed window:  "
        f"{observed['start']} -> {observed['end']} ({observed['bars']} bars)"
    )
    print(format_metrics(result.metrics))

    if comparison.get("available"):
        retention = comparison.get("retention", {})
        print(
            "Sharpe retention vs Step 4: "
            f"{format_number(retention.get('sharpe_after_fee'), '{:.2%}')}"
        )
        print(
            "Net profit retention vs Step 4: "
            f"{format_number(retention.get('profit_after_fee'), '{:.2%}')}"
        )
        print(
            "Annualized net profit retention vs Step 4: "
            f"{format_number(retention.get('profit_per_year'), '{:.2%}')}"
        )
    else:
        print("Step 4 lab report not found; run scripts/run_step4_insample.py first for retention comparison.")

    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

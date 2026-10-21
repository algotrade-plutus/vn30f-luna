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
    save_lab_plots,
    write_json_report,
)


WINDOWS = {
    "out_of_sample": ("2023-01-01", "2024-12-19"),
    "forward": ("2026-01-01", "2026-10-01"),
}
SHORT = {"out_of_sample": "oos", "forward": "forward"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(
        parser,
        default_start=None,
        default_end=None,
        default_report=None,
    )
    parser.add_argument(
        "--sample",
        choices=tuple(WINDOWS),
        default="out_of_sample",
        help="Window: out_of_sample (2023-01-01 to 2024-12-19) or forward (2026-01-01 to 2026-10-01)",
    )
    parser.add_argument(
        "--ensemble",
        choices=("vote", "sum"),
        default="sum",
        help="sum (official, up to 3 contracts) or vote (reference, 1 contract)",
    )
    parser.add_argument(
        "--step4-report",
        default=None,
        help="Step 4 lab report used for retention comparison; defaults to the same ensemble",
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
    default_start, default_end = WINDOWS[args.sample]
    args.start = args.start or default_start
    args.end = args.end or default_end
    name = f"step6_{SHORT[args.sample]}_lab_{args.ensemble}"
    args.report = args.report or f"reports/{name}.json"
    args.step4_report = args.step4_report or f"reports/step4_insample_lab_{args.ensemble}.json"
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
        result, diagnostics, config = run_lab_backtest(
            futures, spot, fee=args.fee, ensemble_mode=args.ensemble
        )
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
        report_name=name,
        sample=args.sample,
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
    figure_paths = save_lab_plots(
        result, f"reports/figures/{name}", title=f"Step 6: {args.sample} lab backtest ({args.ensemble})"
    )

    print(f"STEP 6 - {args.sample.upper()} LAB BACKTEST")
    print(f"Data source: {args.source}")
    print(f"Ensemble: {args.ensemble}")
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
    for figure_path in figure_paths:
        print(f"Figure: {figure_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Step 4: in-sample lab backtest using the local lab engine."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from lab_common import (  # noqa: E402
    add_common_arguments,
    build_base_payload,
    format_metrics,
    load_research_frames,
    parse_window,
    run_lab_backtest,
    write_json_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(
        parser,
        default_start="2021-01-15",
        default_end="2022-12-30",
        default_report="reports/step4_insample_lab.json",
    )
    return parser


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
        print(f"Step 4 failed: {exc}", file=sys.stderr)
        return 1

    payload = build_base_payload(
        report_name="step4_insample_lab",
        sample="in_sample",
        start=start,
        end=end,
        source=args.source,
        data_meta=data_meta,
        result=result,
        diagnostics=diagnostics,
        config=config,
    )
    report_path = write_json_report(args.report, payload)

    print("STEP 4 - IN-SAMPLE LAB BACKTEST")
    print(f"Data source: {args.source}")
    print(f"Requested window: {start.isoformat()} -> {end.isoformat()}")
    print(format_metrics(result.metrics))
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

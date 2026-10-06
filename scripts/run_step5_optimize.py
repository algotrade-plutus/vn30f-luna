#!/usr/bin/env python3
"""Step 5: parameter sensitivity sweep for the local lab engine."""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, str(path))

from lab_common import (  # noqa: E402
    DEFAULT_FEE,
    add_common_arguments,
    build_base_payload,
    format_number,
    json_safe,
    load_research_frames,
    parse_window,
    run_lab_backtest,
    selected_metrics,
    summarize_values,
    write_json_report,
)

DEFAULT_RIDGE_THRESHOLDS = [0.16, 0.18, 0.20]
DEFAULT_SHINJI_Z_ENTRIES = [1.3, 1.5, 1.7]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(
        parser,
        default_start="2021-01-15",
        default_end="2022-12-30",
        default_report="reports/step5_optimize_lab.json",
    )
    parser.add_argument(
        "--ridge-thresholds",
        default=",".join(str(v) for v in DEFAULT_RIDGE_THRESHOLDS),
        help="Comma-separated ridge_entry_threshold values",
    )
    parser.add_argument(
        "--shinji-z-entries",
        default=",".join(str(v) for v in DEFAULT_SHINJI_Z_ENTRIES),
        help="Comma-separated shinji_z_entry values",
    )
    return parser


def parse_float_list(parser: argparse.ArgumentParser, option: str, value: str) -> list[float]:
    try:
        values = [float(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        parser.error(f"{option} must be comma-separated numbers: {exc}")
        return []

    if not values:
        parser.error(f"{option} must contain at least one value")
    return values


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    start, end = parse_window(args, parser)

    if args.fee < 0:
        parser.error("--fee must be non-negative")

    ridge_thresholds = parse_float_list(parser, "--ridge-thresholds", args.ridge_thresholds)
    shinji_z_entries = parse_float_list(parser, "--shinji-z-entries", args.shinji_z_entries)

    try:
        futures, spot, data_meta = load_research_frames(
            args.source,
            start,
            end,
            cache_dir=args.cache_dir,
            allow_fetch=not args.no_fetch,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Step 5 failed while loading data: {exc}", file=sys.stderr)
        return 1

    results = []
    baseline_row = None

    for ridge_threshold, shinji_z_entry in itertools.product(ridge_thresholds, shinji_z_entries):
        overrides = {
            "ridge_entry_threshold": ridge_threshold,
            "shinji_z_entry": shinji_z_entry,
        }
        is_baseline = abs(ridge_threshold - 0.18) <= 1e-12 and abs(shinji_z_entry - 1.5) <= 1e-12
        row = {
            "parameters": overrides,
            "baseline": is_baseline,
            "status": "ok",
        }
        try:
            result, diagnostics, _ = run_lab_backtest(
                futures,
                spot,
                fee=args.fee,
                parameter_overrides=overrides,
            )
            row["metrics"] = selected_metrics(result.metrics)
            row["diagnostics"] = {
                "source_mode": diagnostics.get("source_mode"),
                "raw_contract_roll_count": diagnostics.get("raw_contract_roll_count"),
                "parameter_overrides": diagnostics.get("parameter_overrides"),
            }
            if is_baseline:
                baseline_row = row
        except Exception as exc:  # noqa: BLE001
            row["status"] = "error"
            row["error"] = str(exc)

        results.append(row)

    ok_rows = [row for row in results if row["status"] == "ok"]
    stability = {
        "runs_total": len(results),
        "runs_ok": len(ok_rows),
        "runs_failed": len(results) - len(ok_rows),
    }
    for key in (
        "profit_after_fee",
        "sharpe_after_fee",
        "margin_after_fee",
        "mdd_points",
        "mdd_percent",
        "hit_rate",
    ):
        stability[key] = summarize_values(row["metrics"].get(key) for row in ok_rows if "metrics" in row)

    payload = {
        "report": "step5_optimize_lab",
        "engine": "src.lab.backtest",
        "sample": "in_sample",
        "requested_window": {"start": start, "end": end},
        "data": data_meta,
        "fee_convention": {
            "round_trip_fee_points": args.fee,
            "fee_per_position_unit": args.fee / 2.0,
            "note": "A 0.8-point round-trip fee is charged as 0.4 point per position change.",
        },
        "grid": {
            "ridge_entry_threshold": ridge_thresholds,
            "shinji_z_entry": shinji_z_entries,
        },
        "baseline": baseline_row,
        "results": results,
        "stability": stability,
        "note": (
            "Sensitivity analysis on the frozen Calibrum package. No parameters are "
            "automatically selected or refitted."
        ),
        "caveats": [
            "Headline README metrics remain Native SDK/evangelion verification numbers from "
            "PS_V30_Vien_Calibrum/native_verification.json.",
            "Lab engine uses local point-based accounting; it is not the Plutus VND execution simulation.",
            "DNSE data is a public continuous front-month candle cache; it is not native-parity adjusted contract data."
            if args.source == "dnse"
            else "PostgreSQL data is raw front-month data from algotradeDB; it is not native-parity adjusted contract data.",
        ],
    }
    report_path = write_json_report(args.report, payload)

    print("STEP 5 - SENSITIVITY LAB BACKTEST")
    print(f"Data source: {args.source}")
    print(f"Requested window: {start.isoformat()} -> {end.isoformat()}")
    print(f"Grid: ridge_entry_threshold={ridge_thresholds}, shinji_z_entry={shinji_z_entries}")

    for row in results:
        params = row["parameters"]
        label = f"ridge={params['ridge_entry_threshold']:.2f} z={params['shinji_z_entry']:.2f}"
        if row["baseline"]:
            label += " (baseline)"
        if row["status"] != "ok":
            print(f"{label}: ERROR {row.get('error')}")
            continue

        metrics = row["metrics"]
        print(
            f"{label}: profit={format_number(metrics.get('profit_after_fee'))} "
            f"sharpe={format_number(metrics.get('sharpe_after_fee'))} "
            f"margin={format_number(metrics.get('margin_after_fee'))} "
            f"mdd={format_number(metrics.get('mdd_points'), '{:.1f}')}"
        )

    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

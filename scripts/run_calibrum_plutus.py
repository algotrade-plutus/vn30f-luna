#!/usr/bin/env python3
"""Run the frozen Calibrum signal through DB bars and the Plutus exchange."""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from src.adapters.backtesting import PlutusResearchRunner
from src.adapters.data import PlutusBarSource, PostgresResearchSource
from src.adapters.strategies.calibrum_signal_source import generate_calibrum_targets


PACKAGE_DIR = WORKSPACE / "PS_V30_Vien_Calibrum"
REPORT_PATH = WORKSPACE / "reports" / "calibrum_raw_roll_insample_plutus.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2021-06-01")
    parser.add_argument("--end", default="2022-12-30")
    parser.add_argument(
        "--sample",
        choices=("in_sample", "out_of_sample", "forward"),
        default="in_sample",
        help="Research window label; OOS and forward use the holdout threshold",
    )
    parser.add_argument("--capital", type=int, default=100_000_000)
    parser.add_argument("--contracts", type=int, default=1)
    parser.add_argument(
        "--disable-shinji",
        action="store_true",
        help="Ablation: remove Shinji's contribution without retraining weights",
    )
    parser.add_argument(
        "--shinji-basis-price",
        choices=("raw", "roll_adjusted"),
        default="raw",
        help="Futures price supplied to the Shinji basis sleeve",
    )
    parser.add_argument(
        "--shinji-roll-guard",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Flat Shinji on expiry and reset its 40-bar history after each roll",
    )
    parser.add_argument(
        "--ridge-roll-guard",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Flat Ridge on expiry and reset ATR/state after each roll",
    )
    parser.add_argument(
        "--expiry-flat",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Flat the ensemble from the 14:00 bar of each expiry session",
    )
    parser.add_argument(
        "--ensemble-mode",
        choices=("vote", "sum"),
        default="vote",
        help="Ensemble rule: 'vote' (majority vote 1 contract) or 'sum' (3 independent contracts)",
    )
    parser.add_argument(
        "--report",
        default=str(REPORT_PATH.relative_to(WORKSPACE)),
        help="Report path, relative to the workspace unless absolute",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if args.contracts < 1:
        raise ValueError("--contracts must be positive")
    if args.capital <= 0:
        raise ValueError("--capital must be positive")
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = WORKSPACE / report_path

    database = PostgresResearchSource()
    try:
        futures = database.load_front_month_bars(start, end)
        spot = database.load_index_bars(start, end)
    finally:
        database.pool.close()
    multiplier = args.contracts * (3 if args.ensemble_mode == "sum" else 1)
    targets = generate_calibrum_targets(
        futures,
        spot,
        PACKAGE_DIR,
        quantity=args.contracts,
        ensemble_mode=args.ensemble_mode,
        use_shinji=not args.disable_shinji,
        shinji_basis_price=args.shinji_basis_price,
        shinji_roll_guard=args.shinji_roll_guard,
        ridge_roll_guard=args.ridge_roll_guard,
        expiry_flat=args.expiry_flat,
    )
    runner = PlutusResearchRunner(
        PlutusBarSource(futures, spot),
        initial_deposit=Decimal(str(args.capital)),
        target_multiplier=multiplier,
        execution_model="soft",
    )
    sig_name = (
        "calibrum_raw_roll_sum3"
        if args.ensemble_mode == "sum"
        else ("calibrum_raw_roll_no_shinji" if args.disable_shinji else "calibrum_raw_roll")
    )
    result = runner.run(
        start,
        end,
        sample=args.sample,
        target_by_start=targets.targets,
        signal_name=sig_name,
    )
    payload = result.to_dict(include_series=True)
    payload["calibrum_replay"] = targets.diagnostics
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    summary = result.summary
    print("CALIBRUM — DB + PLUTUS REPLAY")
    print(f"Status:              {summary['status']}")
    print(f"Sample:              {summary['sample']}")
    print(f"Complete sessions:   {summary['complete_sessions']}")
    print(f"Orders / fills:      {summary['orders']} / {summary['fills']}")
    print(f"Net PnL:             {summary['net_pnl']:+,.0f} VND")
    print(f"Return / Sharpe:     {summary['return_pct']:+.2f}% / {summary['sharpe']:.3f}")
    print(f"MDD:                 {summary['mdd_pct']:.3f}%")
    print(f"Raw contract rolls:  {targets.diagnostics['raw_contract_roll_count']}")
    print(f"Shinji contribution: {'enabled' if not args.disable_shinji else 'disabled'}")
    print(f"Shinji basis price:  {args.shinji_basis_price}")
    print(f"Shinji roll guard:   {'enabled' if args.shinji_roll_guard else 'disabled'}")
    print(f"Ridge roll guard:    {'enabled' if args.ridge_roll_guard else 'disabled'}")
    print(f"Expiry flat:         {'enabled' if args.expiry_flat else 'disabled'}")
    print("Parity caveat:       no — DB series is not verified platform adjusted data")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()

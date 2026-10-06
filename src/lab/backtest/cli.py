"""Run backtest evaluation locally from a position parquet."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import BacktestConfig
from .evaluator import evaluate
from .reporting import format_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("positions", type=Path)
    parser.add_argument("--round-trip-fee", type=float, default=0.8)
    parser.add_argument("--plot", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--allow-fractional", action="store_true")
    args = parser.parse_args()
    result = evaluate(
        pd.read_parquet(args.positions),
        BacktestConfig(
            round_trip_fee_points=args.round_trip_fee,
            require_discrete_position=not args.allow_fractional,
        ),
    )
    print(format_metrics(result.metrics))
    if args.plot:
        args.plot.parent.mkdir(parents=True, exist_ok=True)
        result.plot_pnl().savefig(args.plot, dpi=160, bbox_inches="tight")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = result.metrics.as_dict()
        payload["mdd_peak"] = str(payload["mdd_peak"])
        payload["mdd_trough"] = str(payload["mdd_trough"])
        args.json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()

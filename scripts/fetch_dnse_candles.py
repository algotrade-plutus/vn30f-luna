#!/usr/bin/env python3
"""Fetch and cache DNSE candles for local lab backtests."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from src.adapters.data.dnse_candle_source import (  # noqa: E402
    DnseDataError,
    cache_path,
    load_or_fetch_dnse_bars,
)

SERIES = (
    ("derivative", "VN30F1M"),
    ("index", "VN30"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2021-01-01", help="Start date, inclusive, YYYY-MM-DD")
    parser.add_argument("--end", default="2024-12-31", help="End date, inclusive, YYYY-MM-DD")
    parser.add_argument("--resolution", type=int, default=30, help="Bar resolution in minutes")
    parser.add_argument("--cache-dir", default=None, help="Cache directory, default data/dnse")
    parser.add_argument("--force", action="store_true", help="Refetch requested range even if cache appears to cover it")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as exc:
        print(f"Invalid date: {exc}", file=sys.stderr)
        return 2

    if start > end:
        print("--start must not be after --end", file=sys.stderr)
        return 2

    status = 0
    for market, symbol in SERIES:
        path = cache_path(market, symbol, args.resolution, args.cache_dir)
        try:
            bars, meta = load_or_fetch_dnse_bars(
                market,
                symbol,
                start,
                end,
                resolution=args.resolution,
                cache_dir=args.cache_dir,
                force_refresh=args.force,
                allow_fetch=True,
            )
        except DnseDataError as exc:
            print(f"ERROR {market}/{symbol}: {exc}", file=sys.stderr)
            status = 1
            continue

        print(f"{market}/{symbol}")
        print(f"  cache: {path}")
        print(f"  rows: {len(bars):,}")
        print(f"  range: {meta['observed_start']} -> {meta['observed_end']}")
        print(f"  fetched_now: {meta['fetched']}")

    return status


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only Kafka market-data smoke test."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from paperbroker.market_data import KafkaMarketDataClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


async def run(seconds: int, offset: str) -> int:
    instrument = os.environ["VN30F1M"]
    count = 0
    latest = None

    # KafkaMarketDataClient invokes callbacks synchronously from its consumer
    # thread. An async callback silently returns an un-awaited coroutine.
    def on_quote(symbol, quote):
        nonlocal count, latest
        count += 1
        latest = quote.latest_matched_price

    client = KafkaMarketDataClient(
        bootstrap_servers=os.environ["PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS"],
        username=os.environ["PAPERBROKER_KAFKA_USERNAME"],
        password=os.environ["PAPERBROKER_KAFKA_PASSWORD"],
        env_id=os.environ["PAPERBROKER_ENV_ID"],
        auto_offset_reset=offset,
        merge_updates=True,
    )
    try:
        await client.subscribe(instrument, on_quote)
        await client.start()
        await asyncio.sleep(seconds)
    finally:
        await client.stop()
    print(f"instrument={instrument} offset={offset} updates={count} latest={latest}")
    return 0 if count > 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--offset", choices=("earliest", "latest"), default="earliest")
    args = parser.parse_args()
    return asyncio.run(run(args.seconds, args.offset))


if __name__ == "__main__":
    raise SystemExit(main())

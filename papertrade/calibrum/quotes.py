"""Best bid/ask of the traded contract from PaperTrade's Kafka feed, only to price orders.

Signals never read this feed (they come from DNSE). The SDK consumes Kafka on
its own thread and calls back synchronously (REBUILD_NOTES #10); the latest
merged snapshot is read with ``query``.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from .execution import Quote


class KafkaQuotes:
    def __init__(self) -> None:
        from paperbroker.market_data import KafkaMarketDataClient

        self.client = KafkaMarketDataClient(
            bootstrap_servers=os.environ["PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS"],
            username=os.environ["PAPERBROKER_KAFKA_USERNAME"],
            password=os.environ["PAPERBROKER_KAFKA_PASSWORD"],
            env_id=os.environ["PAPERBROKER_ENV_ID"],
            auto_offset_reset="latest",
            merge_updates=True,
        )
        self.symbols: set[str] = set()
        self.received: dict[str, float] = {}
        self.started = False

    def _on_quote(self, instrument: str, quote: Any) -> None:
        self.received[instrument] = time.time()

    def follow(self, symbol: str) -> None:
        """Subscribe to ``symbol`` (once) and start the consumer on first use."""
        if symbol in self.symbols:
            return
        asyncio.run(self.client.subscribe(symbol, self._on_quote))
        self.symbols.add(symbol)
        if not self.started:
            asyncio.run(self.client.start())
            self.started = True

    def quote(self, symbol: str, max_age_s: float = 30.0) -> Quote | None:
        snapshot = self.client.query(symbol)
        if snapshot is None or time.time() - self.received.get(symbol, 0.0) > max_age_s:
            return None
        bid, ask = snapshot.bid_price_1, snapshot.ask_price_1
        ceiling, floor = snapshot.ceiling_price, snapshot.floor_price
        if not all(value for value in (bid, ask, ceiling, floor)):
            return None
        return Quote(bid=float(bid), ask=float(ask), ceiling=float(ceiling), floor=float(floor))

    def age_seconds(self, symbol: str) -> float | None:
        stamp = self.received.get(symbol)
        return None if stamp is None else time.time() - stamp

    def stop(self) -> None:
        if self.started:
            asyncio.run(self.client.stop())

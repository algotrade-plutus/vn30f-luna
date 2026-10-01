"""Domain entity: Tick and Order Book Snapshot.
Pure Python standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class MatchedTick:
    """A single matched trade tick from the market."""
    symbol: str
    timestamp: datetime
    price: Decimal
    volume: int
    match_type: str = ""  # e.g., "M" (continuous), "O" (open ATO), "C" (close ATC)


@dataclass(frozen=True)
class OrderBookLevel:
    """One depth level in the bid or ask ladder."""
    price: Decimal
    quantity: int


@dataclass(frozen=True)
class OrderBookSnapshot:
    """Top-of-book or multi-depth order book snapshot."""
    symbol: str
    timestamp: datetime
    bids: tuple[OrderBookLevel, ...]  # Best bid at index 0
    asks: tuple[OrderBookLevel, ...]  # Best ask at index 0

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Decimal | None:
        bb = self.best_bid
        ba = self.best_ask
        if bb is not None and ba is not None:
            return (bb + ba) / Decimal(2)
        return bb or ba

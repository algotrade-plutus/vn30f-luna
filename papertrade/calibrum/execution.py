"""From the vote to one broker order at a time (papertrade/docs/REBUILD_NOTES.md sections 4, 5 and 9).

``plan`` is pure: it reads the broker's view of the account, the quote and the
clock, and returns at most one order. Rules, in order:

1. Any working order: wait (the runner cancels a stale one).
2. Outside an order window: wait. Windows are continuous trading
   (09:00-11:30, 13:00-14:30) and the closing auction until 14:44:30.
3. Equity below the margin held (``remain_cash`` < 0): sell or buy back just
   enough contracts to cover it, keeping the side.
4. Holding the other side of the vote, or holding while the vote is flat:
   close the whole position. A reversal opens only after REST shows flat.
5. Flat and the vote is not: open min(qty, what the broker lets us place).
   A held position is never topped up, so size is set at entry.

Prices: in continuous trading a LIMIT a few ticks through the book (BUY at
ask + cross, SELL at bid - cross), held inside the band; in the closing
auction the band edge (BUY at ceiling, SELL at floor), which fills at the
auction price.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

import pandas as pd

from src.domain.strategy.calendar_rules import is_trading_day

POINT_VND = 100_000
TICK = Decimal("0.1")
CONTINUOUS = ((time(9, 0), time(11, 30)), (time(13, 0), time(14, 30)))
AUCTION = (time(14, 30), time(14, 44, 30))


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    ceiling: float
    floor: float


@dataclass(frozen=True)
class Account:
    position: int  # signed contracts in the managed symbol, from REST
    remain_cash: float  # VND: equity minus margin held, from REST
    working_orders: int


@dataclass(frozen=True)
class Order:
    side: str  # "BUY" or "SELL"
    qty: int
    price: float
    reason: str  # "margin", "close" or "open"


def phase(now: pd.Timestamp) -> str:
    """'continuous', 'auction' or 'closed'."""
    if not is_trading_day(now.date()):
        return "closed"
    clock = now.time()
    if any(start <= clock < end for start, end in CONTINUOUS):
        return "continuous"
    if AUCTION[0] <= clock < AUCTION[1]:
        return "auction"
    return "closed"


def tick(price: float) -> float:
    return float(Decimal(str(price)).quantize(TICK, rounding=ROUND_HALF_UP))


def order_price(side: str, quote: Quote, window: str, cross: float) -> float:
    if window == "auction":
        return tick(quote.ceiling if side == "BUY" else quote.floor)
    if side == "BUY":
        return tick(min(quote.ask + cross, quote.ceiling))
    return tick(max(quote.bid - cross, quote.floor))


def margin_per_contract(price: float, ratio: float) -> float:
    return price * POINT_VND * ratio


def plan(
    vote: int,
    qty: int,
    account: Account,
    quote: Quote | None,
    now: pd.Timestamp,
    max_placeable: Callable[[str, float], int],
    margin_ratio: float = 0.25,
    cross: float = 0.3,
) -> Order | None:
    if account.working_orders:
        return None
    window = phase(now)
    if window == "closed" or quote is None:
        return None
    position = account.position

    if position and account.remain_cash < 0:
        side = "SELL" if position > 0 else "BUY"
        reference = (quote.bid + quote.ask) / 2
        cut = min(abs(position), math.ceil(-account.remain_cash / margin_per_contract(reference, margin_ratio)))
        return Order(side, cut, order_price(side, quote, window, cross), "margin")

    if position and (vote == 0 or (vote > 0) != (position > 0)):
        side = "SELL" if position > 0 else "BUY"
        return Order(side, abs(position), order_price(side, quote, window, cross), "close")

    if not position and vote:
        side = "BUY" if vote > 0 else "SELL"
        price = order_price(side, quote, window, cross)
        size = min(qty, max(0, int(max_placeable(side, price))))
        return Order(side, size, price, "open") if size else None
    return None

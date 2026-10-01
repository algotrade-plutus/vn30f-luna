"""Reconstruct three-level VN30F books from PostgreSQL change streams.

The four ``quote.*`` depth tables are per-level change streams, not atomic
snapshots. Each level is joined independently as-of the requested instant and
forward fill is deliberately bounded to one calendar day.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from plutus.core.order import Side
from plutus.market.adapters.depth import (
    DepthBook,
    DepthLevel,
    DepthSide,
    SideAvailability,
    Truncation,
)
from plutus.market.protocol import Resolution
from plutus.market.session import DataField

from src.infrastructure.database.postgres_pool import PostgresConnectionPool


_MAX_DEPTH = 3
_WITHHELD = frozenset(
    {
        DataField.LAST,
        DataField.OPEN,
        DataField.HIGH,
        DataField.LOW,
        DataField.CLOSE,
        DataField.VOLUME,
        DataField.REFERENCE,
        DataField.CEILING,
        DataField.FLOOR,
        DataField.SESSION_PHASE,
        DataField.FOREIGN_ROOM,
        DataField.SETTLEMENT_PRICE,
    }
)


@dataclass
class _Stream:
    stamps: dict[int, list[datetime]] = field(
        default_factory=lambda: {depth: [] for depth in range(1, _MAX_DEPTH + 1)}
    )
    values: dict[int, list[Any]] = field(
        default_factory=lambda: {depth: [] for depth in range(1, _MAX_DEPTH + 1)}
    )

    def append(self, stamp: datetime, depth: int, value: Any) -> None:
        if 1 <= depth <= _MAX_DEPTH:
            self.stamps[depth].append(stamp)
            self.values[depth].append(value)

    def at(self, depth: int, stamp: datetime) -> tuple[Any, datetime] | None:
        times = self.stamps[depth]
        index = bisect_right(times, stamp) - 1
        if index < 0:
            return None
        return self.values[depth][index], times[index]


@dataclass
class _DayTape:
    bid_price: _Stream = field(default_factory=_Stream)
    ask_price: _Stream = field(default_factory=_Stream)
    bid_size: _Stream = field(default_factory=_Stream)
    ask_size: _Stream = field(default_factory=_Stream)


class PostgresDepthSource:
    """Plutus ``BookProvider`` backed by bounded read-only database queries."""

    SERVES_RESOLUTIONS = frozenset({Resolution.TICK})
    table_prefix = "quote"

    def __init__(self, pool: PostgresConnectionPool | None = None) -> None:
        self.pool = pool or PostgresConnectionPool()
        self._owns_pool = pool is None
        self._cache: dict[tuple[str, date], _DayTape] = {}
        self._book_requests = 0
        self._loaded_days = 0
        self._query_count = 0

    @property
    def diagnostics(self) -> dict[str, int]:
        return {
            "book_requests": self._book_requests,
            "loaded_ticker_days": self._loaded_days,
            "postgres_queries": self._query_count,
            "cached_ticker_days": len(self._cache),
        }

    def close(self) -> None:
        if self._owns_pool:
            self.pool.close()

    def _load_stream(
        self,
        ticker: str,
        day: date,
        table: str,
        value_column: str,
    ) -> _Stream:
        start = datetime.combine(day, time.min)
        end = datetime.combine(day, time.max)
        # Table and column names are constants selected by this class, never
        # user input. Values remain parameterized and carry both index bounds.
        sql = f"""
            SELECT datetime, depth, {value_column}
            FROM quote.{table}
            WHERE datetime >= %s AND datetime <= %s
              AND tickersymbol = %s
              AND depth >= 1 AND depth <= 3
            ORDER BY datetime ASC, depth ASC
        """
        rows = self.pool.execute_query(sql, (start, end, ticker))
        self._query_count += 1
        stream = _Stream()
        for stamp, depth, value in rows:
            normalized = (
                Decimal(str(value)) if value_column == "price" else int(value)
            )
            stream.append(stamp, int(depth), normalized)
        return stream

    def _tape(self, ticker: str, day: date) -> _DayTape:
        key = (ticker, day)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        tape = _DayTape(
            bid_price=self._load_stream(ticker, day, "bidprice", "price"),
            ask_price=self._load_stream(ticker, day, "askprice", "price"),
            bid_size=self._load_stream(ticker, day, "bidsize", "quantity"),
            ask_size=self._load_stream(ticker, day, "asksize", "quantity"),
        )
        self._cache[key] = tape
        self._loaded_days += 1
        if self._loaded_days % 25 == 0:
            print(
                f"Order-book cache: {self._loaded_days} ticker-days "
                f"({self._query_count} bounded queries)",
                flush=True,
            )
        return tape

    @staticmethod
    def _side(
        tape: _DayTape,
        side: Side,
        stamp: datetime,
        max_age: timedelta | None,
    ) -> DepthSide:
        price = tape.bid_price if side is Side.BUY else tape.ask_price
        size = tape.bid_size if side is Side.BUY else tape.ask_size
        observed = tuple(
            depth
            for depth in range(1, _MAX_DEPTH + 1)
            if price.at(depth, stamp) is not None
        )
        levels: list[DepthLevel] = []
        truncated_at: int | None = None
        aged_out = False
        for depth in range(1, _MAX_DEPTH + 1):
            priced = price.at(depth, stamp)
            if priced is None:
                truncated_at = depth
                break
            price_value, price_as_of = priced
            sized = size.at(depth, stamp)
            level = DepthLevel(
                depth=depth,
                price=price_value,
                size=None if sized is None else sized[0],
                price_as_of=price_as_of,
                size_as_of=None if sized is None else sized[1],
                ts=stamp,
            )
            if max_age is not None and level.age > max_age:
                truncated_at = depth
                aged_out = True
                break
            levels.append(level)

        if truncated_at is None:
            truncation = Truncation.NONE
        elif aged_out:
            truncation = Truncation.MAX_AGE
        elif any(depth > truncated_at for depth in observed):
            truncation = Truncation.LADDER_GAP
        else:
            truncation = Truncation.NO_OBSERVATION
        availability = (
            SideAvailability.OBSERVED if levels else SideAvailability.ABSENT
        )
        return DepthSide(
            side=side,
            availability=availability,
            levels=tuple(levels),
            truncation=truncation,
            truncated_at_depth=truncated_at,
            observed_depths=observed,
            ts=stamp,
        )

    def book_at(
        self,
        ticker: str,
        ts: datetime,
        *,
        max_age: timedelta | None = None,
    ) -> DepthBook:
        if max_age is not None and max_age < timedelta(0):
            raise ValueError("max_age must be non-negative")
        self._book_requests += 1
        tape = self._tape(ticker, ts.date())
        bid = self._side(tape, Side.BUY, ts, max_age)
        ask = self._side(tape, Side.SELL, ts, max_age)
        withheld = set(_WITHHELD)
        if (
            bid.availability is not SideAvailability.OBSERVED
            and ask.availability is not SideAvailability.OBSERVED
        ):
            withheld.add(DataField.BOOK)
        observed_sides = [
            side
            for side in (bid, ask)
            if side.availability is SideAvailability.OBSERVED
        ]
        if not observed_sides or not all(side.has_sizes for side in observed_sides):
            withheld.add(DataField.BOOK_SIZE)
        return DepthBook(
            ticker=ticker,
            ts=ts,
            bid=bid,
            ask=ask,
            resolution=Resolution.TICK,
            withheld=frozenset(withheld),
            table_prefix=self.table_prefix,
        )

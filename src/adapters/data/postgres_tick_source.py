"""Adapters Data: PostgreSQL Tick and Bar Source.
Connects to algotradeDB and queries quote.matched and quote.close with indexed queries.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
import logging
from typing import Any

from src.application.ports.market_data_port import IMarketDataGateway
from src.domain.entities.bar import Bar
from src.domain.entities.tick import MatchedTick
from src.infrastructure.database.postgres_pool import PostgresConnectionPool
from .postgres_research_source import PostgresResearchSource

logger = logging.getLogger(__name__)


class PostgresTickSource(IMarketDataGateway):
    """Fetches ticks and bars directly from PostgreSQL algotradeDB."""

    def __init__(self, pool: PostgresConnectionPool | None = None) -> None:
        self.pool = pool or PostgresConnectionPool()

    def stream_ticks(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Iterator[MatchedTick]:
        """Stream ticks from quote.matched table."""
        sql = """
            SELECT datetime, tickersymbol, price
            FROM quote.matched
            WHERE tickersymbol = %s
              AND datetime >= %s
              AND datetime <= %s
            ORDER BY datetime ASC
        """
        rows = self.pool.execute_query(sql, (symbol, start_time, end_time))
        for dt, sym, prc in rows:
            yield MatchedTick(
                symbol=sym,
                timestamp=dt,
                price=Decimal(str(prc)),
                # quote.matchedvolume is a separate asynchronous stream; an
                # exact-timestamp join would fabricate zeros for most trades.
                volume=0,
                match_type="",
            )

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start_date: date | datetime,
        end_date: date | datetime,
    ) -> list[Bar]:
        """Fetch 30-minute front-contract bars or explicitly requested daily bars."""
        start_day = start_date.date() if isinstance(start_date, datetime) else start_date
        end_day = end_date.date() if isinstance(end_date, datetime) else end_date
        if timeframe == "30m" and symbol == "VN30F1M":
            frame = PostgresResearchSource(self.pool).load_front_month_bars(
                start_day, end_day
            )
            return [
                Bar(
                    symbol=str(row.Contract),
                    timestamp=row.Datetime.to_pydatetime(),
                    open=Decimal(str(row.Open)),
                    high=Decimal(str(row.High)),
                    low=Decimal(str(row.Low)),
                    close=Decimal(str(row.Close)),
                    volume=int(row.Volume),
                )
                for row in frame.itertuples(index=False)
            ]
        if timeframe != "1d":
            raise ValueError(f"Unsupported PostgreSQL timeframe: {timeframe}")
        start_dt = datetime.combine(start_day, datetime.min.time())
        end_dt = datetime.combine(end_day, datetime.max.time())

        sql = """
            SELECT c.datetime, c.tickersymbol, o.price AS open, h.price AS high, l.price AS low, c.price AS close, v.quantity AS volume
            FROM quote.close c
            JOIN quote.open o ON c.datetime = o.datetime AND c.tickersymbol = o.tickersymbol
            JOIN quote.max h ON c.datetime = h.datetime AND c.tickersymbol = h.tickersymbol
            JOIN quote.min l ON c.datetime = l.datetime AND c.tickersymbol = l.tickersymbol
            LEFT JOIN quote.dailyvolume v ON c.datetime = v.datetime AND c.tickersymbol = v.tickersymbol
            WHERE c.tickersymbol = %s
              AND c.datetime >= %s
              AND c.datetime <= %s
            ORDER BY c.datetime ASC
        """
        rows = self.pool.execute_query(sql, (symbol, start_dt, end_dt))
        bars: list[Bar] = []
        for dt, sym, o, h, l, c, vol in rows:
            bars.append(
                Bar(
                    symbol=sym,
                    timestamp=dt,
                    open=Decimal(str(o)),
                    high=Decimal(str(h)),
                    low=Decimal(str(l)),
                    close=Decimal(str(c)),
                    volume=int(vol or 0),
                )
            )
        return bars

    def get_trading_days(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        sql = """
            SELECT DISTINCT datetime::date
            FROM quote.close
            WHERE tickersymbol = %s
              AND datetime >= %s
              AND datetime <= %s
            ORDER BY datetime::date ASC
        """
        rows = self.pool.execute_query(sql, (symbol, start_date, end_date))
        return [r[0] for r in rows]

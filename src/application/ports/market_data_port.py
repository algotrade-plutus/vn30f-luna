"""Application Port: Market Data Gateway interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date, datetime

from src.domain.entities.bar import Bar
from src.domain.entities.tick import MatchedTick, OrderBookSnapshot


class IMarketDataGateway(ABC):
    """Interface for obtaining historical and streaming market data."""

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start_date: date | datetime,
        end_date: date | datetime,
    ) -> list[Bar]:
        """Fetch historical bars in chronological order."""
        ...

    @abstractmethod
    def stream_ticks(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Iterator[MatchedTick]:
        """Stream tick-by-tick trades in chronological order."""
        ...

    @abstractmethod
    def get_trading_days(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """Return list of active trading dates in the given window."""
        ...

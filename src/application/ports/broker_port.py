"""Application Port: Broker / Execution Gateway interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.entities.fill import Fill
from src.domain.entities.margin import MarginSnapshot
from src.domain.entities.order import Order, OrderStatus
from src.domain.entities.position import Position


class IBrokerGateway(ABC):
    """Interface for order submission, position tracking, and margin queries."""

    @abstractmethod
    def submit_order(self, order: Order) -> tuple[bool, str]:
        """Submit order to exchange simulator or broker.
        Returns (is_accepted, reason_or_message).
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open active order."""
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position:
        """Return current open position for the specified symbol."""
        ...

    @abstractmethod
    def get_margin(self) -> MarginSnapshot:
        """Return latest margin snapshot and utilisation ratio."""
        ...

    @abstractmethod
    def get_fills(self) -> list[Fill]:
        """Return history of executed fills."""
        ...

    @abstractmethod
    def advance_to(self, timestamp: datetime) -> list[object]:
        """Advance exchange clock to specified time (for event-driven backtesting)."""
        ...

"""Domain entity: Trade Fill execution report.
Pure Python standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import uuid

from .order import Side


@dataclass(frozen=True)
class Fill:
    """A matched order execution (trade fill)."""
    order_id: str
    symbol: str
    side: Side
    quantity: int
    price: Decimal
    timestamp: datetime
    fee: Decimal = Decimal(0)
    tax: Decimal = Decimal(0)
    fill_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Fill quantity must be positive, got {self.quantity}")
        if self.price <= Decimal(0):
            raise ValueError(f"Fill price must be positive, got {self.price}")

    @property
    def notional_value(self) -> Decimal:
        """VN30F contract multiplier is 100,000 VND per index point."""
        return self.price * Decimal(self.quantity) * Decimal(100_000)

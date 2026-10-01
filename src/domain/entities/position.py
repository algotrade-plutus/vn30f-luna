"""Domain entity: Derivatives Position.
Pure Python standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .order import Side
from .fill import Fill


@dataclass
class Position:
    """Current open position for a derivative contract."""
    symbol: str
    net_quantity: int = 0
    average_price: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)
    multiplier: int = 100_000  # VN30 index futures multiplier: 100,000 VND / point

    @property
    def is_flat(self) -> bool:
        return self.net_quantity == 0

    @property
    def is_long(self) -> bool:
        return self.net_quantity > 0

    @property
    def is_short(self) -> bool:
        return self.net_quantity < 0

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Mark-to-market unrealized PnL."""
        if self.is_flat:
            return Decimal(0)
        point_diff = current_price - self.average_price
        return Decimal(self.net_quantity) * point_diff * Decimal(self.multiplier)

    def apply_fill(self, fill: Fill) -> tuple[Decimal, Decimal]:
        """Apply a fill event to the position.
        Returns (closed_quantity, realized_pnl_delta).
        """
        fill_qty = fill.quantity if fill.side == Side.BUY else -fill.quantity
        new_qty = self.net_quantity + fill_qty

        # Case 1: Opening or adding in same direction
        if self.net_quantity == 0 or (self.net_quantity > 0 and fill_qty > 0) or (self.net_quantity < 0 and fill_qty < 0):
            total_notional = (self.average_price * Decimal(abs(self.net_quantity))) + (fill.price * Decimal(fill.quantity))
            self.net_quantity = new_qty
            self.average_price = total_notional / Decimal(abs(new_qty))
            return Decimal(0), Decimal(0)

        # Case 2: Closing or reversing position
        closing_qty = min(abs(self.net_quantity), abs(fill_qty))
        if self.net_quantity > 0:
            # Closing long
            pnl_points = fill.price - self.average_price
        else:
            # Closing short
            pnl_points = self.average_price - fill.price
        pnl_delta = Decimal(closing_qty) * pnl_points * Decimal(self.multiplier)
        self.realized_pnl += pnl_delta

        if abs(fill_qty) > abs(self.net_quantity):
            # Reversed position
            self.average_price = fill.price
        elif new_qty == 0:
            # Flattened
            self.average_price = Decimal(0)
        # else: partial reduction keeps average_price unchanged

        self.net_quantity = new_qty
        return Decimal(closing_qty), pnl_delta

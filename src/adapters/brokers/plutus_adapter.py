"""Adapters Brokers: Plutus Broker Adapter.
Connects the domain IBrokerGateway interface to the realistic Plutus Exchange Simulator.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from typing import Any

from plutus.core.order import OrderType as PlutusOrderType, Side as PlutusSide
from plutus.market.protocol import Order as PlutusOrder
from plutus.market.session import Accepted, Cancelled, ExchangeSession, MarginStatus

from src.application.ports.broker_port import IBrokerGateway
from src.domain.entities.fill import Fill
from src.domain.entities.margin import MarginCallStatus, MarginSnapshot
from src.domain.entities.order import Order, OrderStatus, OrderType, Side
from src.domain.entities.position import Position

logger = logging.getLogger(__name__)


class PlutusBrokerAdapter(IBrokerGateway):
    """Wraps Plutus ExchangeSession to satisfy IBrokerGateway port."""

    def __init__(self, session: ExchangeSession) -> None:
        self.session = session
        self._order_ids: dict[str, str] = {}

    def submit_order(self, order: Order) -> tuple[bool, str]:
        """Convert domain Order to PlutusOrder and submit to session."""
        side = PlutusSide.BUY if order.side == Side.BUY else PlutusSide.SELL
        order_types = {
            OrderType.MARKET: PlutusOrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
            OrderType.LIMIT: PlutusOrderType.LIMIT,
            OrderType.ATO: PlutusOrderType.AT_THE_OPENING,
            OrderType.ATC: PlutusOrderType.AT_THE_CLOSE,
        }
        order_type = order_types[order.order_type]
        price_dec = Decimal(str(order.price)) if order.price else None

        plutus_order = PlutusOrder(
            ticker=order.symbol,
            side=side,
            quantity=order.quantity,
            order_type=order_type,
            limit_price=price_dec,
        )

        verdict = self.session.submit(plutus_order)
        if isinstance(verdict, Accepted):
            order.status = OrderStatus.ACCEPTED
            self._order_ids[order.order_id] = str(verdict.order_id)
            return True, "ACCEPTED"
        else:
            reason = str(verdict)
            order.status = OrderStatus.REJECTED
            order.reject_reason = reason
            logger.warning("Order rejected by Plutus: %s", reason)
            return False, reason

    def cancel_order(self, order_id: str) -> bool:
        plutus_id = self._order_ids.get(order_id)
        if plutus_id is None:
            return False
        return isinstance(self.session.cancel(plutus_id), Cancelled)

    def get_position(self, symbol: str) -> Position:
        """Fetch current open position from Plutus session."""
        p = self.session.positions().get(symbol)
        result = Position(symbol=symbol)
        for fill in self.get_fills():
            if fill.symbol == symbol:
                result.apply_fill(fill)
        # Preserve the engine's authoritative open quantity and basis.  The
        # replay above is used only to derive the domain's realised PnL.
        if p is not None:
            result.net_quantity = int(p.net_quantity)
            result.average_price = Decimal(str(p.average_entry))
            result.multiplier = int(p.multiplier)
        return result

    def get_margin(self) -> MarginSnapshot:
        """Fetch current margin status and map to domain MarginSnapshot."""
        m = self.session.margin()

        # Map status
        statuses = {
            MarginStatus.OK: MarginCallStatus.NORMAL,
            MarginStatus.WARNING: MarginCallStatus.WARNING,
            MarginStatus.CALL: MarginCallStatus.CALL,
            MarginStatus.FORCED: MarginCallStatus.FORCED,
            MarginStatus.INDETERMINATE: MarginCallStatus.INDETERMINATE,
        }
        status = statuses[m.status]

        im = Decimal(str(m.initial_margin or 0))
        dep = Decimal(str(m.deposit_balance or 0))
        vm = Decimal(str(getattr(m, "variation_margin", 0) or 0))
        ratio = Decimal(str(m.utilisation or 0))

        return MarginSnapshot(
            deposit_balance=dep,
            initial_margin=im,
            variation_margin=vm,
            # Vietnam does not publish a separate maintenance-margin fraction.
            maintenance_margin=Decimal(0),
            cash_balance=dep,
            # Domain equity is account capital, not Plutus MarginView.equity
            # (which means free deposit after the margin requirement).
            equity=dep,
            utilisation_ratio=ratio,
            status=status,
        )

    def get_fills(self) -> list[Fill]:
        """Convert session ledger fills into domain Fill entities."""
        fills: list[Fill] = []
        for record in self.session.orders():
            for fill in record.fills:
                tax = sum(
                    (charge.total for charge in fill.charges if charge.kind.startswith("pit_")),
                    Decimal(0),
                )
                fee = sum((charge.total for charge in fill.charges), Decimal(0)) - tax
                fills.append(
                    Fill(
                        fill_id=str(fill.fill_id),
                        order_id=str(fill.order_id),
                        symbol=fill.ticker,
                        side=(Side.BUY if fill.side is PlutusSide.BUY else Side.SELL),
                        quantity=fill.quantity,
                        price=fill.price,
                        timestamp=fill.ts,
                        fee=fee,
                        tax=tax,
                    )
                )
        return fills

    def advance_to(self, timestamp: datetime) -> list[Any]:
        """Advance Plutus simulated market clock."""
        return list(self.session.advance_to(timestamp))

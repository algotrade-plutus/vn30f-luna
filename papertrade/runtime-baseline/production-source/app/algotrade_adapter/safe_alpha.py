"""Workarounds for verified paperbroker-client 0.2.8 alpha defects."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from paperbroker.alpha import CloseSignal, OrderRequest, SignalDrivenAlpha
from paperbroker.execution.position_tracker import Position


class SafeSignalDrivenAlpha(SignalDrivenAlpha):
    """Alpha base with priced LIMIT exits and enriched position fills."""

    async def start(self) -> None:
        await super().start()
        for event in ("fix:order:partial_fill", "fix:order:filled"):
            self.client.on(event, self._apply_enriched_fill)
            self._subscriptions.append(
                lambda event=event: self.client.off(event, self._apply_enriched_fill)
            )

    def seed_positions(self, positions: Dict[str, int]) -> None:
        """Seed local position tracker with initial overnight positions from REST."""
        if self._position_tracker is None:
            return
        with self._position_tracker._lock:
            for instrument, qty in positions.items():
                pos = self._position_tracker._positions.setdefault(
                    instrument, Position(instrument=instrument)
                )
                pos.quantity = float(qty)

    def reconcile_positions(
        self,
        remote_positions: Dict[str, int],
        open_orders: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Reconcile local position tracker with REST portfolio when no working orders exist."""
        if self._position_tracker is None:
            return
        open_orders = open_orders or {}
        with self._position_tracker._lock:
            for instrument, qty in remote_positions.items():
                if not open_orders.get(instrument):
                    pos = self._position_tracker._positions.setdefault(
                        instrument, Position(instrument=instrument)
                    )
                    pos.quantity = float(qty)
            for instrument in list(self._position_tracker._positions.keys()):
                if instrument not in remote_positions and not open_orders.get(instrument):
                    self._position_tracker._positions[instrument].quantity = 0.0

    def _apply_enriched_fill(self, **payload: Any) -> None:
        # If upstream eventually adds symbol/side, its PositionTracker already
        # handled the event and this workaround must not double count it.
        if payload.get("instrument") or payload.get("symbol") or payload.get("full_symbol"):
            return
        cl_ord_id = payload.get("cl_ord_id")
        if not cl_ord_id or self._position_tracker is None:
            return

        tracked = self._orders.get(cl_ord_id)
        symbol = getattr(tracked, "symbol", None)
        side = getattr(tracked, "side", None)
        if not symbol and getattr(self.client, "orders", None) is not None:
            info: Dict[str, Any] = self.client.orders.order_info.get(cl_ord_id, {})
            exchange, raw_symbol = info.get("exchange"), info.get("symbol")
            symbol = f"{exchange}:{raw_symbol}" if exchange and raw_symbol else raw_symbol
            side = info.get("side")
        if not symbol or side not in {"BUY", "SELL"}:
            self.logger.error("Cannot enrich fill cl_ord_id=%s; forcing REST reconcile", cl_ord_id)
            return
        qty = float(payload.get("last_qty", 0) or 0)
        price = float(payload.get("last_px", 0) or 0)
        if qty <= 0 or price <= 0:
            return
        signed_qty = -qty if side == "SELL" else qty
        self._position_tracker.update(symbol, signed_qty, price, at=payload.get("at"))

    def _plan_close_orders(
        self, signal: CloseSignal, ctx: Any,
    ) -> List[OrderRequest]:
        pos = ctx.positions.get(signal.symbol)
        qty = abs(int(getattr(pos, "quantity", 0))) if pos is not None else 0
        quote = ctx.quotes.get(signal.symbol)
        if qty <= 0 or quote is None:
            return []
        if signal.side == "SELL":
            price = quote.bid_price_1 or quote.latest_matched_price
        else:
            price = quote.ask_price_1 or quote.latest_matched_price
        if price is None:
            self.logger.error("No reference price for close signal %s", signal.symbol)
            return []
        return [
            OrderRequest(
                symbol=signal.symbol,
                side=signal.side,
                qty=qty,
                price=float(price),
                ord_type="LIMIT",
                tag=signal.tag or "close",
            )
        ]

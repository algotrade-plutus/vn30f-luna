"""Application Use Case: Trading Cycle.
Executes the core trade cycle: bar ingestion -> signal evaluation -> risk guard -> broker execution.
Decoupled from specific strategy implementations via ISignalGateway.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from src.application.ports.broker_port import IBrokerGateway
from src.application.ports.signal_port import ISignalGateway
from src.application.use_cases.risk_monitor import RiskMonitorUseCase
from src.domain.entities.bar import Bar
from src.domain.entities.order import Order, OrderType, Side

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CycleLog:
    """Record of an executed trading cycle step."""

    timestamp: datetime
    symbol: str
    bar_close: float
    current_position: int
    target_position: int
    delta: int
    strategy_reason: str
    order_action: str
    order_status: str


class TradingCycleUseCase:
    """Orchestrates signal evaluation, risk checks, and order dispatch for each market bar."""

    def __init__(
        self,
        signal_gateway: ISignalGateway,
        broker: IBrokerGateway,
        risk_monitor: RiskMonitorUseCase,
        target_symbol: str,
    ) -> None:
        self.signal_gateway = signal_gateway
        self.broker = broker
        self.risk_monitor = risk_monitor
        self.target_symbol = target_symbol
        self.logs: list[CycleLog] = []

    def on_bar(self, bar: Bar) -> CycleLog:
        """Process incoming completed bar, compute alpha signal, evaluate risk, and place orders."""
        target_pos, reason = self.signal_gateway.get_target_position(bar.timestamp, bar)
        current_pos = self.broker.get_position(self.target_symbol)
        curr_qty = current_pos.net_quantity
        delta = target_pos - curr_qty

        order_action = "HOLD"
        order_status = "NONE"

        if delta != 0:
            is_increasing_exposure = abs(target_pos) > abs(curr_qty)
            risk_verdict = self.risk_monitor.evaluate()

            if is_increasing_exposure and not risk_verdict.can_trade:
                order_action = f"VETOED_BY_RISK: {risk_verdict.message}"
                order_status = "BLOCKED"
                logger.warning(
                    "Order blocked by risk: target %d, current %d, reason: %s",
                    target_pos,
                    curr_qty,
                    risk_verdict.message,
                )
            else:
                side = Side.BUY if delta > 0 else Side.SELL
                qty = abs(delta)
                order = Order(
                    symbol=self.target_symbol,
                    side=side,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                )
                accepted, msg = self.broker.submit_order(order)
                order_action = f"{side.value} {qty}"
                order_status = "ACCEPTED" if accepted else f"REJECTED: {msg}"

        log = CycleLog(
            timestamp=bar.timestamp,
            symbol=self.target_symbol,
            bar_close=float(bar.close),
            current_position=curr_qty,
            target_position=target_pos,
            delta=delta,
            strategy_reason=reason,
            order_action=order_action,
            order_status=order_status,
        )
        self.logs.append(log)
        return log

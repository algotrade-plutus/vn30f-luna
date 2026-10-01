"""Application Use Case: Margin & Risk Monitor.
Ensures margin utilisation is kept strictly below 80% and halts on margin calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging

from src.application.ports.broker_port import IBrokerGateway
from src.domain.entities.margin import MarginCallStatus, MarginSnapshot

logger = logging.getLogger(__name__)


@dataclass
class RiskVerdict:
    """Outcome of risk monitoring check."""
    can_trade: bool
    status: MarginCallStatus
    utilisation_pct: float
    message: str


class RiskMonitorUseCase:
    """Guards margin requirements and rejects order actions if margin is in warning/call."""

    def __init__(
        self,
        broker: IBrokerGateway,
        max_allowed_utilisation: float = 0.80,
    ) -> None:
        self.broker = broker
        self.max_allowed_utilisation = max_allowed_utilisation
        self.warning_count: int = 0
        self.call_count: int = 0
        self.forced_count: int = 0
        self.peak_utilisation: float = 0.0

    def evaluate(self) -> RiskVerdict:
        """Query margin snapshot from broker and evaluate safety."""
        snap = self.broker.get_margin()
        ratio_float = float(snap.utilisation_ratio)
        self.peak_utilisation = max(self.peak_utilisation, ratio_float)

        if snap.status == MarginCallStatus.WARNING:
            self.warning_count += 1
            logger.warning("Margin WARNING: utilisation at %.2f%%", ratio_float * 100)
        elif snap.status == MarginCallStatus.CALL:
            self.call_count += 1
            logger.error("Margin CALL (90%%): utilisation at %.2f%%", ratio_float * 100)
            return RiskVerdict(
                can_trade=False,
                status=snap.status,
                utilisation_pct=ratio_float * 100,
                message="Trading halted due to Margin Call (>= 90%)",
            )
        elif snap.status == MarginCallStatus.FORCED:
            self.forced_count += 1
            logger.critical("Margin FORCED LIQUIDATION: utilisation at %.2f%%", ratio_float * 100)
            return RiskVerdict(
                can_trade=False,
                status=snap.status,
                utilisation_pct=ratio_float * 100,
                message="Trading halted due to Forced Liquidation (>= 100%)",
            )
        elif snap.status == MarginCallStatus.INDETERMINATE:
            return RiskVerdict(
                can_trade=False,
                status=snap.status,
                utilisation_pct=ratio_float * 100,
                message="Trading halted because margin status is indeterminate",
            )

        if ratio_float >= self.max_allowed_utilisation:
            return RiskVerdict(
                can_trade=False,
                status=snap.status,
                utilisation_pct=ratio_float * 100,
                message=f"Utilisation ({ratio_float*100:.1f}%) exceeds safety threshold ({self.max_allowed_utilisation*100:.1f}%)",
            )

        return RiskVerdict(
            can_trade=True,
            status=snap.status,
            utilisation_pct=ratio_float * 100,
            message="Margin status safe",
        )

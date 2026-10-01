"""Domain entity: Margin Account and Margin Status.
Pure Python standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class MarginCallStatus(str, Enum):
    NORMAL = "NORMAL"        # Utilisation < 80% (Safe)
    WARNING = "WARNING"      # 80% <= Utilisation < 90% (Warning)
    CALL = "CALL"            # 90% <= Utilisation < 100% (Margin Call)
    FORCED = "FORCED"        # Utilisation >= 100% (Forced Liquidation)
    INDETERMINATE = "INDETERMINATE"  # Missing/stale mark: trading must fail closed


@dataclass(frozen=True)
class MarginSnapshot:
    """Point-in-time snapshot of margin status."""
    deposit_balance: Decimal
    initial_margin: Decimal
    variation_margin: Decimal
    maintenance_margin: Decimal
    cash_balance: Decimal
    equity: Decimal
    utilisation_ratio: Decimal  # initial_margin / (deposit_balance + variation_margin)
    status: MarginCallStatus

    @property
    def is_safe(self) -> bool:
        return self.status == MarginCallStatus.NORMAL

    @property
    def has_call(self) -> bool:
        return self.status in (MarginCallStatus.CALL, MarginCallStatus.FORCED)


@dataclass
class MarginAccount:
    """Margin account tracking cash, deposits, and collateral for VSDC/HNXDS."""
    initial_deposit: Decimal
    cash_balance: Decimal
    deposit_balance: Decimal  # VSDC escrow account
    initial_margin_rate: Decimal = Decimal("0.17")  # VSDC standard 17% Initial Margin rate
    im_warning_threshold: Decimal = Decimal("0.80")
    im_call_threshold: Decimal = Decimal("0.90")
    im_forced_threshold: Decimal = Decimal("1.00")

    @classmethod
    def create(cls, initial_capital: Decimal, im_rate: Decimal = Decimal("0.17")) -> MarginAccount:
        return cls(
            initial_deposit=initial_capital,
            cash_balance=initial_capital,
            deposit_balance=initial_capital,
            initial_margin_rate=im_rate,
        )

    def calculate_status(
        self,
        net_quantity: int,
        settlement_price: Decimal,
        daily_variation_margin: Decimal = Decimal(0),
    ) -> MarginSnapshot:
        """Evaluate margin requirements and check for warnings / calls."""
        multiplier = Decimal(100_000)
        notional = Decimal(abs(net_quantity)) * settlement_price * multiplier
        required_im = notional * self.initial_margin_rate

        # Total available margin collateral
        available_collateral = self.deposit_balance + daily_variation_margin
        if available_collateral > Decimal(0):
            ratio = required_im / available_collateral
        else:
            ratio = Decimal(999) if required_im > Decimal(0) else Decimal(0)

        if ratio >= self.im_forced_threshold:
            status = MarginCallStatus.FORCED
        elif ratio >= self.im_call_threshold:
            status = MarginCallStatus.CALL
        elif ratio >= self.im_warning_threshold:
            status = MarginCallStatus.WARNING
        else:
            status = MarginCallStatus.NORMAL

        equity = self.cash_balance + daily_variation_margin
        return MarginSnapshot(
            deposit_balance=self.deposit_balance,
            initial_margin=required_im,
            variation_margin=daily_variation_margin,
            maintenance_margin=required_im * Decimal("0.8"),
            cash_balance=self.cash_balance,
            equity=equity,
            utilisation_ratio=ratio,
            status=status,
        )

"""Configuration with standard derivatives fee convention made explicit."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    """Backtest settings.

    Standard convention exposes ``fee=0.8`` as a round-trip fee. Accounting charges half
    of it per unit position change, so a 0 -> 1 -> 0 trade costs 0.8 points and
    a direct +1 -> -1 reversal costs 0.8 points at the reversal itself.
    """

    round_trip_fee_points: float = 0.8
    annualization_days: int = 252
    require_discrete_position: bool = True
    position_tolerance: float = 1e-12

    def __post_init__(self) -> None:
        if self.round_trip_fee_points < 0.0:
            raise ValueError("round-trip fee cannot be negative")
        if self.annualization_days < 1:
            raise ValueError("annualization_days must be positive")
        if self.position_tolerance < 0.0:
            raise ValueError("position tolerance cannot be negative")

    @property
    def fee_per_position_unit(self) -> float:
        return self.round_trip_fee_points / 2.0


__all__ = ["BacktestConfig"]

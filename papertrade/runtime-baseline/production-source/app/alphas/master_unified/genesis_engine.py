"""Point-in-time intraday features for the Genesis PaperTrade runtime.

Historical bars are left-labelled.  This engine therefore consumes
only bars that the live aggregator has closed, plus the current 13:00 open for
the lunch gap.  The pre-ATC basis is supplied from synchronized live quotes;
it never reads the historical 14:30 bucket containing the 14:45 uncross.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

from .hybrid_engine import Bar30m
from .schedule import third_thursday


@dataclass(frozen=True)
class GenesisIntradayParameters:
    orb_thresh_pct: float = 0.0
    min_range_pct: float = 0.0
    orb_mode: str = "short_only"
    lunch_gap_thresh_pct: float = -0.0003
    basis_veto_bps: float = 45.0
    expiry_basis_thresh_bps: float = 30.0
    days_before_expiry: tuple[int, ...] = (1, 2, 3)

    def __post_init__(self) -> None:
        if self.orb_mode not in {"short_only", "both"}:
            raise ValueError("orb_mode must be 'short_only' or 'both'")


@dataclass(frozen=True)
class GenesisIntradaySnapshot:
    orb: int
    lunch: int
    basis_bps: Optional[float]
    basis_veto: bool
    expiry_arb: int


class GenesisIntradayEngine:
    """Compute Genesis features from the information available right now."""

    def __init__(self, params: Optional[GenesisIntradayParameters] = None) -> None:
        self.params = params or GenesisIntradayParameters()

    @staticmethod
    def _parsed(bar: Bar30m) -> datetime:
        return datetime.fromisoformat(bar.datetime)

    def _session_bars(self, bars: Iterable[Bar30m], day: date) -> list[Bar30m]:
        result = [bar for bar in bars if self._parsed(bar).date() == day]
        result.sort(key=lambda bar: self._parsed(bar))
        return result

    def _orb(self, bars: list[Bar30m]) -> int:
        opening = next(
            (bar for bar in bars if self._parsed(bar).strftime("%H:%M") == "09:00"),
            None,
        )
        if opening is None:
            return 0

        if opening.high > 0 and ((opening.high - opening.low) / opening.high) < self.params.min_range_pct:
            return 0

        state = 0
        both = self.params.orb_mode == "both"
        eligible = {
            "09:30", "10:00", "10:30", "11:00", "11:30",
            "13:00", "13:30", "14:00",
        }
        for bar in bars:
            stamp = self._parsed(bar).strftime("%H:%M")
            if stamp not in eligible:
                continue
            close = bar.close
            if state == 0:
                if both and close > opening.high * (1.0 + self.params.orb_thresh_pct):
                    state = 1
                elif close < opening.low * (1.0 - self.params.orb_thresh_pct):
                    state = -1
            elif state == 1 and close < opening.low:
                state = -1 if both else 0
            elif state == -1 and close > opening.high:
                state = 1 if both else 0
        return state

    def _lunch(self, bars: list[Bar30m], current: Optional[Bar30m]) -> int:
        if current is None:
            return 0
        current_at = self._parsed(current)
        if current_at.strftime("%H:%M") not in {"13:00", "13:30", "14:00"}:
            return 0
        morning = [bar for bar in bars if self._parsed(bar).time().hour < 12]
        if not morning:
            return 0
        morning_close = float(morning[-1].close)
        if morning_close <= 0:
            return 0
        gap_pct = (float(current.open) - morning_close) / morning_close
        return -1 if gap_pct <= self.params.lunch_gap_thresh_pct else 0

    def evaluate(
        self,
        *,
        bars: Iterable[Bar30m],
        current: Optional[Bar30m],
        now: datetime,
        basis_bps: Optional[float],
        pre_atc: bool,
    ) -> GenesisIntradaySnapshot:
        session = self._session_bars(bars, now.date())
        days_to_expiry = (third_thursday(now.year, now.month) - now.date()).days
        expiry_arb = (
            -1
            if basis_bps is not None
            and days_to_expiry in self.params.days_before_expiry
            and basis_bps >= self.params.expiry_basis_thresh_bps
            else 0
        )
        return GenesisIntradaySnapshot(
            orb=self._orb(session),
            lunch=self._lunch(session, current),
            basis_bps=basis_bps,
            basis_veto=bool(
                pre_atc and basis_bps is not None and basis_bps > self.params.basis_veto_bps
            ),
            expiry_arb=expiry_arb,
        )

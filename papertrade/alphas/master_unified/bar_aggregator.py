"""Causal 30-minute bar aggregator from live quotes for PaperTrade runtimes.

Constructs left-labelled 30-minute bars according to the official HOSE/HNX
trading schedule (09:00-09:30, 09:30-10:00, ..., 14:00-14:30).
"""

from __future__ import annotations

import logging
from datetime import datetime, time as clock_time
from typing import Optional

from .hybrid_engine import Bar30m

LOGGER = logging.getLogger(__name__)


class BarAggregator:
    """Track and construct live 30m bars from quote updates."""

    def __init__(self) -> None:
        self.current_bar_start: Optional[datetime] = None
        self.current_bar_first_quote: Optional[datetime] = None
        self.bar_open: Optional[float] = None
        self.bar_high: Optional[float] = None
        self.bar_low: Optional[float] = None
        self.bar_close: Optional[float] = None
        self.bar_transition_pending: bool = False

    @staticmethod
    def bucket_start(local_now: datetime) -> Optional[datetime]:
        """Map local timestamp to the 30-minute bar's left-labelled start time."""
        current = local_now.time()
        if clock_time(9, 0) <= current < clock_time(11, 30):
            minute = 30 if local_now.minute >= 30 else 0
            return local_now.replace(minute=minute, second=0, microsecond=0)
        if current == clock_time(11, 30):
            return local_now.replace(hour=11, minute=0, second=0, microsecond=0)
        if clock_time(13, 0) <= current <= clock_time(14, 45):
            minute = 30 if local_now.minute >= 30 else 0
            return local_now.replace(minute=minute, second=0, microsecond=0)
        return None

    def current_bar_snapshot(self) -> Optional[Bar30m]:
        """Snapshot the currently accumulating (incomplete) bar."""
        if self.current_bar_start is None or self.bar_close is None:
            return None
        return Bar30m(
            datetime=self.current_bar_start.strftime("%Y-%m-%d %H:%M:%S"),
            open=float(self.bar_open if self.bar_open is not None else self.bar_close),
            high=float(self.bar_high if self.bar_high is not None else self.bar_close),
            low=float(self.bar_low if self.bar_low is not None else self.bar_close),
            close=float(self.bar_close),
        )

    def start_bar(self, bucket_start: datetime, price: float, observed_at: datetime) -> None:
        """Initialize a new 30-minute bar."""
        self.current_bar_start = bucket_start
        self.current_bar_first_quote = observed_at
        self.bar_open = price
        self.bar_high = price
        self.bar_low = price
        self.bar_close = price

    def update(self, price: float, local_now: datetime) -> Optional[Bar30m]:
        """Update live bar state with a new quote.

        Returns:
            Completed Bar30m if this quote closed a prior bar, else None.
        """
        bucket_start = self.bucket_start(local_now)
        if bucket_start is None:
            return None
        if self.current_bar_start is None:
            self.start_bar(bucket_start, price, local_now)
            return None
        if bucket_start < self.current_bar_start:
            return None
        if bucket_start == self.current_bar_start:
            self.bar_high = max(float(self.bar_high), price)
            self.bar_low = min(float(self.bar_low), price)
            self.bar_close = price
            return None

        # Bucket advanced: snapshot the completed previous bar
        completed = self.current_bar_snapshot()
        self.bar_transition_pending = True
        self.start_bar(bucket_start, price, local_now)
        return completed

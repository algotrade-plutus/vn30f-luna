"""DNSE 1-minute bars for the live Calibrum runtime, built the way the research base is.

DNSE's public chart API (the research source) returns closed minutes only, a
second or two after each minute ends. Consecutive reads can come from caches
at different points in time, so a read may lack minutes an earlier read had.
``MinuteBook`` therefore:

- ignores a read whose last minute is older than the last confirmed minute,
- confirms a minute once two consecutive reads agree on its OHLCV,
- never changes a confirmed minute (a later revision is counted, not applied).

Futures bars get the front-month ``Contract`` code from the exchange calendar,
as in ``src.adapters.data.dnse_minute_bars``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from src.adapters.data.dnse_candle_source import (
    _request_payload,
    add_front_month_contract,
    payload_to_frame,
)

FUTURES = ("derivative", "VN30F1M")
INDEX = ("index", "VN30")
COLUMNS = ["Datetime", "Open", "High", "Low", "Close", "Volume"]
BOOTSTRAP_DAYS = 70
POLL_MINUTES = 20

Fetch = Callable[[str, str, int, int], dict[str, Any]]


def _empty() -> pd.DataFrame:
    frame = pd.DataFrame({column: pd.Series(dtype=float) for column in COLUMNS})
    frame["Datetime"] = pd.Series(dtype="datetime64[ns]")
    return frame


def dnse_fetch(market: str, symbol: str, from_epoch: int, to_epoch: int) -> dict[str, Any]:
    return _request_payload(market, symbol, 1, from_epoch, to_epoch, retries=2, timeout=10)


@dataclass
class MinuteBook:
    """Confirmed closed minutes of one series."""

    bars: pd.DataFrame = field(default_factory=_empty)
    pending: dict[pd.Timestamp, tuple] = field(default_factory=dict)
    stale_reads: int = 0
    revisions: int = 0

    @property
    def last(self) -> pd.Timestamp | None:
        return None if self.bars.empty else self.bars["Datetime"].iloc[-1]

    def seed(self, frame: pd.DataFrame, now: pd.Timestamp) -> None:
        """Trust history up to the minute before the last one; the last one still needs a second read."""
        closed = frame[frame["Datetime"] + pd.Timedelta(minutes=1) <= now]
        self.bars = closed.iloc[:-1][COLUMNS].reset_index(drop=True)
        self.merge(closed.tail(1), now)

    def merge(self, read: pd.DataFrame, now: pd.Timestamp) -> list[pd.Timestamp]:
        """Fold one read in; returns the minutes it confirmed."""
        read = read[read["Datetime"] + pd.Timedelta(minutes=1) <= now]
        if read.empty:
            return []
        last = self.last
        if last is not None and read["Datetime"].iloc[-1] < last:
            self.stale_reads += 1
            return []
        if last is not None:
            known = read[read["Datetime"] <= last].merge(self.bars, on="Datetime", suffixes=("", "_kept"))
            changed = (known[COLUMNS[1:]].to_numpy() != known[[f"{c}_kept" for c in COLUMNS[1:]]].to_numpy()).any(axis=1)
            self.revisions += int(changed.sum())
            read = read[read["Datetime"] > last]

        seen = {row.Datetime: tuple(getattr(row, c) for c in COLUMNS[1:]) for row in read.itertuples(index=False)}
        confirmed = []
        for stamp in sorted(seen):
            if self.pending.get(stamp) == seen[stamp]:
                confirmed.append(stamp)
            else:
                break
        self.pending = {stamp: values for stamp, values in seen.items() if stamp not in confirmed}
        if confirmed:
            rows = pd.DataFrame([(stamp, *seen[stamp]) for stamp in confirmed], columns=COLUMNS)
            self.bars = rows if self.bars.empty else pd.concat([self.bars, rows], ignore_index=True)
        return confirmed


class DnseFeed:
    """VN30F1M and VN30 minute books fed by polling DNSE."""

    def __init__(self, fetch: Fetch = dnse_fetch, clock: Callable[[], float] = time.time) -> None:
        self.fetch = fetch
        self.clock = clock
        self.books = {FUTURES: MinuteBook(), INDEX: MinuteBook()}

    def _read(self, series: tuple[str, str], minutes_back: int) -> pd.DataFrame:
        now = int(self.clock())
        return payload_to_frame(self.fetch(*series, now - minutes_back * 60, now + 60))

    def bootstrap(self, now: pd.Timestamp) -> None:
        for series, book in self.books.items():
            book.seed(self._read(series, BOOTSTRAP_DAYS * 24 * 60), now)

    def poll(self, now: pd.Timestamp) -> dict[tuple[str, str], list[pd.Timestamp]]:
        return {series: book.merge(self._read(series, POLL_MINUTES), now) for series, book in self.books.items()}

    def futures(self) -> pd.DataFrame:
        return add_front_month_contract(self.books[FUTURES].bars)

    def index(self) -> pd.DataFrame:
        return self.books[INDEX].bars.copy()

    def age_seconds(self, series: tuple[str, str], now: pd.Timestamp) -> float | None:
        """Seconds since the last confirmed minute closed."""
        last = self.books[series].last
        return None if last is None else (now - last - pd.Timedelta(minutes=1)).total_seconds()

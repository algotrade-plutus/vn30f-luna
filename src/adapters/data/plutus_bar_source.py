"""Plutus market-data adapter for canonical 30-minute research bars.

The canonical bars are left-labelled.  A row is therefore not visible through
``state_at`` until its completion instant.  This is the timing boundary that
prevents a signal computed from a bar close from filling at that same close.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
import re
from typing import Any

import pandas as pd

from plutus.market.protocol import (
    BandSource,
    InstrumentKind,
    InstrumentSpec,
    MarketState,
    Resolution,
    SessionPhase,
)
from plutus.market.session import DataField, MarketInterval

from src.domain.entities.bar import Bar
from src.domain.strategy.calendar_rules import is_expiry_thursday


_CONTRACT_RE = re.compile(r"^VN30F(?P<yy>\d{2})(?P<mm>\d{2})$")
_PRICE_TICK = Decimal("0.1")


@dataclass(frozen=True)
class ReplayBar:
    """One completed strategy bar and the real contract traded by that row."""

    bar: Bar
    contract: str
    start: datetime
    end: datetime
    is_last_of_day: bool


@dataclass(frozen=True)
class _ObservedBar:
    ticker: str
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    reference: Decimal
    ceiling: Decimal
    floor: Decimal
    band_source: BandSource


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _bar_end(start: datetime, minutes: int) -> datetime:
    """Return when a left-labelled bar is fully observable.

    The 11:30 row is the small boundary print in this dataset.  It becomes
    visible one microsecond after the ordinary 11:00-11:30 bar so both rows
    retain a strict order.  The 14:30 row represents the closing interval and
    completes at the HNX derivatives close, 14:45.
    """

    if start.time() == time(11, 30):
        return start + timedelta(microseconds=1)
    if start.time() == time(14, 30):
        return start + timedelta(minutes=15)
    return start + timedelta(minutes=minutes)


def _contract_expiry(contract: str) -> date | None:
    match = _CONTRACT_RE.fullmatch(contract)
    if match is None:
        return None
    year = 2000 + int(match.group("yy"))
    month = int(match.group("mm"))
    for day in range(1, 22):
        candidate = date(year, month, day)
        if is_expiry_thursday(candidate):
            return candidate
    raise AssertionError(f"No third Thursday found for {contract}")


class PlutusBarSource:
    """Serve real-contract VN30F bars to :class:`ExchangeSession`.

    Plutus currently exposes daily and tick session resolutions.  This source
    declares ``TICK`` and serves a completed 30-minute interval at each replay
    clock step.  The exact interval is carried in ``MarketInterval.start/end``
    and in the run metadata; no 30-minute row is silently presented as daily.

    Database frames can carry published daily reference/ceiling/floor values.
    If a particular row lacks any of them, those admission fields alone are
    reconstructed from the previous observed close and marked
    ``BandSource.RECONSTRUCTED``.
    """

    SERVES_RESOLUTIONS = frozenset({Resolution.TICK})

    def __init__(
        self,
        futures_path: Path | str | pd.DataFrame,
        index_path: Path | str | pd.DataFrame | None = None,
        *,
        bar_minutes: int = 30,
        book_provider: Any | None = None,
    ) -> None:
        if bar_minutes not in (5, 30):
            raise ValueError(f"Unsupported Plutus bar size: {bar_minutes} minutes")
        self.bar_minutes = bar_minutes
        self.book_provider = book_provider
        self.futures_path = (
            Path(futures_path) if isinstance(futures_path, (str, Path)) else None
        )
        self.index_path = (
            Path(index_path) if isinstance(index_path, (str, Path)) else None
        )
        self.origin = "postgresql:algotradeDB" if isinstance(futures_path, pd.DataFrame) else str(self.futures_path)
        self._rows: dict[str, list[_ObservedBar]] = {}
        self._ends: dict[str, list[datetime]] = {}
        self._strategy_rows: list[ReplayBar] = []
        self.band_source_counts: dict[str, int] = {
            BandSource.PUBLISHED.value: 0,
            BandSource.RECONSTRUCTED.value: 0,
        }
        self._load_futures(futures_path)
        if isinstance(index_path, pd.DataFrame) or (
            self.index_path is not None and self.index_path.is_file()
        ):
            self._load_index(index_path)  # type: ignore[arg-type]

    @staticmethod
    def _read(source: Path | str | pd.DataFrame) -> pd.DataFrame:
        if isinstance(source, pd.DataFrame):
            frame = source.copy()
        else:
            path = Path(source)
            if not path.is_file():
                raise FileNotFoundError(path)
            frame = pd.read_parquet(path)
        frame.columns = [str(column).capitalize() for column in frame.columns]
        required = {"Datetime", "Open", "High", "Low", "Close", "Volume"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        frame["Datetime"] = pd.to_datetime(frame["Datetime"])
        return frame.sort_values("Datetime").reset_index(drop=True)

    @staticmethod
    def _references(frame: pd.DataFrame, ticker_column: str) -> list[Decimal]:
        references: list[Decimal] = []
        previous_day_close: dict[str, Decimal] = {}
        current_day: dict[str, date] = {}
        latest_close: dict[str, Decimal] = {}
        for row in frame.itertuples(index=False):
            ticker = str(getattr(row, ticker_column))
            day = row.Datetime.date()
            close = _decimal(row.Close)
            if current_day.get(ticker) != day:
                if ticker in latest_close:
                    previous_day_close[ticker] = latest_close[ticker]
                current_day[ticker] = day
            references.append(previous_day_close.get(ticker, close))
            latest_close[ticker] = close
        return references

    @staticmethod
    def _bands(row: object, fallback_reference: Decimal) -> tuple[Decimal, Decimal, Decimal, BandSource]:
        published = all(
            hasattr(row, name) and not pd.isna(getattr(row, name))
            for name in ("Reference", "Ceiling", "Floor")
        )
        if published:
            return (
                _decimal(getattr(row, "Reference")),
                _decimal(getattr(row, "Ceiling")),
                _decimal(getattr(row, "Floor")),
                BandSource.PUBLISHED,
            )
        reference = fallback_reference
        ceiling = (reference * Decimal("1.07")).quantize(
            _PRICE_TICK, rounding=ROUND_FLOOR
        )
        floor = (reference * Decimal("0.93")).quantize(
            _PRICE_TICK, rounding=ROUND_CEILING
        )
        return reference, ceiling, floor, BandSource.RECONSTRUCTED

    def _load_futures(self, source: Path | str | pd.DataFrame) -> None:
        frame = self._read(source)
        if "Contract" not in frame.columns:
            raise ValueError("Futures research data is missing Contract")
        frame["Ticker"] = frame["Contract"].astype(str)
        references = self._references(frame, "Ticker")
        last_by_day = frame.groupby(frame["Datetime"].dt.date)["Datetime"].max()

        for row, reference in zip(frame.itertuples(index=False), references):
            start = row.Datetime.to_pydatetime()
            end = _bar_end(start, self.bar_minutes)
            contract = str(row.Contract)
            reference, ceiling, floor, band_source = self._bands(row, reference)
            self.band_source_counts[band_source.value] += 1
            observed = _ObservedBar(
                ticker=contract,
                start=start,
                end=end,
                open=_decimal(row.Open),
                high=_decimal(row.High),
                low=_decimal(row.Low),
                close=_decimal(row.Close),
                volume=max(int(row.Volume or 0), 0),
                reference=reference,
                ceiling=ceiling,
                floor=floor,
                band_source=band_source,
            )
            self._rows.setdefault(contract, []).append(observed)
            domain_bar = Bar(
                symbol=contract,
                timestamp=start,
                open=observed.open,
                high=observed.high,
                low=observed.low,
                close=observed.close,
                volume=observed.volume,
            )
            self._strategy_rows.append(
                ReplayBar(
                    bar=domain_bar,
                    contract=contract,
                    start=start,
                    end=end,
                    is_last_of_day=start == last_by_day[start.date()].to_pydatetime(),
                )
            )
        self._reindex()

    def _load_index(self, source: Path | str | pd.DataFrame) -> None:
        frame = self._read(source)
        frame["Ticker"] = "VN30"
        references = self._references(frame, "Ticker")
        for row, reference in zip(frame.itertuples(index=False), references):
            start = row.Datetime.to_pydatetime()
            reference, ceiling, floor, band_source = self._bands(row, reference)
            self._rows.setdefault("VN30", []).append(
                _ObservedBar(
                    ticker="VN30",
                    start=start,
                    end=_bar_end(start, self.bar_minutes),
                    open=_decimal(row.Open),
                    high=_decimal(row.High),
                    low=_decimal(row.Low),
                    close=_decimal(row.Close),
                    volume=max(int(row.Volume or 0), 0),
                    reference=reference,
                    ceiling=ceiling,
                    floor=floor,
                    band_source=band_source,
                )
            )
        self._reindex()

    def _reindex(self) -> None:
        for ticker, rows in self._rows.items():
            rows.sort(key=lambda row: row.end)
            self._ends[ticker] = [row.end for row in rows]
        self._strategy_rows.sort(key=lambda row: row.start)

    def replay_bars(self, start: date, end: date) -> list[ReplayBar]:
        """Return an inclusive date window in chronological order."""

        return [row for row in self._strategy_rows if start <= row.start.date() <= end]

    def trading_days(self) -> frozenset[date]:
        return frozenset(row.start.date() for row in self._strategy_rows)

    def _latest(self, ticker: str, ts: datetime) -> _ObservedBar | None:
        ends = self._ends.get(ticker, [])
        index = bisect_right(ends, ts) - 1
        if index < 0:
            return None
        return self._rows[ticker][index]

    @staticmethod
    def _state(row: _ObservedBar, ts: datetime) -> MarketState:
        phase = (
            SessionPhase.CLOSING_AUCTION
            if row.start.time() == time(14, 30)
            else SessionPhase.CONTINUOUS
        )
        return MarketState(
            ticker=row.ticker,
            ts=ts,
            reference=row.reference,
            ceiling=row.ceiling,
            floor=row.floor,
            band_source=row.band_source,
            last=row.close,
            session=phase,
        )

    def state_at(self, ticker: str, ts: datetime) -> MarketState | None:
        row = self._latest(ticker, ts)
        return None if row is None else self._state(row, ts)

    def book_at(
        self,
        ticker: str,
        ts: datetime,
        *,
        max_age: timedelta | None = None,
    ):
        """Delegate the instantaneous ladder without changing bar semantics."""

        if self.book_provider is None:
            raise ValueError("No order-book provider is attached to PlutusBarSource")
        return self.book_provider.book_at(ticker, ts, max_age=max_age)

    def states(
        self,
        ticker: str,
        start: date | datetime,
        end: date | datetime,
        *,
        resolution: Resolution = Resolution.DAILY,
    ) -> Iterator[MarketState]:
        start_dt = (
            datetime.combine(start, time.min) if isinstance(start, date) and not isinstance(start, datetime) else start
        )
        end_dt = (
            datetime.combine(end, time.min) if isinstance(end, date) and not isinstance(end, datetime) else end
        )
        for row in self._rows.get(ticker, []):
            if start_dt <= row.end < end_dt:
                yield self._state(row, row.end)

    def instrument(self, ticker: str) -> InstrumentSpec:
        if ticker == "VN30":
            return InstrumentSpec(
                ticker=ticker,
                exchange_code="HSX",
                kind=InstrumentKind.INDEX,
                trading_unit=1,
                daily_trading_limit=Decimal("0.07"),
            )
        expiry = _contract_expiry(ticker)
        if expiry is not None:
            return InstrumentSpec(
                ticker=ticker,
                exchange_code="HNXDS",
                kind=InstrumentKind.FUTURE,
                trading_unit=1,
                daily_trading_limit=Decimal("0.07"),
                multiplier=Decimal("100000"),
                expiry=expiry,
                underlying="VN30",
            )
        return InstrumentSpec(
            ticker=ticker,
            exchange_code="",
            kind=InstrumentKind.UNKNOWN,
            trading_unit=1,
            daily_trading_limit=Decimal("0"),
        )

    def interval(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        *,
        resolution: Resolution,
    ) -> MarketInterval | None:
        if resolution is not Resolution.TICK:
            raise ValueError(f"PlutusBarSource cannot serve {resolution.value}")
        row = self._latest(ticker, start)
        if row is None:
            return None
        # A composed book provider serves size through ``book_at`` just like
        # Plutus' BookSessionSource; do not let the interval audit falsely
        # report that a depth-backed fill ignored book size.
        missing = (
            frozenset({DataField.BOOK_SIZE})
            if self.book_provider is None
            else frozenset()
        )
        return MarketInterval(
            ticker=ticker,
            start=row.start,
            end=row.end,
            resolution=resolution,
            state=self._state(row, start),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            missing=missing,
        )

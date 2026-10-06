"""DNSE public chart API adapter for cached 30-minute research candles.

This adapter downloads OHLCV bars from DNSE's public chart API and caches them
as local parquet files under ``data/dnse``. The returned frames use timezone-naive
local Vietnam exchange time and the canonical research columns:

    Datetime, Open, High, Low, Close, Volume
"""
from __future__ import annotations

import json
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

API_URL_TEMPLATE = "https://api.dnse.com.vn/chart-api/v2/ohlcs/{market}"
VIETNAM_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")
REQUIRED_COLUMNS = ("Datetime", "Open", "High", "Low", "Close", "Volume")
OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "dnse"
CACHE_COVERAGE_TOLERANCE_DAYS = 10
DEFAULT_CHUNK_DAYS = 365
DEFAULT_TIMEOUT = 30
DEFAULT_USER_AGENT = "luna-vn30f-research"

__all__ = [
    "DnseCandleSource",
    "DnseDataError",
    "cache_path",
    "fetch_dnse_bars",
    "load_cached_bars",
    "load_or_fetch_dnse_bars",
    "normalize_bars",
    "payload_to_frame",
    "save_cached_bars",
]


class DnseDataError(RuntimeError):
    """Raised when DNSE data cannot be fetched, parsed, or validated."""


def _empty_frame() -> pd.DataFrame:
    frame = pd.DataFrame(columns=list(REQUIRED_COLUMNS))
    frame["Datetime"] = pd.to_datetime(frame["Datetime"])
    for column in OHLCV_COLUMNS:
        frame[column] = pd.to_numeric(frame[column])
    return frame


def normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and canonicalize an OHLCV bar frame."""
    if frame is None:
        raise DnseDataError("No bar frame supplied")

    if len(frame) == 0:
        return _empty_frame()

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DnseDataError(f"Bar frame is missing columns: {missing}")

    out = frame.loc[:, list(REQUIRED_COLUMNS)].copy()
    out["Datetime"] = pd.to_datetime(out["Datetime"], errors="raise")
    if getattr(out["Datetime"].dt, "tz", None) is not None:
        out["Datetime"] = out["Datetime"].dt.tz_convert(VIETNAM_TZ).dt.tz_localize(None)

    for column in OHLCV_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    if out[OHLCV_COLUMNS].isna().any().any():
        raise DnseDataError("Bars contain missing OHLCV values")

    invalid_ohlc = (
        (out["High"] < out["Low"])
        | (out["Open"] < out["Low"])
        | (out["Open"] > out["High"])
        | (out["Close"] < out["Low"])
        | (out["Close"] > out["High"])
    )
    if invalid_ohlc.any():
        # Repair malformed public candles where high/low may be swapped or do not
        # envelop open/close. OHLC validity is then re-checked.
        out["High"] = out[["Open", "High", "Low", "Close"]].max(axis=1)
        out["Low"] = out[["Open", "High", "Low", "Close"]].min(axis=1)
        invalid_ohlc = (
            (out["High"] < out["Low"])
            | (out["Open"] < out["Low"])
            | (out["Open"] > out["High"])
            | (out["Close"] < out["Low"])
            | (out["Close"] > out["High"])
        )
        if invalid_ohlc.any():
            raise DnseDataError(f"Bars contain {int(invalid_ohlc.sum())} invalid OHLC rows")

    if (out["Volume"] < 0).any():
        raise DnseDataError("Bars contain negative volume")

    out = (
        out.sort_values("Datetime", kind="mergesort")
        .drop_duplicates("Datetime", keep="last")
        .reset_index(drop=True)
    )
    return out


def payload_to_frame(payload: dict[str, Any]) -> pd.DataFrame:
    """Convert a DNSE chart-API payload into a normalized bar DataFrame."""
    if not isinstance(payload, dict):
        raise DnseDataError("DNSE response was not a JSON object")

    fields = ("t", "o", "h", "l", "c", "v")
    missing = [field for field in fields if field not in payload]
    if missing:
        raise DnseDataError(f"DNSE payload missing fields: {missing}")

    lengths = {len(payload[field] or []) for field in fields}
    if len(lengths) > 1:
        raise DnseDataError("DNSE payload fields have inconsistent lengths")
    if lengths == {0}:
        return _empty_frame()

    raw = pd.DataFrame(
        {
            "Datetime": payload["t"],
            "Open": payload["o"],
            "High": payload["h"],
            "Low": payload["l"],
            "Close": payload["c"],
            "Volume": payload["v"],
        }
    )

    timestamps = pd.to_numeric(raw["Datetime"], errors="coerce")
    if timestamps.isna().any():
        raise DnseDataError("DNSE payload contains invalid timestamps")

    if float(timestamps.abs().max()) > 1.0e12:
        timestamps = timestamps // 1000.0

    raw["Datetime"] = (
        pd.to_datetime(timestamps, unit="s", utc=True)
        .dt.tz_convert(VIETNAM_TZ)
        .dt.tz_localize(None)
    )
    return normalize_bars(raw)


def _request_payload(
    market: str,
    symbol: str,
    resolution: int,
    from_epoch: int,
    to_epoch: int,
    *,
    retries: int = 3,
    timeout: int = DEFAULT_TIMEOUT,
    pause_seconds: float = 0.25,
) -> dict[str, Any]:
    url = API_URL_TEMPLATE.format(market=market)
    params = {
        "symbol": symbol,
        "resolution": str(resolution),
        "from": str(from_epoch),
        "to": str(to_epoch),
    }
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT},
    )

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise DnseDataError("DNSE response was not a JSON object")
            return payload
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, DnseDataError) as exc:
            last_error = exc
            if attempt < retries:
                time_module.sleep(pause_seconds * attempt)

    raise DnseDataError(
        f"DNSE request failed for {market}/{symbol}: {type(last_error).__name__}"
    ) from last_error


def _epoch_bounds(day_start: date, day_end: date) -> tuple[int, int]:
    start_dt = datetime.combine(day_start, time.min, tzinfo=VIETNAM_TZ)
    end_dt = datetime.combine(day_end + timedelta(days=1), time.min, tzinfo=VIETNAM_TZ)
    return int(start_dt.timestamp()), int(end_dt.timestamp())


def _iter_date_chunks(start: date, end: date, chunk_days: int = DEFAULT_CHUNK_DAYS):
    if start > end:
        raise ValueError("start date must not be after end date")

    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def _slice_by_date(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if frame.empty:
        return _empty_frame()

    start_ts = pd.Timestamp(datetime.combine(start, time.min))
    end_ts = pd.Timestamp(datetime.combine(end, time.max))
    sliced = frame[(frame["Datetime"] >= start_ts) & (frame["Datetime"] <= end_ts)]
    return sliced.reset_index(drop=True)


def fetch_dnse_bars(
    market: str,
    symbol: str,
    start: date,
    end: date,
    *,
    resolution: int = 30,
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    retries: int = 3,
    timeout: int = DEFAULT_TIMEOUT,
    pause_seconds: float = 0.25,
) -> pd.DataFrame:
    """Fetch OHLCV bars from DNSE and return them as a normalized DataFrame."""
    frames: list[pd.DataFrame] = []

    for chunk_start, chunk_end in _iter_date_chunks(start, end, chunk_days):
        from_epoch, to_epoch = _epoch_bounds(chunk_start, chunk_end)
        payload = _request_payload(
            market,
            symbol,
            resolution,
            from_epoch,
            to_epoch,
            retries=retries,
            timeout=timeout,
            pause_seconds=pause_seconds,
        )
        frame = payload_to_frame(payload)
        if not frame.empty:
            frames.append(frame)
        if chunk_end < end and pause_seconds > 0:
            time_module.sleep(pause_seconds)

    if not frames:
        return _empty_frame()

    combined = normalize_bars(pd.concat(frames, ignore_index=True))
    return _slice_by_date(combined, start, end)


def cache_path(
    market: str,
    symbol: str,
    resolution: int = 30,
    cache_dir: Path | str | None = None,
) -> Path:
    root = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    safe_symbol = str(symbol).lower().replace("/", "_")
    return root / f"{market.lower()}_{safe_symbol}_{int(resolution)}m.parquet"


def load_cached_bars(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return _empty_frame()

    frame = pd.read_parquet(path)
    return normalize_bars(frame)


def save_cached_bars(frame: pd.DataFrame, path: Path | str) -> pd.DataFrame:
    normalized = normalize_bars(frame)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_parquet(path, index=False)
    return normalized


def _coverage_intervals(cached: pd.DataFrame, start: date, end: date) -> list[tuple[date, date]]:
    if cached.empty:
        return [(start, end)]

    first = cached["Datetime"].min().date()
    last = cached["Datetime"].max().date()
    intervals: list[tuple[date, date]] = []

    if start < first - timedelta(days=CACHE_COVERAGE_TOLERANCE_DAYS):
        intervals.append((start, min(end, first - timedelta(days=1))))

    if end > last + timedelta(days=CACHE_COVERAGE_TOLERANCE_DAYS):
        intervals.append((max(start, last + timedelta(days=1)), end))

    return [
        (interval_start, interval_end)
        for interval_start, interval_end in intervals
        if interval_start <= interval_end
    ]


def load_or_fetch_dnse_bars(
    market: str,
    symbol: str,
    start: date,
    end: date,
    *,
    resolution: int = 30,
    cache_dir: Path | str | None = None,
    force_refresh: bool = False,
    allow_fetch: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load DNSE bars from parquet cache, fetching missing data when allowed."""
    if start > end:
        raise ValueError("start date must not be after end date")

    path = cache_path(market, symbol, resolution, cache_dir)
    cached = load_cached_bars(path) if path.exists() else _empty_frame()

    if not allow_fetch:
        sliced = _slice_by_date(cached, start, end)
        if sliced.empty:
            raise DnseDataError(
                f"No cached DNSE bars for {market}/{symbol} between {start} and {end}. "
                "Run scripts/fetch_dnse_candles.py first."
            )
        return sliced, {
            "source": "dnse-cache",
            "market": market,
            "symbol": symbol,
            "resolution_minutes": resolution,
            "cache_path": str(path),
            "cache_rows": int(len(cached)),
            "returned_rows": int(len(sliced)),
            "fetched": False,
            "observed_start": sliced["Datetime"].min().isoformat(),
            "observed_end": sliced["Datetime"].max().isoformat(),
        }

    intervals = [(start, end)] if force_refresh or cached.empty else _coverage_intervals(cached, start, end)
    fetched_frames: list[pd.DataFrame] = []

    for interval_start, interval_end in intervals:
        fetched = fetch_dnse_bars(
            market,
            symbol,
            interval_start,
            interval_end,
            resolution=resolution,
        )
        if not fetched.empty:
            fetched_frames.append(fetched)

    parts = ([cached] if not cached.empty else []) + fetched_frames

    if not parts:
        raise DnseDataError(
            f"No DNSE bars available for {market}/{symbol} between {start} and {end}."
        )

    combined = normalize_bars(pd.concat(parts, ignore_index=True))
    if fetched_frames or force_refresh:
        save_cached_bars(combined, path)

    sliced = _slice_by_date(combined, start, end)
    if sliced.empty:
        raise DnseDataError(
            f"DNSE returned no bars for {market}/{symbol} between {start} and {end}."
        )

    meta = {
        "source": "dnse:https://api.dnse.com.vn/chart-api/v2/ohlcs",
        "market": market,
        "symbol": symbol,
        "resolution_minutes": resolution,
        "cache_path": str(path),
        "cache_rows": int(len(combined)),
        "returned_rows": int(len(sliced)),
        "fetched": bool(fetched_frames),
        "observed_start": sliced["Datetime"].min().isoformat(),
        "observed_end": sliced["Datetime"].max().isoformat(),
    }
    return sliced, meta


class DnseCandleSource:
    """Convenience source mirroring the PostgresResearchSource bar interface."""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        resolution: int = 30,
        *,
        force_refresh: bool = False,
        allow_fetch: bool = True,
    ) -> None:
        self.cache_dir = cache_dir
        self.resolution = resolution
        self.force_refresh = force_refresh
        self.allow_fetch = allow_fetch

    def load_front_month_bars(self, start: date, end: date) -> pd.DataFrame:
        bars, _ = load_or_fetch_dnse_bars(
            "derivative",
            "VN30F1M",
            start,
            end,
            resolution=self.resolution,
            cache_dir=self.cache_dir,
            force_refresh=self.force_refresh,
            allow_fetch=self.allow_fetch,
        )
        if "Contract" not in bars.columns:
            bars = bars.assign(Contract="VN30F1M")
        return bars

    def load_index_bars(self, start: date, end: date) -> pd.DataFrame:
        bars, _ = load_or_fetch_dnse_bars(
            "index",
            "VN30",
            start,
            end,
            resolution=self.resolution,
            cache_dir=self.cache_dir,
            force_refresh=self.force_refresh,
            allow_fetch=self.allow_fetch,
        )
        return bars

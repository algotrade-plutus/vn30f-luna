"""DNSE minute bars for the lab: 1-minute base, 5-minute fallback, signal-bar aggregation.

The research base is DNSE's 1-minute VN30F1M and VN30 bars (``config/research.toml``).
DNSE serves no 1-minute futures bars for some sessions, most of 2023-03-22 to
2023-09-21; those sessions take DNSE's 5-minute bars, which equal the
1-minute bars aggregated wherever both exist.  A session missing at every
resolution stays missing.

Signal bars are aggregated from the base with the conventions of the two
sleeve families:

- 10-minute (Calendar MTW, from calendar-mtw-vn30f): the 11:30 and 14:30 stub
  prints merge into the 11:20 and 14:20 bars; the 14:45 ATC print is its own
  bar, labelled 14:45.
- 30-minute (Basis, Momentum): each print goes to the start of its 30-minute
  bucket, so the 11:30 stub is its own bar and the 14:30 bar holds the 14:30
  stub and the ATC print.  Index bars labelled 09:15 fall into 09:00.
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pandas as pd

from src.adapters.data.dnse_candle_source import (
    add_front_month_contract,
    cache_path,
    load_cached_bars,
)

FUTURES = ("derivative", "VN30F1M")
INDEX = ("index", "VN30")
BASE_MINUTES = 1
FALLBACK_MINUTES = 5

_MORNING = (time(9, 0), time(11, 30))
_AFTERNOON = (time(13, 0), time(14, 30))
_ATC = time(14, 45)
_STUB_TO_10M = {time(11, 30): time(11, 20), time(14, 30): time(14, 20)}
_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _cached(series: tuple[str, str], minutes: int, cache_dir: Path | str | None) -> pd.DataFrame:
    path = cache_path(*series, minutes, cache_dir)
    bars = load_cached_bars(path)
    if bars.empty:
        raise FileNotFoundError(
            f"No cached DNSE {minutes}m bars at {path}. "
            f"Run scripts/fetch_dnse_candles.py --resolution {minutes} first."
        )
    return bars


def load_futures_minutes(cache_dir: Path | str | None = None) -> pd.DataFrame:
    """VN30F1M minute bars with ``Contract`` and the ``Resolution`` each session came from."""
    base = _cached(FUTURES, BASE_MINUTES, cache_dir).assign(Resolution=BASE_MINUTES)
    fallback = _cached(FUTURES, FALLBACK_MINUTES, cache_dir)
    covered = set(base["Datetime"].dt.date)
    filler = fallback[~fallback["Datetime"].dt.date.isin(covered)].assign(Resolution=FALLBACK_MINUTES)
    bars = pd.concat([base, filler], ignore_index=True).sort_values("Datetime", kind="stable")
    return add_front_month_contract(bars.reset_index(drop=True))


def load_index_minutes(cache_dir: Path | str | None = None) -> pd.DataFrame:
    """VN30 1-minute bars. DNSE's 5-minute index bars cover no session the 1-minute ones miss."""
    return _cached(INDEX, BASE_MINUTES, cache_dir).assign(Resolution=BASE_MINUTES)


def _aggregate(bars: pd.DataFrame, labels: pd.Series) -> pd.DataFrame:
    keep = labels.notna()
    grouped = bars.loc[keep].assign(Datetime=labels[keep]).groupby("Datetime", sort=True)
    out = grouped.agg(_AGG)
    if "Contract" in bars.columns:
        out["Contract"] = grouped["Contract"].first()
    return out.reset_index()


def _label_10m(stamp: pd.Timestamp) -> pd.Timestamp | None:
    tod = stamp.time()
    if tod == _ATC:
        return stamp
    if tod in _STUB_TO_10M:
        return pd.Timestamp.combine(stamp.date(), _STUB_TO_10M[tod])
    if _MORNING[0] <= tod < _MORNING[1] or _AFTERNOON[0] <= tod < _AFTERNOON[1]:
        return stamp.floor("10min")
    return None


def bars_10m(minutes: pd.DataFrame) -> pd.DataFrame:
    """10-minute bars in the calendar-mtw-vn30f convention, ATC bar included at 14:45."""
    return _aggregate(minutes, minutes["Datetime"].map(_label_10m))


def bars_30m(minutes: pd.DataFrame) -> pd.DataFrame:
    """30-minute bars on Calibrum's clock: 09:00 ... 14:00, the 11:30 stub, and 14:30 with the ATC."""
    return _aggregate(minutes, minutes["Datetime"].dt.floor("30min"))

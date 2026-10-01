#!/usr/bin/env python3
"""Step 2: query, validate, and fingerprint research bars from algotradeDB."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys

import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from src.adapters.data import PostgresResearchSource
from src.domain.strategy.calendar_rules import is_trading_day
from src.infrastructure.reproducibility import emit_plutus_results

MANIFEST_PATH = WORKSPACE / "data" / "dataset_manifest.json"
_CONTRACT = re.compile(r"^VN30F\d{4}$")


def _validate(frame: pd.DataFrame, *, needs_contract: bool) -> pd.DataFrame:
    frame = frame.copy()
    required = {"Datetime", "Open", "High", "Low", "Close", "Volume"}
    if needs_contract:
        required.update({"Contract", "Reference", "Ceiling", "Floor"})
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Database result is missing columns {missing}")
    frame["Datetime"] = pd.to_datetime(frame["Datetime"])
    if frame.empty:
        raise ValueError("Database query returned no research bars")
    if not frame["Datetime"].is_monotonic_increasing:
        raise ValueError("Database bars are not monotonic")
    if frame["Datetime"].duplicated().any():
        raise ValueError("Database bars contain duplicate timestamps")
    invalid_ohlc = (
        (frame["Low"] > frame["High"])
        | (frame["Open"] < frame["Low"])
        | (frame["Open"] > frame["High"])
        | (frame["Close"] < frame["Low"])
        | (frame["Close"] > frame["High"])
    )
    if invalid_ohlc.any():
        raise ValueError(f"Database bars contain {int(invalid_ohlc.sum())} invalid OHLC rows")
    if frame[["Open", "High", "Low", "Close", "Volume"]].isna().any().any():
        raise ValueError("Database bars contain null OHLCV fields")
    if (frame["Volume"] < 0).any():
        raise ValueError("Database bars contain negative volume")
    if needs_contract:
        if not frame["Contract"].astype(str).map(_CONTRACT.fullmatch).all():
            raise ValueError("Database bars contain an invalid VN30F contract code")
    return frame


def _canonical_sha256(frame: pd.DataFrame) -> str:
    """Hash every returned value in stable column and row order."""

    digest = hashlib.sha256()
    columns = sorted(frame.columns)
    digest.update(("|".join(columns) + "\n").encode())
    for row in frame.sort_values("Datetime")[columns].itertuples(index=False, name=None):
        values = [item.isoformat() if hasattr(item, "isoformat") else str(item) for item in row]
        digest.update(("|".join(values) + "\n").encode())
    return digest.hexdigest()


def _date_diagnostics(
    frame: pd.DataFrame, *, requested_start: date | None = None
) -> dict:
    days = frozenset(frame["Datetime"].dt.date)
    first, last = min(days), max(days)
    expected: set[date] = set()
    cursor = requested_start or first
    while cursor <= last:
        if is_trading_day(cursor):
            expected.add(cursor)
        cursor += timedelta(days=1)
    last_bar = frame.groupby(frame["Datetime"].dt.date)["Datetime"].max()
    incomplete = [
        day.isoformat()
        for day, timestamp in last_bar.items()
        if timestamp.time().isoformat() != "14:30:00"
    ]
    return {
        "requested_start": (requested_start or first).isoformat(),
        "observed_start": first.isoformat(),
        "observed_sessions": len(days),
        "missing_expected_session_dates": sorted(day.isoformat() for day in expected - days),
        "incomplete_session_dates": incomplete,
    }


def validate_and_fingerprint() -> dict:
    source = PostgresResearchSource()
    try:
        futures = _validate(
            source.load_front_month_bars(date(2021, 1, 15), date(2024, 12, 19)),
            needs_contract=True,
        )
        index = _validate(
            source.load_index_bars(date(2021, 1, 15), date(2024, 12, 19)),
            needs_contract=False,
        )
    finally:
        source.pool.close()

    partitions = {
        "in_sample": (date(2021, 1, 15), date(2022, 12, 30)),
        "out_of_sample": (date(2023, 1, 1), date(2024, 12, 19)),
    }
    partition_rows = {}
    for name, (start, end) in partitions.items():
        part = futures[
            (futures["Datetime"].dt.date >= start)
            & (futures["Datetime"].dt.date <= end)
        ]
        partition_rows[name] = {
            "bars": len(part),
            "start": part["Datetime"].min().isoformat(),
            "end": part["Datetime"].max().isoformat(),
            "sha256": _canonical_sha256(part),
            "contracts": sorted(part["Contract"].astype(str).unique()),
        }

    payload = {
        "schema_version": "2.0",
        "source": {
            "kind": "postgresql",
            "database": "algotradeDB",
            "tables": [
                "quote.matched",
                "quote.matchedvolume",
                "quote.futurecontractcode",
                "quote.reference",
                "quote.ceil",
                "quote.floor",
            ],
            "credentials": "environment only; never serialized",
        },
        "query_contract": {
            "symbol": "VN30F1M resolved to dated real contracts",
            "timeframe": "30m",
            "opening_auction": "08:45-08:59:59 included in the 09:00 bar",
            "bounds": "inclusive and index-bounded on every queried table",
        },
        "datasets": {
            "futures": {
                "rows": len(futures),
                "sha256": _canonical_sha256(futures),
                "start": futures["Datetime"].min().isoformat(),
                "end": futures["Datetime"].max().isoformat(),
                "bars_missing_any_published_band_field": int(
                    futures[["Reference", "Ceiling", "Floor"]].isna().any(axis=1).sum()
                ),
                **_date_diagnostics(futures, requested_start=date(2021, 1, 15)),
            },
            "vn30_index": {
                "rows": len(index),
                "sha256": _canonical_sha256(index),
                "start": index["Datetime"].min().isoformat(),
                "end": index["Datetime"].max().isoformat(),
                **_date_diagnostics(index, requested_start=date(2021, 1, 15)),
            },
        },
        "partitions": partition_rows,
        "known_limitations": [
            "The database snapshot has OHLCV and published bands but no historical book depth in this runner.",
            "Soft no-impact fills remain a modelling assumption and are labelled in every report.",
            "Missing sessions/closing bars are enumerated and never imputed.",
        ],
    }
    MANIFEST_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    emit_plutus_results(
        WORKSPACE,
        "data_preparation",
        {
            "futures_bars": (len(futures), "count"),
            "index_bars": (len(index), "count"),
        },
        artifacts=[
            {"name": "dataset_manifest", "path": "data/dataset_manifest.json", "kind": "json"}
        ],
        metadata={"source": "postgresql:algotradeDB"},
    )
    print(f"Validated {len(futures):,} futures bars and {len(index):,} index bars from PostgreSQL")
    print(f"Manifest: {MANIFEST_PATH}")
    return payload


if __name__ == "__main__":
    validate_and_fingerprint()

"""Derive a diagnostic ledger from the executed position stream."""
from __future__ import annotations

import pandas as pd

from .config import BacktestConfig


TRADE_COLUMNS = (
    "EntryDatetime",
    "ExitDatetime",
    "Side",
    "GrossPoints",
    "FeePoints",
    "NetPoints",
    "BarsHeld",
)


def derive_trade_ledger(
    accounting: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    executed = accounting.ExecutedPosition
    segment_id = executed.ne(executed.shift()).cumsum()
    active = accounting[executed.ne(0.0)].copy()
    if active.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    active["Segment"] = segment_id.loc[active.index]
    ledger = (
        active.groupby("Segment", sort=True)
        .agg(
            EntryDatetime=("Datetime", "first"),
            ExitDatetime=("Datetime", "last"),
            Side=("ExecutedPosition", "first"),
            GrossPoints=("GrossGain", "sum"),
            BarsHeld=("GrossGain", "size"),
        )
        .reset_index(drop=True)
    )
    # Every contiguous executed segment represents one trading unit.
    # A complete discrete round trip pays half the fee on entry and half on exit.
    ledger["FeePoints"] = ledger.Side.abs() * config.round_trip_fee_points
    ledger["NetPoints"] = ledger.GrossPoints - ledger.FeePoints
    return ledger.loc[:, TRADE_COLUMNS]


__all__ = ["TRADE_COLUMNS", "derive_trade_ledger"]

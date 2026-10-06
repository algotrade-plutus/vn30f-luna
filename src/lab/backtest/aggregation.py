"""Period aggregation shared by metrics and reports."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


AGGREGATE_COLUMNS = (
    "GrossGain",
    "NetGain",
    "GrossBarReturn",
    "NetBarReturn",
)


@dataclass(frozen=True)
class PeriodAggregates:
    daily: pd.DataFrame
    weekly: pd.DataFrame
    monthly: pd.DataFrame


def build_period_aggregates(accounting: pd.DataFrame) -> PeriodAggregates:
    indexed = accounting.set_index("Datetime")
    daily = accounting.groupby("SessionDate", sort=True)[list(AGGREGATE_COLUMNS)].sum()
    weekly = indexed.loc[:, AGGREGATE_COLUMNS].resample("W").sum()
    monthly = indexed.loc[:, AGGREGATE_COLUMNS].resample("ME").sum()
    return PeriodAggregates(daily=daily, weekly=weekly, monthly=monthly)


def nonzero_hit_rate(values: pd.Series) -> float:
    nonzero = values[values.ne(0.0)]
    return float(nonzero.gt(0.0).mean()) if len(nonzero) else float("nan")


__all__ = ["PeriodAggregates", "build_period_aggregates", "nonzero_hit_rate"]

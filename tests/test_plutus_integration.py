"""Regression tests for the causal Plutus research boundary."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from plutus.market.protocol import BandSource, Resolution
from plutus.market.adapters.depth import (
    DepthBook,
    DepthSide,
    SideAvailability,
    Truncation,
)
from plutus.core.order import Side

from src.adapters.backtesting import PlutusResearchRunner
from src.adapters.data import PlutusBarSource, PostgresResearchSource
from src.domain.strategy.calendar_rules import is_expiry_thursday


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = pd.to_datetime(
        [
            "2024-01-02 09:00:00",
            "2024-01-02 09:30:00",
            "2024-01-02 14:30:00",
            "2024-01-03 09:00:00",
            "2024-01-03 09:30:00",
            "2024-01-03 14:30:00",
        ]
    )
    futures = pd.DataFrame(
        {
            "Datetime": timestamps,
            "Open": [1130, 1132, 1135, 1136, 1138, 1140],
            "High": [1133, 1136, 1137, 1139, 1141, 1142],
            "Low": [1129, 1131, 1134, 1135, 1137, 1139],
            "Close": [1132, 1135, 1136, 1138, 1140, 1141],
            "Volume": [1000] * 6,
            "Contract": ["VN30F2401"] * 6,
            "Reference": [Decimal("1130")] * 6,
            "Ceiling": [Decimal("1209.1")] * 6,
            "Floor": [Decimal("1050.9")] * 6,
        }
    )
    index = futures.drop(
        columns=["Contract", "Reference", "Ceiling", "Floor"]
    ).copy()
    return futures, index


def test_left_labelled_bar_is_invisible_until_completion() -> None:
    futures, index = _frames()
    source = PlutusBarSource(futures, index)
    row = source.replay_bars(date(2024, 1, 2), date(2024, 1, 2))[0]

    assert source.state_at(row.contract, row.start) is None
    state = source.state_at(row.contract, row.end)
    assert state is not None
    assert state.last == row.bar.close
    assert state.band_source is BandSource.PUBLISHED
    interval = source.interval(
        row.contract, row.end, row.end, resolution=Resolution.TICK
    )
    assert interval is not None
    assert interval.start == row.start
    assert interval.end == row.end


def test_expiry_moves_before_exchange_holiday() -> None:
    assert is_expiry_thursday(date(2024, 4, 17))
    assert not is_expiry_thursday(date(2024, 4, 18))
    assert is_expiry_thursday(date(2026, 2, 13))
    assert not is_expiry_thursday(date(2026, 2, 19))


def test_postgres_research_query_is_bounded_and_keeps_published_bands() -> None:
    class FakePool:
        def __init__(self) -> None:
            self.sql = ""
            self.params = ()

        def execute_query(self, sql, params):
            self.sql = sql
            self.params = params
            return [
                (
                    datetime(2024, 1, 2, 9, 0),
                    Decimal("1130"),
                    Decimal("1133"),
                    Decimal("1129"),
                    Decimal("1132"),
                    1000,
                    "VN30F2401",
                    Decimal("1130"),
                    Decimal("1209.1"),
                    Decimal("1050.9"),
                )
            ]

    pool = FakePool()
    frame = PostgresResearchSource(pool).load_front_month_bars(
        date(2024, 1, 2), date(2024, 1, 2)
    )

    assert "m.datetime >= %s AND m.datetime <= %s" in pool.sql
    assert "v.datetime >= %s AND v.datetime <= %s" in pool.sql
    assert "f.datetime >= %s AND f.datetime <= %s" in pool.sql
    assert len(pool.params) == 14
    assert frame.loc[0, "Contract"] == "VN30F2401"
    assert frame.loc[0, "Reference"] == Decimal("1130")


def test_short_real_plutus_run_has_fills_and_engine_evidence() -> None:
    futures, index = _frames()
    source = PlutusBarSource(futures, index)
    result = PlutusResearchRunner(source).run(
        date(2024, 1, 2), date(2024, 1, 3), sample="in_sample"
    )

    assert result.summary["engine"] == "plutus.market.session.ExchangeSession"
    assert result.summary["fills"] > 0
    assert result.summary["exchange_rejects"] == 0
    assert result.summary["margin_calls_90"] == 0
    assert result.ignorance["indeterminate"] == 0
    assert result.provenance["fill_policy_kind"] == "soft(max_participation=0.10)"
    assert result.fills[0]["timestamp"] > datetime(2024, 1, 2, 9, 0).isoformat()


def test_book_runner_does_not_stack_orders_while_a_limit_is_live() -> None:
    futures, index = _frames()

    class AbsentBook:
        def book_at(self, ticker, ts, *, max_age: timedelta | None = None):
            return DepthBook(
                ticker=ticker,
                ts=ts,
                bid=DepthSide(
                    Side.BUY,
                    SideAvailability.ABSENT,
                    truncation=Truncation.NO_OBSERVATION,
                    truncated_at_depth=1,
                    ts=ts,
                ),
                ask=DepthSide(
                    Side.SELL,
                    SideAvailability.ABSENT,
                    truncation=Truncation.NO_OBSERVATION,
                    truncated_at_depth=1,
                    ts=ts,
                ),
                table_prefix="test",
            )

    source = PlutusBarSource(
        futures,
        index,
        book_provider=AbsentBook(),
    )
    result = PlutusResearchRunner(
        source,
        execution_model="book_walk",
        book_queue="optimistic",
    ).run(
        date(2024, 1, 2),
        date(2024, 1, 2),
        sample="out_of_sample",
        target_by_start={datetime(2024, 1, 2, 9, 30): 1},
        signal_name="no_duplicate_order_regression",
    )

    assert result.summary["orders"] == 1
    assert result.summary["unfilled_orders"] == 1

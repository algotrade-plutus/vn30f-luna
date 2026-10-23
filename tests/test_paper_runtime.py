from __future__ import annotations

import pandas as pd

from papertrade.calibrum.execution import Account, Order, Quote, phase, plan
from papertrade.calibrum.feed import COLUMNS, MinuteBook

QUOTE = Quote(bid=1890.6, ask=1890.8, ceiling=2020.0, floor=1760.0)
CONTINUOUS = pd.Timestamp("2026-10-22 10:15:03")
AUCTION = pd.Timestamp("2026-10-22 14:31:02")


def bars(*rows: tuple[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [(pd.Timestamp(stamp), close, close, close, close, 10) for stamp, close in rows], columns=COLUMNS
    )


def test_a_minute_is_confirmed_by_two_agreeing_reads_and_never_rolls_back() -> None:
    book = MinuteBook()
    now = pd.Timestamp("2026-10-22 10:52:02")
    first = bars(("2026-10-22 10:50", 1.0), ("2026-10-22 10:51", 2.0))

    assert book.merge(first, now) == []
    assert book.merge(first, now) == [pd.Timestamp("2026-10-22 10:50"), pd.Timestamp("2026-10-22 10:51")]
    assert book.merge(bars(("2026-10-22 10:50", 1.0)), now) == []  # an older cache
    assert book.stale_reads == 1

    later = pd.Timestamp("2026-10-22 10:53:02")
    revised = bars(("2026-10-22 10:51", 2.5), ("2026-10-22 10:52", 3.0))
    book.merge(revised, later)
    assert book.merge(revised, later) == [pd.Timestamp("2026-10-22 10:52")]
    assert book.revisions >= 1
    assert book.bars["Close"].tolist() == [1.0, 2.0, 3.0]


def test_a_minute_still_running_is_never_taken() -> None:
    book = MinuteBook()
    now = pd.Timestamp("2026-10-22 10:51:30")
    read = bars(("2026-10-22 10:50", 1.0), ("2026-10-22 10:51", 2.0))
    book.merge(read, now)

    assert book.merge(read, now) == [pd.Timestamp("2026-10-22 10:50")]


def test_order_windows() -> None:
    assert phase(CONTINUOUS) == "continuous"
    assert phase(pd.Timestamp("2026-10-22 12:00")) == "closed"
    assert phase(AUCTION) == "auction"
    assert phase(pd.Timestamp("2026-10-22 14:44:45")) == "closed"
    assert phase(pd.Timestamp("2026-10-24 10:00")) == "closed"  # Saturday


def test_open_is_capped_by_what_the_broker_allows_and_priced_through_the_book() -> None:
    flat = Account(position=0, remain_cash=549e6, working_orders=0)

    assert plan(1, 10, flat, QUOTE, CONTINUOUS, lambda side, price: 99) == Order("BUY", 10, 1891.1, "open")
    assert plan(-1, 10, flat, QUOTE, CONTINUOUS, lambda side, price: 8) == Order("SELL", 8, 1890.3, "open")
    assert plan(1, 10, flat, QUOTE, CONTINUOUS, lambda side, price: 0) is None


def test_closing_auction_uses_the_band_edge() -> None:
    flat = Account(position=0, remain_cash=549e6, working_orders=0)

    assert plan(1, 10, flat, QUOTE, AUCTION, lambda side, price: 99) == Order("BUY", 10, 2020.0, "open")
    assert plan(0, 10, Account(10, 50e6, 0), QUOTE, AUCTION, lambda s, p: 0) == Order("SELL", 10, 1760.0, "close")


def test_reversal_closes_first_and_a_held_position_is_not_topped_up() -> None:
    allow = lambda side, price: 99  # noqa: E731

    assert plan(-1, 10, Account(10, 50e6, 0), QUOTE, CONTINUOUS, allow) == Order("SELL", 10, 1890.3, "close")
    assert plan(1, 10, Account(8, 50e6, 0), QUOTE, CONTINUOUS, allow) is None
    assert plan(1, 10, Account(10, 50e6, 1), QUOTE, CONTINUOUS, allow) is None  # working order: wait


def test_margin_deficit_cuts_just_enough_contracts() -> None:
    # One contract at 1890.7 holds about 47.3 million VND of margin.
    short_by_52m = Account(position=10, remain_cash=-51.6e6, working_orders=0)

    assert plan(1, 10, short_by_52m, QUOTE, CONTINUOUS, lambda s, p: 0) == Order("SELL", 2, 1890.3, "margin")
    assert plan(-1, 10, Account(-10, -1e6, 0), QUOTE, CONTINUOUS, lambda s, p: 0) == Order("BUY", 1, 1891.1, "margin")

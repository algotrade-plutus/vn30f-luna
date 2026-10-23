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


class FakeBroker:
    symbol = "HNXDS:VN30F2611"

    def __init__(self) -> None:
        self.position, self.sent, self.cancelled = 0, [], []
        self.status = "New"

    def account(self) -> Account:
        return Account(self.position, 549e6, 0)

    def max_placeable(self, side: str, price: float) -> int:
        return 11

    def place(self, order: Order) -> str:
        self.sent.append(order)
        return f"id{len(self.sent)}"

    def wait(self, cl_ord_id: str, timeout: float) -> str:
        return self.status

    def cancel(self, cl_ord_id: str) -> tuple[bool, str]:
        self.cancelled.append(cl_ord_id)
        return False, "PendingCancel"

    def filled(self, cl_ord_id: str) -> int:
        return 0

    def reject_text(self, cl_ord_id: str) -> None:
        return None

    def logged_on(self) -> bool:
        return True


class FakeQuotes:
    def follow(self, symbol: str) -> None:
        pass

    def quote(self, symbol: str) -> Quote:
        return QUOTE


def test_runner_cancels_a_stale_order_then_waits_for_rest_before_sending_again(tmp_path, monkeypatch) -> None:
    import papertrade.calibrum.runner as runner_module
    from src.lab.calibrum_1m.live import Targets

    clock = [1000.0]
    monkeypatch.setattr(runner_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(runner_module.live, "load_params", lambda: None)
    broker = FakeBroker()
    runner = runner_module.Runner("active", 10, tmp_path, broker, FakeQuotes(), feed=type("F", (), {
        "age_seconds": lambda self, series, now: 4.0})())
    runner.targets = Targets(CONTINUOUS, CONTINUOUS, "VN30F2611", 1, 1, 0, 1)

    runner.trade(CONTINUOUS)
    assert broker.sent == [Order("BUY", 10, 1891.1, "open")]

    clock[0] += 9  # unfilled after 8 s: cancel, and the FIX state says nothing was filled
    runner.trade(CONTINUOUS)
    assert broker.cancelled == ["id1"]

    broker.position = 10  # REST shows the order did fill
    runner.trade(CONTINUOUS)  # still settling: no new order
    clock[0] += 4
    runner.trade(CONTINUOUS)
    assert len(broker.sent) == 1


def test_halt_file_stops_new_orders(tmp_path, monkeypatch) -> None:
    import papertrade.calibrum.runner as runner_module
    from src.lab.calibrum_1m.live import Targets

    monkeypatch.setattr(runner_module.live, "load_params", lambda: None)
    broker = FakeBroker()
    runner = runner_module.Runner("active", 10, tmp_path, broker, FakeQuotes(), feed=type("F", (), {
        "age_seconds": lambda self, series, now: 4.0})())
    runner.targets = Targets(CONTINUOUS, CONTINUOUS, "VN30F2611", 1, 1, 0, 1)
    (tmp_path / "HALT").touch()

    runner.trade(CONTINUOUS)
    assert broker.sent == []


def test_a_fill_stamped_before_the_ack_still_counts() -> None:
    from datetime import datetime, timezone

    from papertrade.calibrum.broker import _patch_fill_ordering

    class Manager:
        def __init__(self) -> None:
            self.status_map = {}

        def _update_status(self, cl_ord_id, status, at, **kwargs) -> None:  # the SDK's newest-wins rule
            prev = self.status_map.get(cl_ord_id)
            if prev is None or at > prev["time"]:
                self.status_map[cl_ord_id] = {"status": status, "time": at, **kwargs}

    raw = type("Raw", (), {})()
    raw.orders = Manager()
    _patch_fill_ordering(raw)
    ack = datetime(2026, 10, 23, 6, 34, 11, 44000, tzinfo=timezone.utc)
    fill = datetime(2026, 10, 23, 6, 34, 9, tzinfo=timezone.utc)  # the tick's whole second

    raw.orders._update_status("a", "New", ack)
    raw.orders._update_status("a", "Filled", fill, cum_qty=1.0)
    assert raw.orders.status_map["a"]["status"] == "Filled"
    assert raw.orders.status_map["a"]["cum_qty"] == 1.0
    raw.orders._update_status("a", "New", fill)  # an older, earlier-stage report does not win
    assert raw.orders.status_map["a"]["status"] == "Filled"


def test_targets_wait_for_vn30_to_reach_the_futures_minute(tmp_path, monkeypatch) -> None:
    import papertrade.calibrum.runner as runner_module

    clock = [1000.0]
    monkeypatch.setattr(runner_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(runner_module.live, "load_params", lambda: None)
    books = {runner_module.FUTURES: type("B", (), {"last": pd.Timestamp("2026-10-22 13:59")})(),
             runner_module.INDEX: type("B", (), {"last": pd.Timestamp("2026-10-22 13:58")})()}
    runner = runner_module.Runner("observe", 1, tmp_path, feed=type("F", (), {"books": books})())

    assert not runner.ready()  # VN30 13:59 not in yet
    books[runner_module.INDEX].last = pd.Timestamp("2026-10-22 13:59")
    assert runner.ready()
    runner.built_for = pd.Timestamp("2026-10-22 13:59")
    assert not runner.ready()  # already built for this minute

    books[runner_module.FUTURES].last = pd.Timestamp("2026-10-22 14:00")
    assert not runner.ready()
    clock[0] += 11  # VN30 still late after the grace period: build anyway
    assert runner.ready()

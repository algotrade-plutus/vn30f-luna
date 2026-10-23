"""The Calibrum paper-trading loop: DNSE minutes -> sleeve targets -> one order at a time.

Modes (CALIBRUM_MODE):
- observe: feed and targets only; no broker connection, no orders.
- active: also reads the account and trades, if PAPERBROKER_ALLOW_ORDERS=true.

A HALT file in the state directory stops new orders at once and survives restarts.
Every target and every order goes to ``journal.jsonl``; ``health.json`` holds
the current state. Neither ever holds a credential.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from papertrade.calibrum.execution import phase, plan  # noqa: E402
from papertrade.calibrum.feed import FUTURES, INDEX, DnseFeed  # noqa: E402
from src.lab.calibrum_1m import live  # noqa: E402

POLL_S = 2.0
FEED_STALE_S = 90.0
CANCEL_AFTER_S = 8.0
# After an order ends, REST may still show the old position for a few seconds (REBUILD_NOTES #22).
SETTLE_S = 3.0
ABANDON_CLOSED_S = 120.0


def now_ict() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").tz_localize(None)


class Journal:
    def __init__(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "journal.jsonl"
        self.health = state_dir / "health.json"

    def write(self, event: str, **fields) -> None:
        record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        print(json.dumps(record, default=str), flush=True)

    def status(self, **fields) -> None:
        temp = self.health.with_suffix(".tmp")
        temp.write_text(json.dumps({"at": now_ict().isoformat(), **fields}, default=str, indent=2), encoding="utf-8")
        temp.replace(self.health)


class Runner:
    def __init__(self, mode: str, qty: int, state_dir: Path, broker=None, quotes=None, feed=None) -> None:
        self.mode, self.qty, self.state_dir = mode, qty, state_dir
        self.broker, self.quotes = broker, quotes
        self.feed = feed or DnseFeed()
        self.params = live.load_params()
        self.journal = Journal(state_dir)
        self.targets: live.Targets | None = None
        self.pending: tuple[str, float] | None = None  # our working order: (cl_ord_id, sent at)
        self.settle_until = 0.0
        self.last_error: str | None = None

    @property
    def halted(self) -> bool:
        return (self.state_dir / "HALT").exists()

    def symbol(self) -> str | None:
        return None if self.targets is None else f"HNXDS:{self.targets.contract}"

    def step(self, now: pd.Timestamp) -> None:
        confirmed = self.feed.poll(now)
        if confirmed[FUTURES] or confirmed[INDEX] or self.targets is None:
            if not self.feed.books[FUTURES].bars.empty:
                self.targets = live.targets(self.feed.futures(), self.feed.index(), now, self.params)
                self.journal.write("target", **{k: v for k, v in asdict(self.targets).items()})
        if self.mode == "active" and self.targets is not None:
            self.trade(now)

    def trade(self, now: pd.Timestamp) -> None:
        broker, symbol = self.broker, self.symbol()
        if broker.symbol != symbol:
            self.journal.write("blocked", reason=f"runtime trades {broker.symbol}, targets are for {symbol}")
            return
        if self.halted:
            return
        age = self.feed.age_seconds(FUTURES, now)
        if phase(now) == "continuous" and (age is None or age > FEED_STALE_S):
            self.journal.write("blocked", reason=f"DNSE futures feed {age}s old")
            return

        if self.pending is not None:
            cl_ord_id, sent = self.pending
            status = broker.wait(cl_ord_id, timeout=0.5)
            waited = time.time() - sent
            if status in {"Filled", "Canceled", "Rejected", "Expired"}:
                self.journal.write("order_done", id=cl_ord_id, status=status, filled=broker.filled(cl_ord_id),
                                   text=broker.reject_text(cl_ord_id))
                self.pending = None
            elif phase(now) == "continuous" and waited > CANCEL_AFTER_S:
                terminal, status = broker.cancel(cl_ord_id)
                self.journal.write("cancel", id=cl_ord_id, terminal=terminal, status=status,
                                   filled=broker.filled(cl_ord_id))
                # Whatever the FIX state says, the next decision reads REST first (REBUILD_NOTES #22).
                self.pending = None
            elif phase(now) == "closed" and waited > ABANDON_CLOSED_S:
                self.journal.write("abandon", id=cl_ord_id, status=status)
                self.pending = None
            if self.pending is None:
                self.settle_until = time.time() + SETTLE_S
            return
        if time.time() < self.settle_until:
            return

        account = broker.account()
        self.quotes.follow(symbol)
        quote = self.quotes.quote(symbol)
        order = plan(self.targets.vote, self.qty, account, quote, now, broker.max_placeable)
        if order is None:
            return
        cl_ord_id = broker.place(order)
        self.pending = (cl_ord_id, time.time())
        self.journal.write("order", id=cl_ord_id, **asdict(order), position=account.position,
                           remain_cash=account.remain_cash, vote=self.targets.vote)

    def health(self, now: pd.Timestamp) -> None:
        self.journal.status(
            mode=self.mode,
            halted=self.halted,
            qty=self.qty,
            targets=None if self.targets is None else asdict(self.targets),
            pending=self.pending,
            feed_age_s={name: self.feed.age_seconds(series, now) for name, series in (("futures", FUTURES), ("index", INDEX))},
            stale_reads={series[1]: book.stale_reads for series, book in self.feed.books.items()},
            revisions={series[1]: book.revisions for series, book in self.feed.books.items()},
            fix_logged_on=None if self.broker is None else self.broker.logged_on(),
            last_error=self.last_error,
        )

    def run(self, until: pd.Timestamp | None = None) -> None:
        self.feed.bootstrap(now_ict())
        self.journal.write("start", mode=self.mode, qty=self.qty, futures_last=self.feed.books[FUTURES].last,
                           index_last=self.feed.books[INDEX].last)
        while until is None or now_ict() < until:
            now = now_ict()
            try:
                self.step(now)
                self.last_error = None
            except Exception as exc:  # keep running; the error is visible in health and the journal
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.journal.write("error", error=self.last_error)
            self.health(now)
            time.sleep(POLL_S)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("observe", "active"), default=os.getenv("CALIBRUM_MODE", "observe"))
    parser.add_argument("--qty", type=int, default=int(os.getenv("CALIBRUM_QTY", "10")))
    parser.add_argument("--state-dir", type=Path, default=Path(os.getenv("CALIBRUM_STATE_DIR", "runtime")))
    parser.add_argument("--until", help="stop at this exchange time, e.g. '2026-10-23 14:46'")
    args = parser.parse_args()
    if not 1 <= args.qty <= 10:
        parser.error("qty must be between 1 and 10")

    broker = quotes = None
    if args.mode == "active":
        from papertrade.calibrum.broker import Broker
        from papertrade.calibrum.quotes import KafkaQuotes
        from src.domain.strategy.calendar_rules import front_month_contract

        allow = os.getenv("PAPERBROKER_ALLOW_ORDERS", "false").lower() == "true"
        symbol = f"HNXDS:{front_month_contract(now_ict().date())}"
        broker = Broker.from_env(symbol, allow, args.state_dir)
        if not broker.connect():
            print("FIX logon failed", file=sys.stderr)
            return 3
        if broker.working_orders():
            print("refusing to start with working orders on the account", file=sys.stderr)
            return 2
        quotes = KafkaQuotes()
    runner = Runner(args.mode, args.qty, args.state_dir, broker, quotes)
    try:
        runner.run(pd.Timestamp(args.until) if args.until else None)
    finally:
        if quotes is not None:
            quotes.stop()
        if broker is not None:
            broker.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only dashboard: status, orders, realized value and the open position from the runner's files."""
from __future__ import annotations

import json
from datetime import datetime

from papertrade.calibrum.dashboard import ICT, notable, open_position, orders, read_journal, realized, state, status


def _journal(tmp_path, records):
    path = tmp_path / "journal.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _health(tmp_path, at, **fields):
    (tmp_path / "health.json").write_text(json.dumps({"at": at, "fix_logged_on": True, **fields}), encoding="utf-8")


RECORDS = [
    {"at": "2026-10-26T02:00:01+00:00", "event": "target", "vote": 1},
    {"at": "2026-10-26T02:01:01+00:00", "event": "target", "vote": 1},
    {"at": "2026-10-26T02:01:02+00:00", "event": "order", "id": "a", "side": "BUY", "qty": 10, "price": 1900.3,
     "reason": "open", "position": 0, "remain_cash": 550e6, "vote": 1},
    {"at": "2026-10-26T02:01:03+00:00", "event": "order_done", "id": "a", "status": "Filled", "filled": 10},
    {"at": "2026-10-26T03:00:01+00:00", "event": "target", "vote": 0},
    {"at": "2026-10-26T03:00:02+00:00", "event": "order", "id": "b", "side": "SELL", "qty": 10, "price": 1904.7,
     "reason": "close", "position": 10, "remain_cash": 80e6, "vote": 0},
    {"at": "2026-10-26T03:00:03+00:00", "event": "order_done", "id": "b", "status": "Filled", "filled": 10},
    {"at": "2026-10-26T04:00:02+00:00", "event": "order", "id": "c", "side": "SELL", "qty": 10, "price": 1902.7,
     "reason": "open", "position": 0, "remain_cash": 554e6, "vote": -1},
    {"at": "2026-10-26T04:00:03+00:00", "event": "order_done", "id": "c", "status": "Filled", "filled": 10},
]


def test_orders_join_sent_and_final_status(tmp_path):
    rows = orders(read_journal(_journal(tmp_path, RECORDS)))
    assert [(r["side"], r["status"], r["filled"]) for r in rows] == [("BUY", "Filled", 10), ("SELL", "Filled", 10), ("SELL", "Filled", 10)]
    assert rows[0]["at"].startswith("2026-10-26T09:01")  # shown in ICT


def test_realized_uses_cash_only_when_flat(tmp_path):
    points = realized(read_journal(_journal(tmp_path, RECORDS)))
    assert [p["nav_million"] for p in points] == [550.0, 554.0]  # the 80e6 order was sent while holding 10


def test_open_position_after_a_close_and_a_new_short(tmp_path):
    held = open_position(orders(read_journal(_journal(tmp_path, RECORDS))))
    assert held == {"contracts": -10, "entry_approx": 1903.0}  # SELL limit 1902.7 fills about 0.3 better


def test_targets_kept_only_when_the_vote_changes(tmp_path):
    events = [r["event"] for r in notable(read_journal(_journal(tmp_path, RECORDS)))]
    assert events.count("target") == 2


def test_status_flags_a_silent_runner_in_the_session(tmp_path):
    now = datetime(2026, 10, 27, 10, 0, tzinfo=ICT)
    assert status({"at": "2026-10-27T09:59:30", "fix_logged_on": True}, now)["level"] == "ok"
    assert status({"at": "2026-10-27T09:50:00", "fix_logged_on": True}, now)["level"] == "bad"
    assert status({"at": "2026-10-27T09:59:30", "halted": True}, now)["text"].startswith("HALT")
    assert status({"at": "2026-10-26T14:59:00", "fix_logged_on": True}, datetime(2026, 10, 26, 20, 0, tzinfo=ICT))["level"] == "idle"


def test_state_reads_the_state_directory(tmp_path):
    _journal(tmp_path, RECORDS)
    _health(tmp_path, "2026-10-26T11:00:00", position=-10, halted=False)
    snapshot = state(tmp_path, now=datetime(2026, 10, 26, 11, 0, 30, tzinfo=ICT))
    assert snapshot["status"]["level"] == "ok"
    assert snapshot["day"] == "2026-10-26" and len(snapshot["orders"]) == 3
    assert snapshot["realized_million"] == 4.0

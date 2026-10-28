"""Read-only dashboard: status, orders, the account curve and the open position from the runner's files."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from papertrade.calibrum.dashboard import (
    ICT,
    account_curve,
    comparison,
    fills,
    hold_curve,
    intraday,
    journal_lines,
    open_position,
    orders,
    performance,
    position_now,
    read_journal,
    realized,
    schedule,
    state,
    status,
)


def _journal(tmp_path, records):
    path = tmp_path / "journal.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


RECORDS = [
    {"at": "2026-10-26T02:00:01+00:00", "event": "target", "vote": 1, "calendar": 1, "basis": 0, "momentum": 0},
    {"at": "2026-10-26T02:01:01+00:00", "event": "target", "vote": 1, "calendar": 1, "basis": 0, "momentum": 0},
    {"at": "2026-10-26T02:01:02+00:00", "event": "order", "id": "a", "side": "BUY", "qty": 10, "price": 1900.3,
     "reason": "open", "position": 0, "remain_cash": 550e6, "vote": 1},
    {"at": "2026-10-26T02:01:03+00:00", "event": "order_done", "id": "a", "status": "Filled", "filled": 10},
    {"at": "2026-10-26T03:00:01+00:00", "event": "target", "vote": 0, "calendar": 0, "basis": 0, "momentum": 0},
    {"at": "2026-10-26T03:00:02+00:00", "event": "order", "id": "b", "side": "SELL", "qty": 10, "price": 1904.7,
     "reason": "close", "position": 10, "remain_cash": 80e6, "vote": 0},
    {"at": "2026-10-26T03:00:03+00:00", "event": "order_done", "id": "b", "status": "Filled", "filled": 10},
    {"at": "2026-10-26T03:01:05+00:00", "event": "index_late"},
    {"at": "2026-10-26T03:02:05+00:00", "event": "index_late"},
    {"at": "2026-10-26T04:00:02+00:00", "event": "order", "id": "c", "side": "SELL", "qty": 10, "price": 1902.7,
     "reason": "open", "position": 0, "remain_cash": 554e6, "vote": -1},
    {"at": "2026-10-26T04:00:03+00:00", "event": "order_done", "id": "c", "status": "Filled", "filled": 10},
]


def _fills(tmp_path, records=RECORDS):
    return fills(orders(read_journal(_journal(tmp_path, records))))


def test_orders_join_sent_and_final_status(tmp_path):
    rows = orders(read_journal(_journal(tmp_path, RECORDS)))
    assert [(r["side"], r["status"], r["filled"]) for r in rows] == [("BUY", "Filled", 10), ("SELL", "Filled", 10), ("SELL", "Filled", 10)]
    assert rows[0]["at"].startswith("2026-10-26T09:01")  # shown in ICT


def test_fills_estimate_the_price_and_the_position_after(tmp_path):
    rows = _fills(tmp_path)
    assert [(f["signed"], f["price"], f["position_after"]) for f in rows] == [(10, 1900.0, 10), (-10, 1905.0, 0), (-10, 1903.0, -10)]
    assert [p["nav"] for p in realized(rows)] == [550.0, 554.0]  # the 80e6 order was sent while holding 10


def test_open_position_restarts_when_the_broker_was_flat(tmp_path):
    stray = [{"at": "2026-10-25T02:00:00+00:00", "event": "order", "id": "x", "side": "BUY", "qty": 1, "price": 1880.3,
              "reason": "open", "position": 0, "remain_cash": 550e6, "vote": 1},
             {"at": "2026-10-25T02:00:01+00:00", "event": "order_done", "id": "x", "status": "Filled", "filled": 1}]
    assert open_position(_fills(tmp_path, stray + RECORDS)) == {"contracts": -10, "entry": 1903.0}


def test_account_curve_marks_between_flat_moments(tmp_path):
    minutes = pd.date_range("2026-10-26 09:01", "2026-10-26 11:05", freq="1min")
    futures = pd.Series(1900.0, index=minutes)
    futures[minutes >= "2026-10-26 09:30"] = 1904.0
    curve = account_curve(_fills(tmp_path), futures)
    assert round(curve.iloc[0], 6) == 550.0 - 0.2  # bought 10 at about 1900.0, fee 0.02 M a contract
    assert round(curve[pd.Timestamp("2026-10-26 09:45")], 6) == round(550.0 - 0.2 + 10 * 4.0 * 0.1, 6)
    assert round(curve[pd.Timestamp("2026-10-26 11:00")], 6) == round(554.0 - 0.2 - 10 * (1904.0 - 1903.0) * 0.1, 6)


def test_comparison_in_percent_of_the_starting_account():
    minutes = pd.date_range("2026-10-26 09:00", "2026-10-26 10:00", freq="1min")
    curve = pd.Series(500.0, index=minutes)
    curve.iloc[-1] = 505.0
    index = pd.Series(1900.0, index=minutes)
    index.iloc[-1] = 1919.0
    out = comparison(curve, curve - 10.0, index, nav=500.0, every="30min")
    assert out["bot"][-1] == 1.0 and out["hold"][-1] == -1.0 and out["index"][-1] == 1.0


def test_holding_pays_the_fee_and_rolls_on_the_adjusted_closes():
    minutes = pd.date_range("2026-11-19 14:00", periods=4, freq="1min")
    futures = pd.DataFrame({"close": [1900.0, 1904.0, 1890.0, 1892.0], "adjusted": [1900.0, 1904.0, 1904.0, 1906.0],
                            "contract": ["VN30F2611", "VN30F2611", "VN30F2612", "VN30F2612"]}, index=minutes)
    hold = hold_curve(futures, minutes[0], nav=500.0, qty=10)
    assert round(hold.iloc[0], 6) == 500.0 - 0.2  # entry fee, 10 contracts
    assert round(hold.iloc[1], 6) == round(500.0 - 0.2 + 10 * 4.0 * 0.1, 6)
    assert round(hold.iloc[3], 6) == round(500.0 - 0.6 + 10 * 6.0 * 0.1, 6)  # the roll pays both sides, its gap is not profit


def test_performance_counts_closed_trades_from_flat_to_flat(tmp_path):
    rows = _fills(tmp_path)
    curve = pd.Series([550.0, 560.0, 553.0, 556.0])
    out = performance(curve, realized(rows), rows)
    assert out["trades"] == 1 and out["won"] == 1  # 550 -> 554; the short is still open
    assert out["max_drawdown_pct"] == -1.25 and out["fees_million"] == 0.6


def test_position_now_open_profit_today_and_buffer():
    minutes = pd.date_range("2026-10-27 09:00", periods=3, freq="1min")
    close = pd.Series([1900.0, 1898.0, 1896.0], index=minutes)
    curve = pd.Series([600.0, 604.0, 606.0], index=[pd.Timestamp("2026-10-26 14:29"), *minutes[1:]])
    now = datetime(2026, 10, 27, 9, 3, tzinfo=ICT)
    out = position_now({"position": -10, "remain_cash_million": 75.0}, {"contracts": -10, "entry": 1903.0}, close, curve, now)
    assert out["open_points"] == 7.0 and out["open_million"] == 7.0  # short 10 from 1903 to 1896
    assert out["today_million"] == 6.0 and out["buffer_points"] == 75.0
    assert position_now({"position": 0, "remain_cash_million": 550.0}, None, close, curve, now)["buffer_points"] is None


def test_schedule_finds_the_expiry_and_the_next_calendar_legs():
    wednesday = schedule(datetime(2026, 10, 28, 11, 0, tzinfo=ICT))
    assert wednesday["contract"] == "VN30F2611" and wednesday["expiry"] == "2026-11-19"
    assert wednesday["sessions_left"] == 16
    assert wednesday["long_from"] == "2026-10-26T14:20+07:00" and wednesday["long_to"] == "2026-10-29T10:00+07:00"
    assert wednesday["long_now"] and wednesday["monday"] == "2026-11-02"
    friday = schedule(datetime(2026, 10, 30, 11, 0, tzinfo=ICT))
    assert friday["long_from"] == "2026-11-02T14:20+07:00" and not friday["long_now"]


def test_intraday_position_follows_the_fills(tmp_path):
    minutes = pd.date_range("2026-10-26 09:00", "2026-10-26 11:05", freq="1min")
    day = intraday("2026-10-26", "2026-10-26", _fills(tmp_path), pd.Series(1900.0, index=minutes))
    at = dict(zip(day["t"], day["position"]))
    assert at["2026-10-26 09:00"] == 0 and at["2026-10-26 09:30"] == 10
    assert at["2026-10-26 10:30"] == 0 and at["2026-10-26 11:00"] == -10
    assert [(f["t"], f["side"]) for f in day["fills"]] == [("2026-10-26 09:01", "BUY"), ("2026-10-26 10:00", "SELL"),
                                                            ("2026-10-26 11:00", "SELL")]


def test_intraday_spans_several_days_and_keeps_every_change(tmp_path):
    sessions = [pd.date_range(f"2026-10-{d} 09:00", f"2026-10-{d} 11:05", freq="1min") for d in (19, 20, 21, 22, 23, 26)]
    futures = pd.Series(1900.0, index=sessions[0].append(sessions[1:]))
    week = intraday("2026-10-19", "2026-10-26", _fills(tmp_path), futures)
    assert week["t"][0] == "2026-10-19 09:00" and week["t"][-1] == "2026-10-26 11:05"
    assert len({t[:10] for t in week["t"]}) == 6
    assert "2026-10-19 09:05" in week["t"] and "2026-10-19 09:02" not in week["t"]  # over 5 sessions: every 5 minutes
    at = dict(zip(week["t"], week["position"]))
    assert at["2026-10-26 09:01"] == 10 and at["2026-10-26 11:00"] == -10  # plus every minute the position changes


def test_journal_reads_as_sentences(tmp_path):
    lines = journal_lines(read_journal(_journal(tmp_path, RECORDS)))
    texts = [line["text"] for line in lines]
    assert texts.count("Vote now BUY (Calendar +1, Basis +0, Momentum +0)") == 1  # repeated targets dropped
    late = [line for line in lines if line["event"] == "index_late"]
    assert len(late) == 1 and late[0]["count"] == 2  # folded


def test_status_flags_a_silent_runner_in_the_session():
    now = datetime(2026, 10, 27, 10, 0, tzinfo=ICT)
    assert status({"at": "2026-10-27T09:59:30", "fix_logged_on": True}, now)["level"] == "ok"
    assert status({"at": "2026-10-27T09:50:00", "fix_logged_on": True}, now)["level"] == "bad"
    assert status({"at": "2026-10-27T09:59:30", "halted": True}, now)["text"].startswith("HALT")
    assert status({"at": "2026-10-26T14:59:00", "fix_logged_on": True}, datetime(2026, 10, 26, 20, 0, tzinfo=ICT))["level"] == "idle"
    late = {"at": "2026-10-27T09:59:30", "fix_logged_on": True, "feed_age_s": {"futures": 20, "index": 900}}
    assert status(late, now)["level"] == "warn"
    assert status(late | {"at": "2026-10-27T09:05:00"}, datetime(2026, 10, 27, 9, 5, 30, tzinfo=ICT))["level"] == "ok"


def test_state_without_prices(tmp_path):
    _journal(tmp_path, RECORDS)
    (tmp_path / "health.json").write_text(json.dumps({"at": "2026-10-26T11:00:00", "fix_logged_on": True}), encoding="utf-8")
    snapshot = state(tmp_path, now=datetime(2026, 10, 26, 11, 0, 30, tzinfo=ICT))
    assert snapshot["status"]["level"] == "ok" and snapshot["from"] == snapshot["to"] == "2026-10-26"
    assert len(snapshot["orders"]) == 3 and snapshot["realized_million"] == 4.0
    assert snapshot["charts"]["since"] is None  # the page still works without DNSE

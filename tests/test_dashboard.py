"""Read-only dashboard: status, orders, the account curve and the open position from the runner's files."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from papertrade.calibrum.dashboard import (
    ICT,
    account,
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
    record_start,
    sleeves,
    sleeve_changes,
    StateCache,
    state,
    status,
    STOP_POINTS,
    trades,
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
    out = performance(curve, trades(rows), rows)
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
    assert texts.count("Calendar +1, Basis +0, Momentum +0 → vote BUY") == 1  # repeated targets dropped
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
    assert len(snapshot["orders"]) == 3 and snapshot["account"]["closed"] == 4.0
    assert snapshot["charts"]["since"] is None  # the page still works without DNSE


def test_public_view_hides_order_ids_and_error_text(tmp_path):
    _journal(tmp_path, RECORDS + [{"at": "2026-10-26T03:00:00+00:00", "event": "error", "error": "host broker.internal refused"}])
    health = {"at": "2026-10-26T11:00:00", "fix_logged_on": True, "pending": ["a", 1.0], "last_error": "host broker.internal refused"}
    (tmp_path / "health.json").write_text(json.dumps(health), encoding="utf-8")
    now = datetime(2026, 10, 26, 11, 0, 30, tzinfo=ICT)
    private = json.dumps(state(tmp_path, now=now))
    public = json.dumps(state(tmp_path, now=now, public=True))
    assert "broker.internal" in private and "Order a:" in private
    assert "broker.internal" not in public and "Order a" not in public and '"a"' not in public
    assert json.loads(public)["account"]["closed"] == 4.0  # the numbers are the same


def test_state_cache_computes_once_per_range_and_ttl():
    calls, now = [], [0.0]
    cache = StateCache(lambda start, end: calls.append((start, end)) or b"x", ttl=15, now=lambda: now[0])
    cache.get(None, None), cache.get(None, None), cache.get("2026-10-26", None)
    assert calls == [(None, None), ("2026-10-26", None)]
    now[0] = 16
    cache.get(None, None)
    assert calls[-1] == (None, None) and len(calls) == 3 and list(cache.saved) == [(None, None)]


def test_trades_run_from_flat_to_flat(tmp_path):
    rows = trades(_fills(tmp_path))
    assert [(t["side"], t["qty"], t["entry"], t["exit"], t["points"]) for t in rows] == [
        (1, 10, 1900.0, 1905.0, 5.0), (-1, 10, 1903.0, None, None)]
    assert rows[0]["million"] == 4.0 and rows[0]["exact"]  # the broker's cash: 550 -> 554
    assert rows[1]["exit_at"] is None and rows[1]["million"] is None
    closed = trades(_fills(tmp_path)[:2])  # flat now, the cash not known: estimated
    assert closed[0]["million"] == round(10 * 5.0 * 0.1 - 0.4, 2) and not closed[0]["exact"]
    assert trades(_fills(tmp_path)[:2], flat_cash=554.5)[0]["million"] == 4.5


def test_the_results_start_at_the_first_runner_with_todays_contract_count(tmp_path):
    starts = [{"at": "2026-10-23T06:56:06+00:00", "event": "start", "qty": 1},
              {"at": "2026-10-23T07:05:09+00:00", "event": "start", "qty": 10},
              {"at": "2026-10-26T01:30:09+00:00", "event": "start", "qty": 10}]
    assert record_start(read_journal(_journal(tmp_path, starts))) == "2026-10-23T14:05:09+07:00"
    assert record_start([]) is None


def test_account_splits_profit_into_closed_and_open(tmp_path):
    rows = _fills(tmp_path)
    curve = pd.Series([550.0, 551.0], index=pd.date_range("2026-10-26 09:01", periods=2, freq="1min"))
    out = account(realized(rows), trades(rows), curve, {"position": -10})
    assert out == {"start": 550.0, "now": 551.0, "total": 1.0, "closed": 4.0, "open": -3.0}
    assert account(realized(rows), trades(rows), curve, {"position": 0, "remain_cash_million": 553.0})["now"] == 553.0


TARGETS = [
    {"at": "2026-10-28T07:00:05+00:00", "event": "target", "last_minute": "2026-10-28 13:59:00", "calendar": 1, "basis": 0, "momentum": 0, "vote": 1},
    {"at": "2026-10-28T07:30:05+00:00", "event": "target", "last_minute": "2026-10-28 14:28:00", "calendar": 1, "basis": 1, "momentum": 0, "vote": 1},
    {"at": "2026-10-29T03:00:05+00:00", "event": "target", "last_minute": "2026-10-29 09:59:00", "calendar": 0, "basis": 1, "momentum": 0, "vote": 1},
]


def test_sleeves_know_since_when_and_their_stop(tmp_path):
    records = read_journal(_journal(tmp_path, TARGETS))
    minutes = pd.date_range("2026-10-28 14:25", periods=5, freq="1min")
    close = pd.Series([1890.0, 1891.0, 1892.0, 1893.0, 1894.0], index=minutes)
    out = sleeves(records, close)
    assert out["basis"] == {"side": 1, "since": "2026-10-28 14:28:00", "entry": 1893.0, "stop": 1893.0 - 14.0}
    assert out["calendar"]["side"] == 0 and out["calendar"]["since"] == "2026-10-29 09:59:00"
    assert out["momentum"] == {"side": 0, "since": None, "entry": None, "stop": None}


def test_stops_match_the_sleeves():
    import inspect

    from src.lab.calibrum_1m import basis, momentum

    assert STOP_POINTS["basis"] == inspect.signature(basis.positions).parameters["stop_points"].default
    assert STOP_POINTS["momentum"] == inspect.signature(momentum.positions).parameters["stop_points"].default


def test_session_chart_carries_each_sleeve(tmp_path):
    records = read_journal(_journal(tmp_path, TARGETS))
    minutes = pd.date_range("2026-10-29 09:55", "2026-10-29 10:05", freq="1min")
    day = intraday("2026-10-29", "2026-10-29", [], pd.Series(1900.0, index=minutes), sleeve_changes(records))
    at = {t: (c, b) for t, c, b in zip(day["t"], day["sleeves"]["calendar"], day["sleeves"]["basis"])}
    assert at["2026-10-29 09:55"] == (1, 1) and at["2026-10-29 10:00"] == (0, 1)  # known at 10:00:05
    assert intraday("2026-10-29", "2026-10-29", [], pd.Series(1900.0, index=minutes))["sleeves"] is None


def test_journal_shows_sleeve_changes_and_quiets_the_daily_open(tmp_path):
    records = TARGETS + [
        {"at": "2026-10-29T06:00:02+00:00", "event": "blocked", "reason": "DNSE futures feed stale"},
        {"at": "2026-10-29T06:01:05+00:00", "event": "unblocked", "reason": "DNSE futures feed stale"},
        {"at": "2026-10-29T06:30:00+00:00", "event": "blocked", "reason": "DNSE futures feed stale"},
    ]
    lines = journal_lines(read_journal(_journal(tmp_path, records)))
    assert [line["event"] for line in lines] == ["target", "target", "target", "blocked", "blocked"]  # vote never changed
    assert lines[3]["level"] == "quiet" and lines[3]["until"].endswith("13:01:05+07:00")
    assert lines[4]["level"] == "warn"  # 13:30 is not the open
    late = [{"at": f"2026-10-29T02:0{m}:16+00:00", "event": "index_late"} for m in range(1, 4)]
    folded = journal_lines(read_journal(_journal(tmp_path, late)))
    assert len(folded) == 1 and folded[0]["level"] == "quiet" and folded[0]["count"] == 3

"""Read-only web dashboard for the Calibrum runner.

Serves one page and ``/api/state`` from the runner's state directory
(``health.json`` and ``journal.jsonl``) and DNSE's public 1-minute bars. It
holds no credentials and never talks to the broker. On the EC2 it listens on
127.0.0.1 only; open it from a laptop through an SSM port forward
(``make papertrade-dashboard``).

The account curve is exact whenever the bot was flat (its cash is then the
whole account) and marked with DNSE closes in between, from fills estimated at
the crossing limit minus 0.3 points and the platform's fee.

    python -m papertrade.calibrum.dashboard --state-dir /state --port 8080
"""
from __future__ import annotations

import argparse
import json
import threading
import time as clock
import tomllib
from datetime import datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import pandas as pd

from src.domain.strategy.calendar_rules import expiry_date, front_month_contract, is_trading_day, next_trading_day

ICT = timezone(timedelta(hours=7))
DAY_START, SESSION_OPEN, SESSION_CLOSE, DAY_END = time(8, 30), time(9, 0), time(14, 45), time(15, 0)
STALE_AFTER_S = 180  # health is rewritten every loop; older than this in a session means the runner is down
JOURNAL_TAIL = 20_000
POINT_MILLION = 0.1  # million VND per index point per contract
FEE_MILLION = 0.02  # platform fee per contract per side
CROSS = 0.3  # orders are limits this far through the book; fills come about this much better
PRICE_TTL_S = 60
DEFAULT_SESSIONS = 5  # the session chart opens on the last week
BASIS_WARMUP_SESSIONS = 8  # 60 thirty-minute bars on a new contract
LIVE_CONFIG = Path(__file__).resolve().parents[2] / "config" / "calibrum_live.toml"


def _ict(stamp: str) -> datetime:
    moment = datetime.fromisoformat(stamp)
    if moment.tzinfo is None:  # health and target clocks are naive ICT
        return moment.replace(tzinfo=ICT)
    return moment.astimezone(ICT)


def thresholds(path: Path = LIVE_CONFIG) -> dict:
    try:
        params = tomllib.loads(path.read_text(encoding="utf-8"))
        return {"z_entry": params["basis"]["z_entry"], "window": params["basis"]["window"],
                "theta": params["momentum"]["theta"]}
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return {"z_entry": None, "window": None, "theta": None}


# ----- journal ---------------------------------------------------------------------------------------------------

def read_journal(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines()[-JOURNAL_TAIL:]:
        try:
            record = json.loads(line)
            record["_at"] = _ict(record["at"])
        except (ValueError, KeyError):
            continue
        records.append(record)
    return records


def orders(journal: list[dict]) -> list[dict]:
    """One row per order: what was sent and how it ended."""
    rows: dict[str, dict] = {}
    for record in journal:
        event, key = record.get("event"), record.get("id")
        if event == "order":
            rows[key] = {
                "at": record["_at"].isoformat(timespec="seconds"),
                "side": record["side"], "qty": record["qty"], "price": record["price"], "reason": record["reason"],
                "position_before": record.get("position"), "remain_cash": record.get("remain_cash"),
                "status": "sent", "filled": 0,
            }
        elif event in ("order_done", "cancel", "abandon") and key in rows:
            rows[key]["status"] = record.get("status") or event
            if "filled" in record:
                rows[key]["filled"] = record["filled"]
    return list(rows.values())


def fills(order_rows: list[dict]) -> list[dict]:
    """Filled orders with the position after them (from the broker's position before) and an estimated price."""
    out = []
    for row in order_rows:
        filled = int(row["filled"] or 0)
        if not filled:
            continue
        sign = 1 if row["side"] == "BUY" else -1
        before = row["position_before"] if row["position_before"] is not None else 0
        flat_nav = row["remain_cash"] / 1e6 if before == 0 and row["remain_cash"] is not None else None
        out.append({"at": row["at"], "signed": sign * filled, "price": row["price"] - CROSS * sign,
                    "position_after": before + sign * filled, "flat_nav": flat_nav})
    return out


def open_position(fill_rows: list[dict]) -> dict | None:
    """Contracts held and their average estimated entry, counted from the last fill that opened from flat."""
    held, cost = 0, 0.0
    for fill in fill_rows:
        signed = fill["signed"]
        if fill["position_after"] - signed == 0:  # opened from flat: restart (a flatten outside the runner is not journaled)
            held, cost = 0, 0.0
        if held == 0 or (held > 0) == (signed > 0):
            held, cost = held + signed, cost + signed * fill["price"]
        else:
            direction = 1 if signed > 0 else -1
            closing = min(abs(held), abs(signed))
            cost *= (abs(held) - closing) / abs(held)
            held += closing * direction
            rest = abs(signed) - closing
            if rest:
                held, cost = rest * direction, rest * direction * fill["price"]
    if held == 0:
        return None
    return {"contracts": held, "entry": round(cost / held, 1)}


def realized(fill_rows: list[dict]) -> list[dict]:
    """Account value whenever the bot was flat before an order: exact, from the broker's cash."""
    return [{"at": f["at"], "nav": round(f["flat_nav"], 2)} for f in fill_rows if f["flat_nav"] is not None]


def _sentence(record: dict) -> str:
    event = record.get("event")
    side = {1: "BUY", -1: "SELL", 0: "FLAT"}
    if event == "start":
        return f"Runner started: mode {record.get('mode')}, {record.get('qty')} contracts"
    if event == "target":
        return (f"Vote now {side.get(record.get('vote'), '?')} (Calendar {record.get('calendar', 0):+d}, "
                f"Basis {record.get('basis', 0):+d}, Momentum {record.get('momentum', 0):+d})")
    if event == "order":
        return (f"Sent {record.get('side')} {record.get('qty')} at {record.get('price')} "
                f"({record.get('reason')}, position before {record.get('position')})")
    if event == "order_done":
        return f"Order {record.get('id')}: {record.get('status')}, filled {record.get('filled')}"
    if event == "cancel":
        return f"Cancelled order {record.get('id')}: {record.get('status')}"
    if event == "abandon":
        return f"Gave up on order {record.get('id')} ({record.get('status')})"
    if event == "blocked":
        return f"Paused: {record.get('reason')}"
    if event == "unblocked":
        return f"Resumed: {record.get('reason')} cleared"
    if event == "index_late":
        return "VN30 bar late"
    if event == "error":
        return f"Error: {record.get('error')}"
    details = {k: v for k, v in record.items() if k not in ("at", "event", "_at")}
    return f"{event}: {json.dumps(details, default=str)}"


def journal_lines(records: list[dict]) -> list[dict]:
    """Readable journal: targets only when the vote changes, repeated lines folded into one."""
    lines: list[dict] = []
    vote = None
    for record in records:
        event = record.get("event")
        if event == "target":
            if record.get("vote") == vote:
                continue
            vote = record.get("vote")
        text = _sentence(record)
        at = record["_at"].isoformat(timespec="seconds")
        if lines and event in ("index_late", "error") and lines[-1]["event"] == event and lines[-1]["text"] == text:
            lines[-1]["count"] += 1
            lines[-1]["until"] = at
            continue
        level = "bad" if event == "error" else "warn" if event in ("blocked", "index_late", "abandon") else ""
        lines.append({"at": at, "until": None, "event": event, "text": text, "count": 1, "level": level})
    return lines


def status(health: dict | None, now: datetime) -> dict:
    if health is None:
        return {"level": "idle", "text": "No health file yet"}
    age = (now - _ict(health["at"])).total_seconds()
    weekday = now.weekday() < 5
    in_day = weekday and DAY_START <= now.time() <= DAY_END
    in_session = weekday and SESSION_OPEN <= now.time() <= SESSION_CLOSE
    if health.get("halted"):
        return {"level": "bad", "text": "HALT: no new orders"}
    if in_session and age > STALE_AFTER_S:
        return {"level": "bad", "text": f"No update for {age / 60:.0f} min: is the runner down?"}
    if not in_day or age > STALE_AFTER_S:
        return {"level": "idle", "text": "Stopped until 08:30 on the next trading day"}
    if health.get("last_error"):
        return {"level": "warn", "text": f"Error: {health['last_error']}"}
    if health.get("blocked_by"):
        return {"level": "warn", "text": f"Paused: {health['blocked_by']}"}
    if not health.get("fix_logged_on"):
        return {"level": "warn", "text": "Broker link (FIX) down"}
    index_age = (health.get("feed_age_s") or {}).get("index")
    if in_session and index_age is not None and index_age > STALE_AFTER_S:
        if now.time() < time(9, 20):
            return {"level": "ok", "text": "Running · VN30 starts printing about 09:15"}
        return {"level": "warn", "text": f"VN30 bars {index_age / 60:.0f} min late: Basis and Momentum wait"}
    return {"level": "ok", "text": "Running" if in_session else "Running, outside the session"}


# ----- prices ----------------------------------------------------------------------------------------------------

def dnse_minutes(market: str, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    from src.adapters.data.dnse_candle_source import _request_payload, payload_to_frame

    payload = _request_payload(market, symbol, 1, int(start.timestamp()), int(end.timestamp()), retries=1, timeout=10)
    return payload_to_frame(payload)


class Prices:
    """VN30F1M and VN30 1-minute closes since a start day, cached for a minute.

    VN30F1M comes as a frame: ``close`` (the traded contract's price), ``adjusted`` (roll gaps removed) and
    ``contract``.
    """

    def __init__(self, fetch: Callable[..., pd.DataFrame] = dnse_minutes, ttl: float = PRICE_TTL_S) -> None:
        self.fetch, self.ttl = fetch, ttl
        self.lock = threading.Lock()
        self.cached: tuple[str, float, Any] | None = None
        self.error: str | None = None

    def get(self, start_day: str, now: datetime) -> tuple[pd.DataFrame, pd.Series] | None:
        with self.lock:
            if self.cached and self.cached[0] == start_day and clock.time() - self.cached[1] < self.ttl:
                return self.cached[2]
            try:
                from src.adapters.data.dnse_candle_source import add_front_month_contract
                from src.adapters.data.dnse_minute_bars import roll_adjust_front_month

                start = datetime.fromisoformat(start_day).replace(tzinfo=ICT)
                raw = add_front_month_contract(self.fetch("derivative", "VN30F1M", start, now))
                raw = raw.assign(Datetime=pd.to_datetime(raw["Datetime"])).sort_values("Datetime", kind="stable")
                adjusted, _ = roll_adjust_front_month(raw)
                futures = pd.DataFrame({"close": raw["Close"].to_numpy(float), "adjusted": adjusted["Close"].to_numpy(float),
                                        "contract": raw["Contract"].to_numpy()}, index=pd.DatetimeIndex(raw["Datetime"]))
                index = self.fetch("index", "VN30", start, now)
                value = (futures, index.set_index("Datetime")["Close"])
                self.cached, self.error = (start_day, clock.time(), value), None
            except Exception as exc:  # the rest of the page works without prices
                self.error = f"{type(exc).__name__}: {exc}"
                return self.cached[2] if self.cached else None
            return value


def _naive(stamp: str) -> pd.Timestamp:
    return pd.Timestamp(stamp).tz_localize(None)


def account_curve(fill_rows: list[dict], futures: pd.Series) -> pd.Series:
    """Account value in million VND at each futures minute from the first flat fill on."""
    anchors = [f for f in fill_rows if f["flat_nav"] is not None]
    if not anchors or futures.empty:
        return pd.Series(dtype=float)
    start = _naive(anchors[0]["at"])
    events = [(_naive(f["at"]), f) for f in fill_rows if _naive(f["at"]) >= start]
    values, i = {}, 0
    nav, cash, held = anchors[0]["flat_nav"], 0.0, 0
    for stamp, close in futures[futures.index >= start.floor("min")].items():
        while i < len(events) and events[i][0] < stamp + pd.Timedelta(minutes=1):
            fill = events[i][1]
            if fill["flat_nav"] is not None:  # the broker's cash when flat resets the estimate
                nav, cash, held = fill["flat_nav"], 0.0, 0
            cash -= fill["signed"] * fill["price"] * POINT_MILLION + abs(fill["signed"]) * FEE_MILLION
            held += fill["signed"]
            i += 1
        values[stamp] = nav + cash + held * close * POINT_MILLION
    return pd.Series(values, dtype=float)


def hold_curve(futures: pd.DataFrame, start: pd.Timestamp, nav: float, qty: int) -> pd.Series:
    """Account value in million VND holding ``qty`` VN30F1M from ``start`` on the same cash: rolled at each expiry,
    measured on the roll-adjusted closes, paying the fee on entry and on both sides of every roll."""
    after = futures[futures.index >= start]
    if after.empty:
        return pd.Series(dtype=float)
    rolls = after["contract"].ne(after["contract"].shift()).cumsum() - 1
    fees = qty * FEE_MILLION * (1 + 2 * rolls)
    return nav + qty * (after["adjusted"] - after["adjusted"].iloc[0]) * POINT_MILLION - fees


def comparison(curve: pd.Series, hold: pd.Series, index: pd.Series, nav: float, every: str = "5min") -> dict:
    """Percent change since the curve's start: the account and holding the same contracts, both on ``nav``,
    and the VN30 index."""
    if curve.empty:
        return {"t": [], "bot": [], "hold": [], "index": []}
    grid = curve.resample(every).last().dropna().index
    start = curve.index[0]

    def pct(series: pd.Series, base: float | None = None) -> list:
        after = series[series.index >= start]
        if after.empty:
            return [None] * len(grid)
        if base is None:
            before = series[series.index < start]
            base = before.iloc[-1] if not before.empty else after.iloc[0]
        aligned = series.reindex(series.index.union(grid)).ffill().reindex(grid)
        return [None if pd.isna(v) else round((v / base - 1) * 100, 3) for v in aligned]

    return {"t": [s.isoformat(timespec="minutes") for s in grid], "bot": pct(curve, nav), "hold": pct(hold, nav),
            "index": pct(index)}


def performance(curve: pd.Series, nav_rows: list[dict], fill_rows: list[dict]) -> dict:
    """Closed trades from one flat moment to the next (exact: the broker's cash), the deepest drawdown of the
    marked curve, and the fees paid."""
    trades = [later["nav"] - earlier["nav"] for earlier, later in zip(nav_rows, nav_rows[1:])]
    drawdown = None if curve.empty else round(float((curve / curve.cummax() - 1).min() * 100), 2)
    return {"trades": len(trades), "won": sum(t > 0 for t in trades), "max_drawdown_pct": drawdown,
            "fees_million": round(sum(abs(f["signed"]) for f in fill_rows) * FEE_MILLION, 2)}


def position_now(health: dict | None, entry: dict | None, close: pd.Series | None, curve: pd.Series | None,
                 now: datetime) -> dict:
    """Open profit at the last DNSE close, today's change of the marked account, and how many points against the
    position the free cash covers (about: the margin held moves a little with the price too)."""
    held = (health or {}).get("position") or 0
    cash = (health or {}).get("remain_cash_million")
    last = None if close is None or close.empty else float(close.iloc[-1])
    out = {"last": last, "open_points": None, "open_million": None, "today_million": None,
           "buffer_points": round(cash / (abs(held) * POINT_MILLION), 1) if held and cash is not None else None}
    if held and entry and last is not None:
        points = (last - entry["entry"]) * (1 if held > 0 else -1)
        out["open_points"], out["open_million"] = round(points, 1), round(points * abs(held) * POINT_MILLION, 2)
    if curve is not None and not curve.empty:
        today = curve[curve.index >= pd.Timestamp(now.date())]
        if not today.empty:
            before = curve[curve.index < today.index[0]]
            base = before.iloc[-1] if not before.empty else curve.iloc[0]
            out["today_million"] = round(float(today.iloc[-1] - base), 2)
    return out


def schedule(now: datetime) -> dict:
    """What the calendar holds ahead: the front month's expiry and the next Calendar legs."""
    day = now.date()
    contract = front_month_contract(day)
    expiry = expiry_date(2000 + int(contract[5:7]), int(contract[7:9]))
    left, cursor = 0, day
    while cursor < expiry:
        cursor = next_trading_day(cursor)
        left += 1
    monday = day if day.weekday() == 0 and is_trading_day(day) and now.time() < time(13, 0) else None
    cursor = day
    while monday is None:
        cursor += timedelta(days=1)
        if cursor.weekday() == 0 and is_trading_day(cursor):
            monday = cursor
    tuesday = day - timedelta(days=day.weekday() - 1)
    while True:  # the first Tuesday-Wednesday leg that has not ended yet
        wednesday = tuesday + timedelta(days=1)
        if is_trading_day(tuesday) and is_trading_day(wednesday):
            entry = tuesday - timedelta(days=1)
            while not is_trading_day(entry):
                entry -= timedelta(days=1)
            entry_at = datetime.combine(entry, time(14, 20), ICT)
            exit_at = datetime.combine(next_trading_day(wednesday), time(10, 0), ICT)
            if exit_at > now:
                break
        tuesday += timedelta(days=7)
    return {"contract": contract, "expiry": expiry.isoformat(), "sessions_left": left,
            "monday": monday.isoformat(), "long_from": entry_at.isoformat(timespec="minutes"),
            "long_to": exit_at.isoformat(timespec="minutes"), "long_now": entry_at <= now}


def intraday(start: str, end: str, fill_rows: list[dict], futures: pd.Series) -> dict:
    """VN30F1M closes from the first to the last session, the position held each minute, and the fills.

    Over more than five sessions the closes are kept every 5 minutes, plus every minute the position changes.
    """
    days = futures.index.normalize()
    window = futures[(days >= pd.Timestamp(start)) & (days <= pd.Timestamp(end))]
    earlier = [f for f in fill_rows if f["at"][:10] < start]
    held = earlier[-1]["position_after"] if earlier else 0
    inside = [f for f in fill_rows if start <= f["at"][:10] <= end]
    step = 1 if window.index.normalize().nunique() <= 5 else 5
    stamps, position, i = [], [], 0
    for stamp in window.index:
        while i < len(inside) and _naive(inside[i]["at"]) < stamp + pd.Timedelta(minutes=1):
            held = inside[i]["position_after"]
            i += 1
        if stamp.minute % step == 0 or not position or held != position[-1]:
            stamps.append(stamp)
            position.append(held)
    return {
        "t": [s.strftime("%Y-%m-%d %H:%M") for s in stamps],
        "price": [round(float(window[s]), 1) for s in stamps],
        "position": position,
        "fills": [{"t": f["at"][:16].replace("T", " "), "side": "BUY" if f["signed"] > 0 else "SELL",
                   "qty": abs(f["signed"]), "price": round(f["price"], 1)} for f in inside],
    }


# ----- state -----------------------------------------------------------------------------------------------------

def state(state_dir: Path, start: str | None = None, end: str | None = None, now: datetime | None = None,
          prices: Prices | None = None) -> dict:
    """Everything the page shows; the session chart, orders and journal cover the days from ``start`` to ``end``."""
    now = now or datetime.now(ICT)
    health_path = state_dir / "health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else None
    journal = read_journal(state_dir / "journal.jsonl")
    days = sorted({r["_at"].date().isoformat() for r in journal}) or [now.date().isoformat()]
    end = end if end in days else days[-1]
    start = start if start in days else days[max(0, days.index(end) - DEFAULT_SESSIONS + 1)]
    start, end = min(start, end), max(start, end)
    order_rows = orders(journal)
    fill_rows = fills(order_rows)
    nav = realized(fill_rows)
    charts: dict[str, Any] = {"error": None, "intraday": None, "since": None}
    entry = open_position(fill_rows)
    curve = close = None
    if prices is not None and nav:
        series = prices.get(nav[0]["at"][:10], now)
        charts["error"] = prices.error
        if series is not None:
            futures, index = series
            close = futures["close"]
            curve = account_curve(fill_rows, close)
            qty = (health or {}).get("qty") or 10
            hold = hold_curve(futures, curve.index[0], nav[0]["nav"], qty) if not curve.empty else pd.Series(dtype=float)
            charts["since"] = comparison(curve, hold, index, nav[0]["nav"])
            charts["intraday"] = intraday(start, end, fill_rows, close)
    return {
        "now": now.isoformat(timespec="seconds"),
        "status": status(health, now),
        "health": health,
        "health_age_s": None if health is None else round((now - _ict(health["at"])).total_seconds()),
        "thresholds": thresholds(),
        "days": days,
        "from": start,
        "to": end,
        "orders": order_rows[::-1],
        "open_position": entry,
        "now_position": position_now(health, entry, close, curve, now),
        "performance": performance(curve if curve is not None else pd.Series(dtype=float), nav, fill_rows),
        "schedule": schedule(now),
        "basis_warmup_sessions": BASIS_WARMUP_SESSIONS,
        "realized": nav,
        "realized_million": None if len(nav) < 2 else round(nav[-1]["nav"] - nav[0]["nav"], 2),
        "journal": journal_lines([r for r in journal if start <= r["_at"].date().isoformat() <= end])[::-1],
        "charts": charts,
    }


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calibrum</title>
<style>
body{margin:0;background:#fff;color:#222;font:13px/1.5 Verdana,Arial,sans-serif}
a{color:#3b5998;text-decoration:none}a:hover{text-decoration:underline}
#top{border-bottom:1px solid #b9b9b9;background:#f8f8f8}
#top>div{max-width:1100px;margin:0 auto;padding:8px 12px;display:flex;gap:18px;align-items:baseline;flex-wrap:wrap}
#logo{font:bold 20px Arial,sans-serif;color:#222;letter-spacing:.5px}
.tab{font-size:14px}.tab.on{color:#222;font-weight:bold;border-bottom:2px solid #3b5998}
#clock{margin-left:auto;color:#888}
#page{max-width:1100px;margin:0 auto;padding:12px;display:flex;gap:16px;align-items:flex-start}
#main{flex:1;min-width:0}#side{width:260px;flex:none}
@media (max-width:820px){#page{flex-direction:column}#side{width:100%}}
h3{font-size:14px;margin:18px 0 6px}h3:first-child{margin-top:0}h3 small{font-weight:normal;color:#888}
table{border-collapse:collapse;width:100%;margin-bottom:4px}
th,td{border:1px solid #e1e1e1;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#f8f8f8;font-weight:normal;color:#555}tr:nth-child(even) td{background:#fcfcfc}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.box{border:1px solid #b9b9b9;border-radius:4px;margin-bottom:12px}
.box .hd{background:#f8f8f8;border-bottom:1px solid #b9b9b9;padding:4px 10px;font-weight:bold;color:#3b5998}
.box .bd{padding:8px 10px}.box .bd div{display:flex;justify-content:space-between;gap:8px}
.big{font-size:18px;font-weight:bold}
.up{color:#0a0}.down{color:#c00}
.buy{color:#0a0;font-weight:bold}.sell{color:#c00;font-weight:bold}.flat{color:#888}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.ok{background:#0a0}.warn{background:#e6a100}.bad{background:#c00}.idle{background:#aaa}
tr.r-bad td{color:#c00}tr.r-warn td{color:#a06800}.muted{color:#888}
.scroll{overflow-x:auto}.chart{border:1px solid #e1e1e1;padding:6px 8px}
svg text{font:11px Verdana,Arial,sans-serif;fill:#888}
.legend{color:#555}.legend span{margin-right:14px}.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px}
select{font:inherit;margin-left:6px}
.range{margin:2px 0 8px}.range .rl{display:flex;gap:6px;align-items:baseline;flex-wrap:wrap}
.rtrack{position:relative;height:24px;margin:2px 8px 0}
.rtrack:before{content:"";position:absolute;left:0;right:0;top:10px;height:4px;background:#e1e1e1;border-radius:2px}
.rfill{position:absolute;top:10px;height:4px;background:#3b5998;border-radius:2px}
.rtrack input{position:absolute;left:-8px;width:calc(100% + 16px);top:0;height:24px;margin:0;background:none;pointer-events:none;-webkit-appearance:none;appearance:none}
.rtrack input::-webkit-slider-runnable-track{background:none;border:0}
.rtrack input::-webkit-slider-thumb{pointer-events:auto;-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:#fff;border:2px solid #3b5998;cursor:grab}
.rtrack input::-moz-range-thumb{pointer-events:auto;width:12px;height:12px;border-radius:50%;background:#fff;border:2px solid #3b5998;cursor:grab}
.rtrack input::-moz-range-track{background:none}
.rends{display:flex;justify-content:space-between;color:#888;font-size:11px}
</style></head><body>
<div id="top"><div><span id="logo">CALIBRUM</span>
<a class="tab on" href="#overview">Overview</a><a class="tab" href="#orders">Orders</a><a class="tab" href="#journal">Journal</a>
<span id="clock"></span></div></div>
<div id="page"><div id="main"><p class="muted">Loading…</p></div>
<div id="side">
 <div class="box"><div class="hd">Bot</div><div class="bd" id="bot"></div></div>
 <div class="box"><div class="hd">Since start</div><div class="bd" id="since"></div></div>
 <div class="box"><div class="hd">Connections</div><div class="bd" id="conn"></div></div>
</div></div>
<script>
const $=id=>document.getElementById(id),Q=new URLSearchParams(location.search);let S=null,dragging=false,from=Q.get('from')||Q.get('day'),to=Q.get('to')||Q.get('day');
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const fmt=(v,d=1)=>v==null?'–':Number(v).toFixed(d);
const sgn=(v,d=2)=>v==null?'–':(v>0?'+':v<0?'−':'')+Math.abs(v).toFixed(d);
const side=(v,q)=>v>0?`<span class="buy">BUY${q?' '+q:''}</span>`:v<0?`<span class="sell">SELL${q?' '+q:''}</span>`:'<span class="flat">flat</span>';
const money=v=>v==null?'–':`<span class="${v>0?'up':v<0?'down':''}">${sgn(v)} M</span>`;
const DOW=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'],dm=s=>`${DOW[new Date(s.slice(0,10)+'T12:00').getDay()]} ${s.slice(8,10)}/${s.slice(5,7)}`;
const ago=v=>v==null?'–':v<120?`${Math.round(v)} s`:v<7200?`${Math.round(v/60)} min`:`${(v/3600).toFixed(1)} h`;
const W=800,H=230,L=56,B=22;

function grid(lo,hi,fy){let g='';for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4,y=H-B-(H-B-8)*k/4;
 g+=`<line x1="${L}" x2="${W-6}" y1="${y}" y2="${y}" stroke="#eee"/><text x="${L-6}" y="${y+4}" text-anchor="end">${fy(v)}</text>`}return g}
function sinceChart(c){if(!c||c.t.length<2)return '<p class="muted">Not enough data yet.</p>';
 const n=c.t.length,all=[...c.bot,...c.hold,...c.index].filter(v=>v!=null);let lo=Math.min(0,...all),hi=Math.max(0,...all);
 const pad=(hi-lo)*.08||.5;lo-=pad;hi+=pad;const x=i=>L+i/(n-1)*(W-L-8),y=v=>H-B-(v-lo)/(hi-lo)*(H-B-8);
 let g=grid(lo,hi,v=>v.toFixed(1)+'%')+`<line x1="${L}" x2="${W-6}" y1="${y(0)}" y2="${y(0)}" stroke="#bbb"/>`;let last='';
 c.t.forEach((s,i)=>{const d=s.slice(8,10)+'/'+s.slice(5,7);if(d!=last){g+=`<line x1="${x(i)}" x2="${x(i)}" y1="8" y2="${H-B}" stroke="#f2f2f2"/><text x="${x(i)+3}" y="${H-6}">${d}</text>`;last=d}});
 [[c.hold,'#e08a3c',1.4,''],[c.index,'#888',1.4,'4 3'],[c.bot,'#3b5998',2.4,'']].forEach(([v,col,w,dash])=>{let d='',pen=false;
  v.forEach((p,i)=>{if(p==null){pen=false;return}d+=`${pen?'L':'M'}${x(i).toFixed(1)},${y(p).toFixed(1)}`;pen=true});
  g+=`<path d="${d}" fill="none" stroke="${col}" stroke-width="${w}" stroke-dasharray="${dash}"/>`});
 return '<div class="legend"><span><i style="background:#3b5998"></i>Account</span><span><i style="background:#e08a3c"></i>Holding '+(S.health?.qty??10)+' VN30F1M</span><span><i style="background:#888"></i>VN30 index</span></div>'+
 `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Percent change since start">${g}</svg>`}
function sessionChart(c){if(!c||c.t.length<2)return '<p class="muted">No prices for these days yet.</p>';
 const n=c.t.length;let lo=Math.min(...c.price),hi=Math.max(...c.price);const pad=(hi-lo)*.12||1;lo-=pad;hi+=pad;
 const days=[...new Set(c.t.map(s=>s.slice(0,10)))],D=days.length,di=Object.fromEntries(days.map((d,k)=>[d,k]));
 const slot=s=>{const m=+s.slice(11,13)*60+ +s.slice(14,16);return Math.max(0,m<13*60?Math.min(m-540,150):150+Math.min(m-780,105))};
 const X=s=>L+(di[s.slice(0,10)]*255+slot(s))/(D*255)*(W-L-8),x=i=>X(c.t[i]),y=v=>H-B-(v-lo)/(hi-lo)*(H-B-8);let g='',i0=0;
 for(let i=1;i<=n;i++){if(i==n||c.position[i]!=c.position[i0]){const p=c.position[i0];
  if(p)g+=`<rect x="${x(i0)}" y="8" width="${Math.max(x(Math.min(i,n-1))-x(i0),1)}" height="${H-B-8}" fill="${p>0?'#0a0':'#c00'}" opacity=".08"/>`;i0=i}}
 g+=grid(lo,hi,v=>v.toFixed(1));
 if(D==1)['09:00','10:00','11:00','13:00','14:00','14:45'].forEach(h=>{const at=X(days[0]+' '+h);
  g+=`<line x1="${at}" x2="${at}" y1="8" y2="${H-B}" stroke="#f2f2f2"/><text x="${at}" y="${H-6}" text-anchor="${h=='14:45'?'end':'middle'}">${h}</text>`});
 else{const every=Math.ceil(D/12);days.forEach((d,k)=>{const at=L+k/D*(W-L-8);
  g+=`<line x1="${at}" x2="${at}" y1="8" y2="${H-B}" stroke="${k?'#e6e6e6':'#f2f2f2'}"/>`;
  if(k%every==0)g+=`<text x="${at+3}" y="${H-6}">${d.slice(8,10)}/${d.slice(5,7)}</text>`})}
 g+=`<path d="${c.price.map((v,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')}" fill="none" stroke="#222" stroke-width="${D>10?1:1.3}"/>`;
 c.fills.forEach(f=>{const i=c.t.findIndex(s=>s>=f.t);if(i<0)return;const X=x(i),Y=y(f.price),up=f.side=='BUY',z=D>10?4:6;
  g+=`<path d="M${X},${up?Y+4:Y-4} l-${z},${up?2*z:-2*z} h${2*z}z" fill="${up?'#0a0':'#c00'}"><title>${f.t} ${f.side} ${f.qty} ≈ ${f.price}</title></path>`});
 return '<div class="legend"><span><i style="background:#222"></i>VN30F1M</span><span><i style="background:#0a0;opacity:.35"></i>holding long</span><span><i style="background:#c00;opacity:.35"></i>holding short</span><span><span class="buy">▲</span> buy <span class="sell">▼</span> sell</span></div>'+
 `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="VN30F1M from ${days[0]} to ${days[D-1]} with the bot's trades">${g}</svg>`}

function orderTable(rows,withDate){return '<div class="scroll"><table><tr>'+(withDate?'<th>Date</th>':'')+'<th>Time</th><th>Side</th><th>Qty</th><th>Limit</th><th>Reason</th><th>Position before</th><th>Result</th></tr>'+
 (rows.map(o=>`<tr>${withDate?`<td>${o.at.slice(0,10)}</td>`:''}<td>${o.at.slice(11,19)}</td><td>${side(o.side=='BUY'?1:-1)}</td><td class="n">${o.qty}</td><td class="n">${o.price}</td><td>${o.reason}</td><td class="n">${o.position_before??''}</td><td>${esc(o.status)}${o.filled&&o.filled!=o.qty?` (${o.filled})`:''}</td></tr>`).join('')
 ||`<tr><td colspan="${withDate?8:7}" class="muted">No orders.</td></tr>`)+'</table></div>'}
const inRange=at=>at.slice(0,10)>=S.from&&at.slice(0,10)<=S.to,multi=()=>S.from!=S.to;
function rangePicker(){const n=S.days.length-1;if(n<1)return `<p class="muted">${S.from}</p>`;
 return `<div class="range"><div class="rl"><b id="rfrom"></b>→<b id="rto"></b><span class="muted" id="rcount"></span></div>
 <div class="rtrack"><div class="rfill" id="rfill"></div><input type="range" id="ra" min="0" max="${n}" step="1" value="${S.days.indexOf(S.from)}" aria-label="First day">
 <input type="range" id="rb" min="0" max="${n}" step="1" value="${S.days.indexOf(S.to)}" aria-label="Last day"></div>
 <div class="rends"><span>${S.days[0]}</span><span>${S.days[n]}</span></div></div>`}
function wireRange(){const ra=$('ra'),rb=$('rb');if(!ra)return;const n=S.days.length-1;
 const pick=()=>{const a=+ra.value,b=+rb.value;return a<=b?[a,b]:[b,a]};
 const show=()=>{const [a,b]=pick();$('rfrom').textContent=S.days[a];$('rto').textContent=S.days[b];
  $('rcount').textContent=`· ${b-a+1} session${b>a?'s':''}`;$('rfill').style.left=a/n*100+'%';$('rfill').style.width=(b-a)/n*100+'%'};
 [ra,rb].forEach(el=>{el.oninput=()=>{dragging=true;show()};el.onchange=()=>{dragging=false;const [a,b]=pick();from=S.days[a];to=S.days[b];load()}});show()}

function overview(){const h=S.health||{},tg=h.targets||{},th=S.thresholds,op=S.open_position,pos=h.position,np=S.now_position,sc=S.schedule;
 let html=`<h3>Position</h3><div class="scroll"><table><tr><th>Contract</th><th>Position</th><th>Entry (est.)</th><th>Last</th><th>Open profit</th><th>Today</th><th>Margin buffer</th></tr>
 <tr><td>${tg.contract??'–'}</td><td>${pos==null?'–':side(pos,Math.abs(pos))}</td><td class="n">${op?fmt(op.entry):'–'}</td><td class="n">${fmt(np.last)}</td>
 <td class="n">${np.open_points==null?'–':`${money(np.open_million)} <span class="muted">(${sgn(np.open_points,1)} pts)</span>`}</td><td class="n">${money(np.today_million)}</td>
 <td class="n" title="Free cash ${fmt(h.remain_cash_million)} M VND: equity minus the margin held">${np.buffer_points==null?(h.remain_cash_million!=null?fmt(h.remain_cash_million)+' M free':'–'):`<b class="${np.buffer_points<30?'down':''}">≈ ${fmt(np.buffer_points,0)} pts</b> <span class="muted">against us</span>`}</td></tr></table></div>`;
 html+=`<h3>Signals <small>· bar ${tg.last_minute?tg.last_minute.slice(11,16):'–'}</small></h3><table><tr><th>Source</th><th>Signal</th><th>Detail</th></tr>
 <tr><td>Calendar</td><td>${side(tg.calendar)}</td><td class="muted">Monday short, Tuesday–Wednesday long</td></tr>
 <tr><td>Basis</td><td>${side(tg.basis)}</td><td>z = ${sgn(tg.basis_z)} <span class="muted">(trades at |z| ≥ ${th.z_entry}; ${tg.basis_bars??'–'} of ${th.window} bars)</span></td></tr>
 <tr><td>Momentum</td><td>${side(tg.momentum)}</td><td>score = ${sgn(tg.momentum_score,3)} <span class="muted">(trades at |score| ≥ ${fmt(th.theta,3)})</span></td></tr>
 <tr><td><b>Vote</b></td><td>${side(tg.vote,tg.vote?h.qty:0)}</td><td class="muted">sign of Calendar + Basis + Momentum, × ${h.qty??10} contracts</td></tr></table>`;
 html+=`<h3>Ahead</h3><table><tr><th>When</th><th>What</th></tr>
 <tr><td>${dm(sc.expiry)}</td><td><b>${sc.contract} expires</b>${sc.sessions_left?` · ${sc.sessions_left} session${sc.sessions_left>1?'s':''} left`:' · today'} <span class="muted">· flat that day; Basis then waits ${th.window??60} bars (about ${S.basis_warmup_sessions} sessions) on the new contract</span></td></tr>
 <tr><td>${dm(sc.long_from)} ${sc.long_from.slice(11,16)} → ${dm(sc.long_to)} ${sc.long_to.slice(11,16)}</td><td>Calendar <b>long</b>, Tuesday–Wednesday${sc.long_now?' <span class="up">· in the window now</span>':''}</td></tr>
 <tr><td>${dm(sc.monday)}</td><td>Calendar <b>short</b> if a 10-minute close falls below the 09:00–09:30 low before 13:00; out at 14:20</td></tr></table>`;
 html+=`<h3>Sessions <small>· drag either end to choose the days</small></h3>${rangePicker()}<div class="chart">${S.charts.intraday?sessionChart(S.charts.intraday):`<p class="muted">${esc(S.charts.error)||'No prices.'}</p>`}</div>`;
 html+=`<h3>Since start <small>· percent of the starting account; holding the same contracts on the same cash, after fees</small></h3><div class="chart">${sinceChart(S.charts.since)}</div>`;
 html+=`<h3>Orders <small>· ${multi()?S.from+' → '+S.to:S.from}</small></h3>`+orderTable(S.orders.filter(o=>inRange(o.at)),multi());
 return html}
const ordersTab=()=>`<h3>All orders <small>· ${S.orders.length}, latest first · limit prices; fills are about 0.3 points better</small></h3>`+orderTable(S.orders,true);
const when=at=>(multi()?at.slice(5,10)+' ':'')+at.slice(11,19);
const journalTab=()=>`<h3>Journal <small>latest first</small></h3>${rangePicker()}<div class="scroll"><table><tr><th>Time</th><th>What happened</th></tr>`+
 (S.journal.map(l=>`<tr class="r-${l.level}"><td>${when(l.at)}${l.until?'–'+l.until.slice(11,19):''}</td><td>${esc(l.text)}${l.count>1?` <span class="muted">×${l.count}</span>`:''}</td></tr>`).join('')||'<tr><td colspan="2" class="muted">Nothing on these days.</td></tr>')+'</table></div>';

function sidebar(){const h=S.health||{},fa=h.feed_age_s||{},c=S.charts.since,pf=S.performance;
 const last=a=>a&&a.length?[...a].reverse().find(v=>v!=null):null;
 $('bot').innerHTML=`<p style="margin:0 0 6px"><span class="dot ${S.status.level}"></span>${esc(S.status.text)}</p>
 <div><span>Updated</span><span>${ago(S.health_age_s)} ago</span></div><div><span>Mode</span><span>${h.mode??'–'}, ${h.qty??'–'} contracts</span></div>`;
 $('since').innerHTML=`<div><span>Realized</span><span class="big">${S.realized_million==null?'–':sgn(S.realized_million)+' M'}</span></div>
 <div><span>Account</span><span>${c?sgn(last(c.bot))+'%':'–'}</span></div><div><span>Hold ${h.qty??10} VN30F1M</span><span>${c?sgn(last(c.hold))+'%':'–'}</span></div>
 <div><span>VN30 index</span><span>${c?sgn(last(c.index))+'%':'–'}</span></div>
 <div><span>Max drawdown</span><span>${pf.max_drawdown_pct==null?'–':sgn(pf.max_drawdown_pct,1)+'%'}</span></div>
 <div><span>Trades won</span><span>${pf.trades?`${pf.won} / ${pf.trades}`:'–'}</span></div><div><span>Fees paid</span><span>${fmt(pf.fees_million,2)} M</span></div>
 <p class="muted" style="margin:6px 0 0">From ${S.realized.length?S.realized[0].at.slice(0,10):'–'}. Realized and trades are exact (the broker's cash when flat); the rest is marked at DNSE closes.</p>`;
 $('conn').innerHTML=`<div><span>VN30F1M bar</span><span>${ago(fa.futures)} old</span></div><div><span>VN30 bar</span><span>${ago(fa.index)} old</span></div>
 <div><span>Broker (FIX)</span><span>${h.fix_logged_on?'connected':'<b style="color:#c00">down</b>'}</span></div><div><span>Pending order</span><span>${h.pending?esc(h.pending[0]):'none'}</span></div>
 ${S.charts.error?`<p style="color:#c00;margin:6px 0 0">Prices: ${esc(S.charts.error)}</p>`:''}`}

function render(){const tab=(location.hash||'#overview').slice(1);
 document.querySelectorAll('.tab').forEach(a=>a.classList.toggle('on',a.getAttribute('href')=='#'+tab));
 $('main').innerHTML=tab=='orders'?ordersTab():tab=='journal'?journalTab():overview();sidebar();
 $('clock').textContent=S.now.slice(0,19).replace('T',' ')+' ICT';wireRange()}
async function load(){if(dragging)return;try{const r=await fetch('api/state'+(from&&to?`?from=${from}&to=${to}`:''));const next=await r.json();if(!dragging){S=next;render()}}catch(e){$('clock').textContent='connection lost, retrying…'}}
window.onhashchange=()=>S&&render();load();setInterval(load,15000);
</script></body></html>
"""


def handler(state_dir: Path, prices: Prices) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                body, kind = PAGE.encode("utf-8"), "text/html; charset=utf-8"
            elif url.path == "/api/state":
                query = parse_qs(url.query)
                day = query.get("day", [None])[0]  # an old single-day link
                start, end = query.get("from", [day])[0], query.get("to", [day])[0]
                body = json.dumps(state(state_dir, start, end, prices=prices), default=str).encode("utf-8")
                kind = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # quiet: the runner's journal is the log that matters
            pass

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, default=Path("/state"))
    parser.add_argument("--host", default="0.0.0.0")  # the container port is published on 127.0.0.1 only
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), handler(args.state_dir, Prices()))
    print(f"dashboard on {args.host}:{args.port}, state {args.state_dir}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

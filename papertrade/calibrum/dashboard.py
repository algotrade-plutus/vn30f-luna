"""Read-only web dashboard for the Calibrum runner.

Serves one page and ``/api/state`` from the runner's state directory
(``health.json`` and ``journal.jsonl``). It holds no credentials and never
talks to the broker. On the EC2 it listens on 127.0.0.1 only; open it from a
laptop through an SSM port forward (``make papertrade-dashboard``).

    python -m papertrade.calibrum.dashboard --state-dir /state --port 8080
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ICT = timezone(timedelta(hours=7))
DAY_START, SESSION_OPEN, SESSION_CLOSE, DAY_END = time(8, 30), time(9, 0), time(14, 45), time(15, 0)
STALE_AFTER_S = 180  # health is rewritten every loop; older than this in a session means the runner is down
JOURNAL_TAIL = 20_000
MULTIPLIER_MILLION = 0.1  # million VND per index point per contract


def _ict(stamp: str) -> datetime:
    moment = datetime.fromisoformat(stamp)
    if moment.tzinfo is None:  # health and target clocks are naive ICT
        return moment.replace(tzinfo=ICT)
    return moment.astimezone(ICT)


def read_journal(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-JOURNAL_TAIL:]
    records = []
    for line in lines:
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
                "position_before": record.get("position"), "vote": record.get("vote"),
                "status": "sent", "filled": 0,
            }
        elif event in ("order_done", "cancel", "abandon") and key in rows:
            rows[key]["status"] = record.get("status") or event
            if "filled" in record:
                rows[key]["filled"] = record["filled"]
    return list(rows.values())


def realized(journal: list[dict]) -> list[dict]:
    """Account value whenever the bot was flat: its cash then is the whole account (no margin held)."""
    points = [
        {"at": r["_at"].isoformat(timespec="seconds"), "nav_million": round(r["remain_cash"] / 1e6, 2)}
        for r in journal
        if r.get("event") == "order" and r.get("position") == 0 and r.get("remain_cash") is not None
    ]
    return points


def notable(records: list[dict]) -> list[dict]:
    """Everything except the per-minute targets, which are kept only when the vote changes."""
    kept, vote = [], None
    for record in records:
        if record.get("event") == "target":
            if record.get("vote") == vote:
                continue
            vote = record.get("vote")
        kept.append(record)
    return kept


def open_position(order_rows: list[dict]) -> dict | None:
    """Contracts held and the approximate entry: a fill is about 0.3 points better than the crossing limit."""
    held, cost = 0, 0.0
    for row in order_rows:
        filled = int(row["filled"] or 0)
        if not filled:
            continue
        sign = 1 if row["side"] == "BUY" else -1
        fill = row["price"] - 0.3 * sign
        if held == 0 or (held > 0) == (sign > 0):
            cost += sign * filled * fill
            held += sign * filled
        else:
            closing = min(abs(held), filled)
            cost *= (abs(held) - closing) / abs(held)
            held += sign * closing
            if filled > closing:
                cost, held = sign * (filled - closing) * fill, sign * (filled - closing)
    if held == 0:
        return None
    return {"contracts": held, "entry_approx": round(cost / held, 1)}


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
        return {"level": "idle", "text": "Not running: the timer starts it at 08:30 on trading days"}
    if health.get("last_error"):
        return {"level": "warn", "text": f"Error: {health['last_error']}"}
    if health.get("blocked_by"):
        return {"level": "warn", "text": f"Waiting: {health['blocked_by']}"}
    if not health.get("fix_logged_on"):
        return {"level": "warn", "text": "Broker link (FIX) down"}
    return {"level": "ok", "text": "Trading" if in_session else "Running, outside the session"}


def state(state_dir: Path, day: str | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(ICT)
    health_path = state_dir / "health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else None
    journal = read_journal(state_dir / "journal.jsonl")
    days = sorted({r["_at"].date().isoformat() for r in journal}, reverse=True)
    day = day if day in days else (days[0] if days else now.date().isoformat())
    today = [r for r in journal if r["_at"].date().isoformat() == day]
    targets = [
        {"at": r["_at"].isoformat(timespec="seconds"), **{k: r.get(k) for k in ("calendar", "basis", "momentum", "vote")}}
        for r in today if r.get("event") == "target"
    ]
    all_orders = orders(journal)
    nav = realized(journal)
    return {
        "now": now.isoformat(timespec="seconds"),
        "status": status(health, now),
        "health": health,
        "health_age_s": None if health is None else round((now - _ict(health["at"])).total_seconds()),
        "days": days[:15],
        "day": day,
        "targets": targets,
        "orders": [o for o in all_orders if o["at"].startswith(day)],
        "open_position": open_position(all_orders),
        "realized": nav,
        "realized_million": None if len(nav) < 2 else round(nav[-1]["nav_million"] - nav[0]["nav_million"], 2),
        "events": [
            {k: v for k, v in r.items() if k != "_at"} | {"at": r["_at"].isoformat(timespec="seconds")}
            for r in notable(today)[-60:]
        ][::-1],
    }


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calibrum live</title>
<style>
:root{--bg:#F3F1EA;--card:#FBFAF5;--ink:#14213D;--muted:#5B6577;--line:#D9D3C3;--ok:#1F7A4D;--warn:#B7791F;--bad:#C0392B;
--long:#2a78d6;--short:#E08A3C;--flat:#C9C3B3}
@media (prefers-color-scheme:dark){:root{--bg:#10151F;--card:#182030;--ink:#E8E6DF;--muted:#9AA3B2;--line:#2A3446;--flat:#3A4556}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,"IBM Plex Sans",Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:16px}
h1{font-size:22px;margin:0}.muted{color:var(--muted)}
.pill{display:inline-flex;gap:8px;align-items:center;padding:6px 12px;border-radius:999px;font-weight:600;background:var(--card);border:1px solid var(--line)}
.dot{width:10px;height:10px;border-radius:50%}.ok{background:var(--ok)}.warn{background:var(--warn)}.bad{background:var(--bad)}.idle{background:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
.big{font-size:28px;font-weight:650}.row{display:flex;justify-content:space-between;gap:8px}
.sig{display:inline-block;min-width:44px;text-align:center;padding:2px 8px;border-radius:6px;font-weight:650;color:#fff}
.s1{background:var(--long)}.s-1{background:var(--short)}.s0{background:var(--flat);color:var(--ink)}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}select{font:inherit;padding:4px 8px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink)}
svg text{fill:var(--muted);font-size:11px}pre{margin:0;white-space:pre-wrap;word-break:break-all;font-size:12px}
.err{color:var(--bad)}
</style></head><body><main>
<header><div><h1>Calibrum live</h1><div class="muted" id="meta">loading…</div></div>
<div class="pill"><span class="dot idle" id="dot"></span><span id="statustext">…</span></div></header>
<div class="grid">
 <div class="card"><h2>Position</h2><div class="big" id="pos">–</div><div class="muted" id="posnote"></div></div>
 <div class="card"><h2>Realized since start</h2><div class="big" id="pnl">–</div><div class="muted" id="pnlnote"></div></div>
 <div class="card"><h2>Signals, last closed bar</h2><div id="sigs"></div></div>
 <div class="card"><h2>Feed and broker</h2><div id="feed"></div></div>
</div>
<div class="card" style="margin-bottom:12px"><div class="row"><h2>Signals through the session</h2>
<select id="day"></select></div><div id="strip"></div></div>
<div class="grid" style="grid-template-columns:1fr">
<div class="card"><h2>Account value when flat (million VND)</h2><div id="nav"></div></div>
<div class="card"><h2>Orders</h2><div class="scroll"><table id="orders"></table></div></div>
<div class="card"><h2>Journal, latest first (targets only when the vote changes)</h2><div class="scroll"><table id="events"></table></div></div>
</div>
<p class="muted">Read-only view of /var/lib/calibrum/live on the EC2. Refreshes every 15 s. Entry prices are approximate (limit ∓ 0.3).</p>
</main><script>
const $=id=>document.getElementById(id);let day=null;
const t=s=>s?s.slice(11,19):'';const sig=v=>`<span class="sig s${v??0}">${v==1?'long':v==-1?'short':'flat'}</span>`;
const age=v=>v==null?'–':v<120?`${Math.round(v)} s`:v<7200?`${Math.round(v/60)} min`:`${(v/3600).toFixed(1)} h`;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function strip(targets){
 if(!targets.length)return '<p class="muted">No targets this day.</p>';
 const W=1100,H=150,L=90,start=9*60,end=14*60+45,x=s=>{const m=+s.slice(11,13)*60+ +s.slice(14,16)+ +s.slice(17,19)/60;return L+(Math.min(Math.max(m,start),end)-start)/(end-start)*(W-L-10)};
 const rows=[['calendar','Calendar'],['basis','Basis'],['momentum','Momentum'],['vote','Vote']];let g='';
 rows.forEach(([k,name],i)=>{const y=8+i*34;g+=`<text x="0" y="${y+17}">${name}</text>`;
  targets.forEach((p,j)=>{const x1=x(p.at),x2=j+1<targets.length?x(targets[j+1].at):x1+3;const v=p[k]??0;
   const c=v==1?'var(--long)':v==-1?'var(--short)':'var(--flat)';g+=`<rect x="${x1}" y="${y}" width="${Math.max(x2-x1,1)+0.6}" height="24" fill="${c}" shape-rendering="crispEdges"/>`})});
 [9,10,11,13,14].forEach(h=>{const xx=x(`0000-00-00T${String(h).padStart(2,'0')}:00:00`);g+=`<text x="${xx}" y="${H-2}">${h}:00</text>`});
 return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Sleeve and vote positions through the session">${g}</svg>`}
function navChart(points){
 if(points.length<2)return '<p class="muted">Not enough flat moments yet.</p>';
 const W=1100,H=180,P=40,v=points.map(p=>p.nav_million),lo=Math.min(...v),hi=Math.max(...v),span=(hi-lo)||1;
 const xs=i=>P+i/(points.length-1)*(W-2*P),ys=n=>H-24-(n-lo)/span*(H-48);
 const d=points.map((p,i)=>`${i?'L':'M'}${xs(i).toFixed(1)},${ys(p.nav_million).toFixed(1)}`).join('');
 let g=`<path d="${d}" fill="none" stroke="var(--long)" stroke-width="2.5"/>`;
 points.forEach((p,i)=>g+=`<circle cx="${xs(i)}" cy="${ys(p.nav_million)}" r="3" fill="var(--long)"><title>${p.at.slice(0,16).replace('T',' ')}: ${p.nav_million}</title></circle>`);
 g+=`<text x="0" y="${ys(hi)+4}">${hi.toFixed(1)}</text><text x="0" y="${ys(lo)+4}">${lo.toFixed(1)}</text>`;
 g+=`<text x="${P}" y="${H-4}">${points[0].at.slice(5,10)}</text><text x="${W-P-40}" y="${H-4}">${points.at(-1).at.slice(5,10)}</text>`;
 return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Account value at each flat moment">${g}</svg>`}
async function load(){
 const r=await fetch('api/state'+(day?`?day=${day}`:''));const s=await r.json();const h=s.health||{},tg=h.targets||{};
 $('dot').className='dot '+s.status.level;$('statustext').textContent=s.status.text;
 $('meta').textContent=`${s.now.slice(0,19).replace('T',' ')} ICT · mode ${h.mode??'–'} · qty ${h.qty??'–'} · health ${s.health_age_s??'–'} s old`;
 const pos=h.position;$('pos').innerHTML=pos==null?'–':`${pos>0?'+':''}${pos} ${tg.contract??''}`;
 $('posnote').textContent=(s.open_position?`entry ≈ ${s.open_position.entry_approx} · `:'')+(h.remain_cash_million!=null?`cash free ${h.remain_cash_million} M`:'');
 $('pnl').textContent=s.realized_million==null?'–':`${s.realized_million>0?'+':''}${s.realized_million} M`;
 $('pnlnote').textContent=s.realized.length?`from ${s.realized[0].nav_million} M on ${s.realized[0].at.slice(0,10)}, at flat moments`:'';
 $('sigs').innerHTML=`<div class="row"><span>Calendar</span>${sig(tg.calendar)}</div><div class="row"><span>Basis (z ${tg.basis_z??'–'}, ${tg.basis_bars??'–'}/60 bars)</span>${sig(tg.basis)}</div>
 <div class="row"><span>Momentum (score ${tg.momentum_score??'–'}, θ 0.232)</span>${sig(tg.momentum)}</div><div class="row"><b>Vote × ${h.qty??10}</b>${sig(tg.vote)}</div>
 <div class="muted">bar ${t(tg.last_minute)} · computed ${t(tg.now)}</div>`;
 const fa=h.feed_age_s||{};$('feed').innerHTML=`<div class="row"><span>Futures bar age</span><span>${age(fa.futures)}</span></div>
 <div class="row"><span>VN30 bar age</span><span>${age(fa.index)}</span></div><div class="row"><span>FIX logged on</span><span>${h.fix_logged_on?'yes':'no'}</span></div>
 <div class="row"><span>Pending order</span><span>${h.pending?esc(h.pending[0]):'none'}</span></div>
 <div class="row"><span>Blocked by</span><span>${esc(h.blocked_by)||'–'}</span></div>${h.last_error?`<div class="err">${esc(h.last_error)}</div>`:''}`;
 $('day').innerHTML=s.days.map(d=>`<option ${d==s.day?'selected':''}>${d}</option>`).join('');
 $('strip').innerHTML=strip(s.targets);$('nav').innerHTML=navChart(s.realized);
 $('orders').innerHTML='<tr><th>Time</th><th>Side</th><th class="num">Qty</th><th class="num">Limit</th><th>Why</th><th class="num">Position before</th><th>Status</th><th class="num">Filled</th></tr>'+
  (s.orders.map(o=>`<tr><td>${t(o.at)}</td><td>${o.side}</td><td class="num">${o.qty}</td><td class="num">${o.price}</td><td>${o.reason}</td><td class="num">${o.position_before??''}</td><td>${esc(o.status)}</td><td class="num">${o.filled}</td></tr>`).join('')||'<tr><td colspan="8" class="muted">No orders this day.</td></tr>');
 $('events').innerHTML='<tr><th>Time</th><th>Event</th><th>Details</th></tr>'+s.events.map(e=>{const{at,event,...rest}=e;
  return `<tr class="${event=='error'?'err':''}"><td>${t(at)}</td><td>${esc(event)}</td><td><pre>${esc(JSON.stringify(rest))}</pre></td></tr>`}).join('');
}
$('day').onchange=e=>{day=e.target.value;load()};load();setInterval(load,15000);
</script></body></html>
"""


def handler(state_dir: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                body, kind = PAGE.encode("utf-8"), "text/html; charset=utf-8"
            elif url.path == "/api/state":
                day = parse_qs(url.query).get("day", [None])[0]
                body, kind = json.dumps(state(state_dir, day), default=str).encode("utf-8"), "application/json"
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
    server = ThreadingHTTPServer((args.host, args.port), handler(args.state_dir))
    print(f"dashboard on {args.host}:{args.port}, state {args.state_dir}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

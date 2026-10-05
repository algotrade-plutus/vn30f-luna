"""Dependency-free HTTP server for sanitized PaperTrade snapshots."""

from __future__ import annotations

import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

DATA_DIR = Path(os.getenv("DASHBOARD_DATA_DIR", "/data"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_SNAPSHOT_BYTES = 1_000_000
MAX_ACTIVITY_READ_BYTES = 1_000_000
MAX_ACTIVITY_EVENT_BYTES = 64_000
ACTIVITY_FIELDS = {
    "status", "healthy", "mode", "alpha", "symbol", "order_gate",
    "configured_qty", "desired_qty", "positions", "reasons",
    "fix_logged_on", "worker_alive", "last_error",
}


def read_json(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return {"status": "unavailable", "error": "snapshot_too_large"}
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"status": "unavailable"}
    return value if isinstance(value, dict) else {"status": "unavailable"}


def read_activity(path: Path, *, limit: int = 50) -> list[dict]:
    if not 1 <= limit <= 200:
        raise ValueError("activity limit must be in [1, 200]")
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            start = max(0, size - MAX_ACTIVITY_READ_BYTES)
            handle.seek(start)
            if start:
                handle.readline()  # discard a partial first line
            lines = handle.readlines()
    except OSError:
        return []
    result = []
    for raw in lines[-limit:]:
        if len(raw) > MAX_ACTIVITY_EVENT_BYTES:
            continue
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
        safe_payload = {}
        for name in ("state", "changed"):
            source = payload.get(name)
            if isinstance(source, dict):
                safe_payload[name] = {
                    key: item for key, item in source.items() if key in ACTIVITY_FIELDS
                }
        result.append({
            key: value.get(key)
            for key in (
                "schema_version", "sequence", "timestamp", "runtime_instance_id",
                "release_id", "type",
            )
        } | {"payload": safe_payload})
    return result


def status_payload() -> dict:
    return {
        "server_time": time.time(),
        "health": read_json(DATA_DIR / "health.json"),
        "account": read_json(DATA_DIR / "account.json"),
        "activity": read_activity(DATA_DIR / "activity.jsonl"),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SteadyFoxDashboard/1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._send_bytes(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                (STATIC_DIR / "index.html").read_bytes(),
            )
            return
        if path == "/api/status":
            self._send_json(HTTPStatus.OK, status_payload())
            return
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read_only"})

    def _send_json(self, status: HTTPStatus, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        # SSM is the only intended caller; avoid noisy access logs.
        return


def main() -> None:
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

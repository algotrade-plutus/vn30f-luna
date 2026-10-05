#!/usr/bin/env python3
"""Container runtime modes. Default `hold` is deliberately non-trading."""

from __future__ import annotations

import importlib
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from algotrade_adapter.runtime_observability import ActivityRecorder, load_release_identity

HEALTH = Path("/app/runtime/health.json")
STOP = False
RELEASE = load_release_identity()
ACTIVITY = ActivityRecorder(release=RELEASE)


def heartbeat(status: str, **extra) -> None:
    HEALTH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEALTH.with_suffix(".tmp")
    payload = {
        "status": status,
        "updated_at": time.time(),
        **extra,
        "runtime_instance_id": ACTIVITY.runtime_instance_id,
        "release": RELEASE,
        "observability_error": ACTIVITY.last_write_error,
    }
    tmp.write_text(json.dumps(payload))
    tmp.replace(HEALTH)
    ACTIVITY.observe(payload)


def stop_handler(signum, frame) -> None:
    global STOP
    STOP = True


def load_factory(spec: str):
    module_name, sep, function_name = spec.partition(":")
    if not sep:
        raise ValueError("ALPHA_FACTORY must be module:function")
    return getattr(importlib.import_module(module_name), function_name)


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("kafka").setLevel(
        getattr(logging, os.getenv("KAFKA_LOG_LEVEL", "WARNING").upper(), logging.WARNING)
    )
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    mode = os.getenv("PAPERTRADING_MODE", "hold").lower()
    heartbeat("starting", mode=mode)

    if mode == "hold":
        # Safe deployment can prove process supervision before an alpha exists.
        while not STOP:
            heartbeat("healthy", mode=mode, order_gate=os.getenv("PAPERBROKER_ALLOW_ORDERS", "false"))
            time.sleep(10)
        heartbeat("stopped", mode=mode)
        return 0

    if mode == "alpha":
        factory = load_factory(os.environ["ALPHA_FACTORY"])
        alpha = factory()
        worker_error = []

        def run_alpha() -> None:
            try:
                alpha.run()
            except BaseException as exc:
                worker_error.append(exc)

        worker = threading.Thread(
            target=run_alpha,
            name=f"runtime.{type(alpha).__name__}",
            daemon=True,
        )
        worker.start()
        while worker.is_alive() and not STOP:
            extra = {}
            snapshot = getattr(alpha, "health_snapshot", None)
            if callable(snapshot):
                extra = dict(snapshot())
            for reserved in (
                "status", "mode", "alpha", "updated_at", "release",
                "runtime_instance_id", "observability_error",
            ):
                extra.pop(reserved, None)
            status = "running" if extra.get("healthy", True) else "degraded"
            heartbeat(status, mode=mode, alpha=type(alpha).__name__, **extra)
            time.sleep(10)

        if STOP and worker.is_alive():
            alpha.stop()
        worker.join(timeout=30)
        if worker.is_alive():
            raise RuntimeError(f"{type(alpha).__name__} did not stop within 30 seconds")
        if worker_error:
            raise RuntimeError(f"{type(alpha).__name__} failed") from worker_error[0]
        if not STOP:
            raise RuntimeError(f"{type(alpha).__name__} stopped unexpectedly")
        heartbeat("stopped", mode=mode, alpha=type(alpha).__name__)
        return 0

    raise ValueError(f"Unsupported PAPERTRADING_MODE={mode!r}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        heartbeat("failed", error_type=type(exc).__name__)
        print(f"runtime failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

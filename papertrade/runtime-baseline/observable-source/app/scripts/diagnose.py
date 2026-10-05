#!/usr/bin/env python3
"""Local dependency/config diagnostics. Never prints secret values."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

REQUIRED_FIX = (
    "PAPER_ACCOUNT_ID", "PAPER_USERNAME", "PAPER_PASSWORD",
    "PAPER_REST_BASE_URL", "SOCKET_HOST", "SOCKET_PORT",
    "SENDER_COMP_ID", "TARGET_COMP_ID",
)
REQUIRED_KAFKA = (
    "PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS",
    "PAPERBROKER_KAFKA_USERNAME",
    "PAPERBROKER_KAFKA_PASSWORD",
    "PAPERBROKER_ENV_ID",
    "VN30F1M",
)


def status(names: tuple[str, ...]) -> str:
    missing = [name for name in names if not os.getenv(name, "").strip()]
    return "ready" if not missing else "missing: " + ", ".join(missing)


def main() -> int:
    try:
        version = importlib.metadata.version("paperbroker-client")
    except importlib.metadata.PackageNotFoundError:
        version = "not installed"
    try:
        import quickfix  # noqa: F401
        quickfix_status = "available"
    except Exception as exc:
        quickfix_status = f"unavailable ({type(exc).__name__})"
    print(f"python={sys.version.split()[0]} os={platform.system()} arch={platform.machine()}")
    print(f"paperbroker-client={version} quickfix={quickfix_status}")
    print(f"FIX/REST config: {status(REQUIRED_FIX)}")
    print(f"Kafka config: {status(REQUIRED_KAFKA)}")
    print("order gate:", os.getenv("PAPERBROKER_ALLOW_ORDERS", "false").lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

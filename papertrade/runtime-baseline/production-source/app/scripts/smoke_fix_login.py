#!/usr/bin/env python3
"""FIX login + read-only account query. This script never places orders."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")


def main() -> int:
    from algotrade_adapter import build_client

    client = build_client(ROOT / ".env", enable_fix=True)
    code = 1
    try:
        client.connect()
        if not client.wait_until_logged_on(timeout=10):
            print(f"FIX login failed: {client.last_logon_error()}", flush=True)
            return 1
        cash = client.get_cash_balance()
        print(
            "FIX login OK; REST cash query success=" + str(bool(cash)),
            flush=True,
        )
        code = 0
        return code
    finally:
        # QuickFIX Python can segfault during interpreter cleanup on macOS.
        # os._exit mirrors the official example, after flushing output.
        os._exit(code)


if __name__ == "__main__":
    main()

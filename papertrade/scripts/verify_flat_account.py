#!/usr/bin/env python3
"""Verify through REST that every position is flat and no order is working.

Output is intentionally limited to booleans and counts. The script never
prints account identifiers, credentials, broker payloads, symbols, or values.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

TERMINAL = {
    "2", "4", "8", "C", "FILLED", "CANCELED", "CANCELLED",
    "REJECTED", "EXPIRED", "DONEFORDAY", "DONE_FOR_DAY",
}


def terminal_order(item: dict[str, Any]) -> bool:
    for key in ("ordStatus", "status", "statusText"):
        status = str(item.get(key) or "").upper().replace(" ", "")
        if status in TERMINAL:
            return True
        if status.endswith((
            "FULLYFILLED", "CANCELED", "CANCELLED", "REJECTED",
            "EXPIRED", "DONEFORDAY", "CANCELEDSUCCESSFULLY",
            "CANCELLEDSUCCESSFULLY",
        )):
            return True
    return False


def verified_counts(portfolio: Any, orders: Any) -> tuple[int, int]:
    if not isinstance(portfolio, dict) or portfolio.get("success") is not True:
        raise RuntimeError("portfolio_unavailable")
    if not isinstance(orders, dict) or orders.get("success") is not True:
        raise RuntimeError("orders_unavailable")
    position_rows = portfolio.get("items")
    order_rows = orders.get("items")
    if not isinstance(position_rows, list) or not isinstance(order_rows, list):
        raise RuntimeError("invalid_broker_response")
    nonflat = 0
    for item in position_rows:
        if not isinstance(item, dict):
            raise RuntimeError("invalid_position")
        raw = item.get("quantity", item.get("qty"))
        if raw is None:
            raise RuntimeError("position_quantity_unknown")
        try:
            quantity = float(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("position_quantity_invalid") from exc
        nonflat += quantity != 0
    working = 0
    for item in order_rows:
        if not isinstance(item, dict):
            raise RuntimeError("invalid_order")
        if not terminal_order(item):
            working += 1
    return nonflat, working


def main() -> int:
    os.environ["PAPERBROKER_ALLOW_ORDERS"] = "false"
    from algotrade_adapter import build_client

    try:
        client = build_client(enable_fix=False, allow_orders=False)
        today = datetime.now().date()
        portfolio = client.get_portfolio_by_sub()
        orders = client.get_orders(
            (today - timedelta(days=30)).isoformat(), today.isoformat()
        )
        nonflat, working = verified_counts(portfolio, orders)
    except BaseException as exc:
        print(json.dumps({
            "status": "unknown",
            "error_type": type(exc).__name__,
        }, separators=(",", ":")))
        return 2
    result = {
        "status": "verified",
        "flat": nonflat == 0,
        "nonflat_positions": nonflat,
        "working_orders": working,
        "order_gate": False,
    }
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["flat"] and working == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

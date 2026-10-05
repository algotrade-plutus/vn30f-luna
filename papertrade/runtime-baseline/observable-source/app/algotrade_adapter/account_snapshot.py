"""Write a strictly whitelisted, credential-free account snapshot."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

HCM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _number(value: Any) -> Optional[float | int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _text(value: Any, limit: int = 160) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip()[:limit] or None


def _pick_number(row: Dict[str, Any], *names: str) -> Optional[float | int]:
    for name in names:
        value = _number(row.get(name))
        if value is not None:
            return value
    return None


def _pick_text(row: Dict[str, Any], *names: str) -> Optional[str]:
    for name in names:
        value = _text(row.get(name))
        if value is not None:
            return value
    return None


def _limited(items: Any, limit: int) -> Iterable[Dict[str, Any]]:
    if not isinstance(items, list):
        return ()
    return (item for item in items[-limit:] if isinstance(item, dict))


def _position(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "instrument": _pick_text(row, "instrument", "symbol"),
        "quantity": _pick_number(row, "quantity", "qty"),
        "avg_price": _pick_number(row, "avgPrice", "averagePrice"),
        "current_price": _pick_number(row, "currentPrice", "marketPrice"),
        "total_cost": _pick_number(row, "totalCost", "cost"),
        "market_value": _pick_number(row, "marketValue"),
        "pnl": _pick_number(row, "pnl", "unrealizedPnl"),
    }


def _order(row: Dict[str, Any]) -> Dict[str, Any]:
    side = _pick_text(row, "side")
    side = {"1": "BUY", "2": "SELL"}.get(side or "", side)
    return {
        "order_id": _pick_text(row, "orderId"),
        "client_order_id": _pick_text(row, "clOrdId"),
        "symbol": _pick_text(row, "symbol", "instrument"),
        "side": side,
        "quantity": _pick_number(row, "orderQty", "quantity"),
        "filled_quantity": _pick_number(row, "cumQty", "filledQuantity"),
        "leaves_quantity": _pick_number(row, "leavesQty"),
        "price": _pick_number(row, "price"),
        "avg_fill_price": _pick_number(row, "avgPx", "avgFillPrice"),
        "status": _pick_text(row, "statusText", "ordStatus", "status"),
        "order_date": _pick_text(row, "orderDate", "createdAt"),
        "last_update": _pick_text(row, "lastUpdateDate", "updatedAt"),
    }


def _transaction(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "order_id": _pick_text(row, "orderId"),
        "symbol": _pick_text(row, "symbol", "instrument"),
        "side": _pick_text(row, "type", "side"),
        "quantity": _pick_number(row, "quantity", "qty"),
        "price": _pick_number(row, "price"),
        "fee": _pick_number(row, "totalFee", "fee"),
        "time": _pick_text(row, "transactionDate", "createdAt", "time"),
    }


class AccountSnapshotExporter:
    """Poll REST with a dedicated read-only client and atomically export JSON."""

    def __init__(
        self,
        client: Any,
        path: Path,
        *,
        lookback_days: int = 7,
        item_limit: int = 100,
    ) -> None:
        self.client = client
        self.path = path
        self.lookback_days = lookback_days
        self.item_limit = item_limit

    def collect(
        self,
        *,
        symbol: str,
        latest_price: Optional[float],
        target_qty: int,
    ) -> Dict[str, Any]:
        local_now = datetime.now(HCM_TZ)
        end = local_now.date()
        start = end - timedelta(days=self.lookback_days)
        errors: list[str] = []

        cash = self._call("cash", self.client.get_cash_balance, errors)
        total = self._call("balance", self.client.get_account_balance, errors)
        portfolio = self._call("portfolio", self.client.get_portfolio_by_sub, errors)
        orders = self._call(
            "orders",
            lambda: self.client.get_orders(start.isoformat(), end.isoformat()),
            errors,
        )
        transactions = self._call(
            "transactions",
            lambda: self.client.get_transactions_by_date(start.isoformat(), end.isoformat()),
            errors,
        )
        capacity: Dict[str, Any] = {}
        if latest_price is not None:
            capacity = self._call(
                "capacity",
                lambda: self.client.get_max_placeable(symbol, latest_price, "BUY"),
                errors,
            )

        positions = [_position(row) for row in _limited(portfolio.get("items"), self.item_limit)]
        clean_orders = [_order(row) for row in _limited(orders.get("items"), self.item_limit)]
        clean_transactions = [
            _transaction(row)
            for row in _limited(transactions.get("items"), self.item_limit)
        ]
        snapshot = {
            "schema_version": 1,
            "updated_at": time.time(),
            "status": "healthy" if not errors else "partial",
            "errors": errors,
            "account": {
                "remain_cash": _pick_number(cash, "remainCash"),
                "total_balance": _pick_number(total, "totalBalance"),
                "derivative_margin_ratio": _pick_number(portfolio, "derivativeMargin"),
                "equity_margin_ratio": _pick_number(portfolio, "equityMargin"),
            },
            "risk": {
                "symbol": symbol,
                "latest_price": _number(latest_price),
                "target_qty": target_qty,
                "max_buy_qty": _pick_number(capacity, "maxQty"),
                "per_unit_cost": _pick_number(capacity, "perUnitCost"),
                "remain_cash": _pick_number(capacity, "remainCash"),
            },
            "positions": positions,
            "orders": clean_orders,
            "transactions": clean_transactions,
        }
        self.write(snapshot)
        return snapshot

    @staticmethod
    def _call(name: str, fn: Any, errors: list[str]) -> Dict[str, Any]:
        try:
            result = fn()
        except Exception:
            errors.append(f"{name}_unavailable")
            return {}
        if not isinstance(result, dict):
            errors.append(f"{name}_unavailable")
            return {}
        valid = {
            "cash": result.get("remainCash") is not None,
            "balance": result.get("totalBalance") is not None,
            "portfolio": result.get("success") is True and isinstance(result.get("items"), list),
            "orders": result.get("success") is True and isinstance(result.get("items"), list),
            "transactions": result.get("success") is True and isinstance(result.get("items"), list),
            "capacity": result.get("success") is True and result.get("maxQty") is not None,
        }.get(name, bool(result))
        if not valid:
            errors.append(f"{name}_unavailable")
        return result

    def write(self, snapshot: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.path)

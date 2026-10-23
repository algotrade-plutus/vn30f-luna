"""The only door to PaperTrade (paperbroker-client 0.2.8) for the Calibrum runtime.

Every method is written out; nothing is forwarded to the raw client, so the
order gate covers every call that can change the account (REBUILD_NOTES #15).
REST is the source of truth for position, cash and working orders; FIX only
places and cancels.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import MethodType
from typing import Any

from .execution import Account, Order, tick

TERMINAL = {"Filled", "Canceled", "Rejected", "Expired", "DoneForDay"}
# How far along an order is; a later stage always replaces an earlier one.
STAGE = {"PendingNew": 0, "New": 1, "PendingCancel": 1, "PartiallyFilled": 2, **{status: 3 for status in TERMINAL}}


class OrderGateClosed(RuntimeError):
    """Raised when an order or cancel is attempted while the gate is closed."""


class BrokerError(RuntimeError):
    """A REST answer we cannot read: never treated as an empty account."""


def _patch_fix_logon(raw: Any) -> None:
    """paperbroker 0.2.8 reads an empty MsgType and skips Password(554) on Logon (REBUILD_NOTES #11)."""
    engine = getattr(raw, "_engine", None)
    if engine is None:
        return
    import quickfix as fix

    def inject(self, message, session_id) -> None:
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)
        if msg_type.getString() == fix.MsgType_Logon:
            message.setField(fix.Password(self._password))
            message.setField(fix.EncryptMethod(0))
            message.setField(fix.HeartBtInt(30))
        message.setField(fix.Username(self._username))
        message.setField(fix.Account(self._sub_provider.current()))

    engine._inject_admin_credentials = MethodType(inject, engine)


def _patch_fill_ordering(raw: Any) -> None:
    """Keep fills the SDK would drop (REBUILD_NOTES #23).

    The SDK applies an ExecutionReport only if its TransactTime is newer than the
    last one. PaperTrade stamps a fill with the market tick's whole second, which
    is often earlier than the New ack, so the fill was discarded and the order
    stayed New with no fill. A report that moves the order to a later stage now
    always applies.
    """
    manager = getattr(raw, "orders", None)
    if manager is None or not hasattr(manager, "_update_status"):
        return
    original = manager._update_status

    def update(cl_ord_id: str, status: str, at: datetime, **kwargs: Any) -> None:
        prev = manager.status_map.get(cl_ord_id)
        if prev is not None and at <= prev["time"] and STAGE.get(status, 0) > STAGE.get(prev.get("status"), 0):
            at = prev["time"] + timedelta(microseconds=1)
        original(cl_ord_id, status, at, **kwargs)

    manager._update_status = update


def _symbol(raw: Any) -> str:
    value = str(raw or "").strip()
    return value if ":" in value else f"HNXDS:{value}"


class Broker:
    def __init__(self, raw: Any, symbol: str, allow_orders: bool) -> None:
        self.raw = raw
        self.symbol = symbol
        self.allow_orders = allow_orders

    @classmethod
    def from_env(cls, symbol: str, allow_orders: bool, state_dir: Path, enable_fix: bool = True) -> "Broker":
        from paperbroker import PaperBrokerClient

        env = os.environ
        state_dir.mkdir(parents=True, exist_ok=True)
        raw = PaperBrokerClient(
            default_sub_account=env["PAPER_ACCOUNT_ID"],
            username=env["PAPER_USERNAME"],
            password=env["PAPER_PASSWORD"],
            rest_base_url=env["PAPER_REST_BASE_URL"],
            socket_connect_host=env["SOCKET_HOST"],
            socket_connect_port=int(env["SOCKET_PORT"]),
            sender_comp_id=env["SENDER_COMP_ID"],
            target_comp_id=env["TARGET_COMP_ID"],
            # One order store per day, so yesterday's orders cannot cause cancel rejects (REBUILD_NOTES #9).
            order_store_path=str(state_dir / f"orders-{datetime.now():%Y%m%d}.db"),
            log_dir=str(state_dir / "logs"),
            enable_fix=enable_fix,
            fix_message_log=False,
        )
        if enable_fix:
            _patch_fix_logon(raw)
            _patch_fill_ordering(raw)
        return cls(raw, symbol, allow_orders)

    # Session

    def connect(self, timeout: float = 20.0) -> bool:
        self.raw.connect()
        return bool(self.raw.wait_until_logged_on(timeout=timeout))

    def disconnect(self) -> None:
        self.raw.disconnect()

    def logged_on(self) -> bool:
        return bool(self.raw.is_logged_on())

    # REST reads

    def positions(self) -> dict[str, int]:
        payload = self.raw.get_portfolio_by_sub()
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise BrokerError("portfolio unavailable")
        out: dict[str, int] = {}
        for item in payload.get("items", []):
            quantity = int(float(item.get("quantity", item.get("openQuantity", 0)) or 0))
            if quantity:
                out[_symbol(item.get("instrument") or item.get("symbol"))] = quantity
        return out

    def remain_cash(self) -> float:
        payload = self.raw.get_cash_balance()
        if not isinstance(payload, dict) or payload.get("remainCash") is None:
            raise BrokerError("cash balance unavailable")
        return float(payload["remainCash"])

    def working_orders(self) -> list[dict[str, Any]]:
        today = datetime.now().date()
        payload = self.raw.get_orders((today - timedelta(days=1)).isoformat(), today.isoformat())
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise BrokerError("orders unavailable")
        working = []
        for item in payload.get("items", []):
            status = str(item.get("statusText") or item.get("ordStatus") or item.get("status") or "").upper()
            done = any(word in status for word in ("FILL", "CANCEL", "REJECT", "EXPIRE"))
            if float(item.get("leavesQty", 0) or 0) > 0 and not done:
                working.append(item)
        return working

    def account(self) -> Account:
        """Position in the managed symbol; any other open symbol is an error the operator must clear."""
        held = self.positions()
        foreign = sorted(symbol for symbol in held if symbol != self.symbol)
        if foreign:
            raise BrokerError(f"positions outside {self.symbol}: {foreign}")
        return Account(held.get(self.symbol, 0), self.remain_cash(), len(self.working_orders()))

    def max_placeable(self, side: str, price: float) -> int:
        payload = self.raw.get_max_placeable(self.symbol, price, side)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return 0
        if payload.get("unlimited"):
            return 10**6
        return int(float(payload.get("maxQty", 0) or 0))

    # FIX, behind the gate

    def place(self, order: Order) -> str:
        if not self.allow_orders:
            raise OrderGateClosed("order gate is closed")
        if order.side not in {"BUY", "SELL"} or int(order.qty) != order.qty or order.qty <= 0:
            raise ValueError(f"invalid order {order}")
        return self.raw.place_order(
            full_symbol=self.symbol, side=order.side, qty=int(order.qty), price=tick(order.price),
            ord_type="LIMIT", tif="DAY",
        )

    def cancel(self, cl_ord_id: str, timeout: float = 5.0) -> tuple[bool, str]:
        """Cancel and wait for a terminal state. After a cancel reject the SDK may mark a filled
        order Rejected with no fill (REBUILD_NOTES #23): read the outcome from REST, not from here."""
        if not self.allow_orders:
            raise OrderGateClosed("order gate is closed")
        terminal, status = self.raw.cancel_order(cl_ord_id, timeout=timeout)
        if not terminal:
            status = self.wait(cl_ord_id, timeout)
        return status in TERMINAL, str(status)

    def wait(self, cl_ord_id: str, timeout: float, statuses: set[str] = TERMINAL) -> str:
        """Status once it is in ``statuses`` or ``timeout`` has passed.

        The SDK's wait_for wakes on any status change (PendingNew -> New), not on the
        ones asked for, so it is called in a loop (REBUILD_NOTES #23).
        """
        deadline = time.monotonic() + timeout
        while True:
            status = str(self.raw.get_order_status(cl_ord_id))
            left = deadline - time.monotonic()
            if status in statuses or left <= 0:
                return status
            self.raw.wait_for(cl_ord_id, statuses, timeout=min(0.2, left))

    def filled(self, cl_ord_id: str) -> int:
        return int(self.raw.get_order_cumqty(cl_ord_id) or 0)

    def reject_text(self, cl_ord_id: str) -> str | None:
        return self.raw.get_order_text(cl_ord_id)

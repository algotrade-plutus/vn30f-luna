"""Validated boundary around paperbroker-client 0.2.8."""

from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import MethodType
from typing import Any, Callable, Optional

from dotenv import load_dotenv


class OrderBlockedError(RuntimeError):
    """Raised while the explicit paper-order safety gate is closed."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value


def _round_tick(value: float, tick: str = "0.1") -> float:
    quantum = Decimal(tick)
    return float((Decimal(str(value)) / quantum).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * quantum)


class ValidatedPaperClient:
    """Composition wrapper that rejects the client's silent fallbacks."""

    def __init__(
        self,
        raw_client: Any,
        *,
        allow_orders: bool = False,
        submit_authorizer: Callable[[], bool] | None = None,
    ) -> None:
        self.raw = raw_client
        self.allow_orders = allow_orders
        self.submit_authorizer = submit_authorizer

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    def place_order(
        self,
        full_symbol: str,
        side: str,
        qty: int,
        price: Optional[float],
        ord_type: str = "LIMIT",
        tif: str = "DAY",
    ) -> str:
        dynamically_allowed = (
            True if self.submit_authorizer is None else bool(self.submit_authorizer())
        )
        if not self.allow_orders or not dynamically_allowed:
            raise OrderBlockedError(
                "Order gate is closed by static or runtime authorization"
            )
        if ":" not in full_symbol:
            raise ValueError("full_symbol must include exchange prefix, e.g. HNXDS:VN30F2609")
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        ord_type = ord_type.upper()
        if ord_type not in {"LIMIT", "MARKET"}:
            raise ValueError("ord_type must be LIMIT or MARKET; unknown values become MARKET upstream")
        if tif.upper() != "DAY":
            raise ValueError("PaperTrade venue accepts DAY only")
        if isinstance(qty, bool) or int(qty) != qty or qty <= 0:
            raise ValueError("qty must be a positive integer")
        if price is None:
            raise ValueError("paperbroker 0.2.8 requires a numeric reference price, including MARKET")

        return self.raw.place_order(
            full_symbol=full_symbol,
            side=side,
            qty=int(qty),
            price=_round_tick(price),
            ord_type=ord_type,
            tif="DAY",
        )


def _patch_fix_logon_injection(raw_client: Any) -> None:
    """Fix paperbroker 0.2.8's incorrect QuickFIX MsgType read.

    QuickFIX mutates the field object passed to ``getField``. Depending on the
    binding build, the returned FieldBase can be empty. Upstream reads that
    return value and therefore skips Password(554) on Logon.
    """
    engine = getattr(raw_client, "_engine", None)
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
        # Never stringify this message: it now contains Password(554).
        self.logger.debug("Injected FIX admin fields for msg_type=%s", msg_type.getString())

    engine._inject_admin_credentials = MethodType(inject, engine)


def build_client(
    env_path: Optional[Path] = None,
    *,
    enable_fix: Optional[bool] = None,
    order_store_path: Optional[Path] = None,
    allow_orders: Optional[bool] = None,
    submit_authorizer: Callable[[], bool] | None = None,
) -> ValidatedPaperClient:
    """Build a fail-closed client from the local secret configuration."""
    if env_path is None:
        env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path, override=False)

    from paperbroker import PaperBrokerClient

    Path("runtime").mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)

    if order_store_path is None:
        order_store_path = Path("runtime") / "orders.db"
    raw = PaperBrokerClient(
        default_sub_account=_required("PAPER_ACCOUNT_ID"),
        username=_required("PAPER_USERNAME"),
        password=_required("PAPER_PASSWORD"),
        rest_base_url=_required("PAPER_REST_BASE_URL"),
        socket_connect_host=_required("SOCKET_HOST"),
        socket_connect_port=int(_required("SOCKET_PORT")),
        sender_comp_id=_required("SENDER_COMP_ID"),
        target_comp_id=_required("TARGET_COMP_ID"),
        order_store_path=str(order_store_path),
        log_dir="logs",
        enable_fix=enable_fix,
        fix_message_log=False,
    )
    _patch_fix_logon_injection(raw)
    allow = (
        os.getenv("PAPERBROKER_ALLOW_ORDERS", "false").lower() == "true"
        if allow_orders is None
        else bool(allow_orders)
    )
    return ValidatedPaperClient(
        raw,
        allow_orders=allow,
        submit_authorizer=submit_authorizer,
    )

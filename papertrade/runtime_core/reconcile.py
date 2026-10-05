"""Pure account reconciliation primitives shared by trading runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


TERMINAL_ORDER_STATES = {
    "2", "4", "8", "C", "CANCELED", "CANCELLED", "DONEFORDAY",
    "DONE_FOR_DAY", "EXPIRED", "FILLED", "REJECTED",
}


def normalize_symbol(raw: Any) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return value if ":" in value else f"HNXDS:{value}"


def order_is_terminal(item: Mapping[str, Any]) -> bool:
    for raw in (item.get("ordStatus"), item.get("status"), item.get("statusText")):
        status = str(raw or "").upper().replace(" ", "").replace("_", "").replace("-", "")
        if status in TERMINAL_ORDER_STATES:
            return True
        if "PARTIALLY" not in status and (
            status.endswith("FULLYFILLED")
            or "WASCANCELED" in status
            or "WASCANCELLED" in status
        ):
            return True
    return False


@dataclass(frozen=True)
class ReconcileSnapshot:
    positions: Mapping[str, int]
    working_orders: tuple[Mapping[str, Any], ...]
    foreign_positions: tuple[str, ...]
    malformed_positions: int
    malformed_orders: int

    @property
    def known(self) -> bool:
        return self.malformed_positions == 0 and self.malformed_orders == 0

    @property
    def flat(self) -> bool | None:
        if not self.known:
            return None
        return not any(self.positions.values())


def _rows(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        for key in ("data", "items", "positions", "orders"):
            rows = value.get(key)
            if isinstance(rows, list):
                return rows
    return (value,)


def reconcile_account(
    position_payload: Any,
    order_payload: Any,
    *,
    managed_symbols: Iterable[str],
) -> ReconcileSnapshot:
    managed = set(managed_symbols)
    positions: dict[str, int] = {}
    malformed_positions = 0
    for row in _rows(position_payload):
        if not isinstance(row, Mapping):
            malformed_positions += 1
            continue
        symbol = normalize_symbol(
            row.get("instrument") or row.get("symbol") or row.get("stockCode")
        )
        raw_qty = row.get(
            "quantity",
            row.get("openQuantity", row.get("qty", row.get("netQty"))),
        )
        try:
            qty = int(float(raw_qty))
        except (TypeError, ValueError):
            malformed_positions += 1
            continue
        if symbol and qty:
            positions[symbol] = positions.get(symbol, 0) + qty

    working: list[Mapping[str, Any]] = []
    malformed_orders = 0
    for row in _rows(order_payload):
        if not isinstance(row, Mapping):
            malformed_orders += 1
            continue
        if not order_is_terminal(row):
            working.append(row)

    foreign = tuple(sorted(symbol for symbol, qty in positions.items() if qty and symbol not in managed))
    return ReconcileSnapshot(
        positions=positions,
        working_orders=tuple(working),
        foreign_positions=foreign,
        malformed_positions=malformed_positions,
        malformed_orders=malformed_orders,
    )

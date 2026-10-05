"""Fail-closed runtime control decisions independent of broker and strategy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class ControlState(str, Enum):
    OBSERVE = "OBSERVE"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    HALTED = "HALTED"
    FLATTENING = "FLATTENING"


@dataclass(frozen=True)
class ControlDecision:
    allowed: bool
    state: ControlState
    reason: str
    generation: int | None = None


class ControlGate:
    """Evaluate an operator-owned control record at the final submit boundary.

    Missing or malformed records fail closed.  This class only decides whether
    submission is authorized; cancel and flatten remain separate capabilities.
    """

    def __init__(
        self,
        path: Path,
        *,
        release_id: str,
        config_hash: str,
        quantity: int,
        static_gate: bool,
    ) -> None:
        self.path = path
        self.release_id = release_id
        self.config_hash = config_hash
        self.quantity = quantity
        self.static_gate = static_gate

    def decision(self) -> ControlDecision:
        if not self.static_gate:
            return ControlDecision(False, ControlState.OBSERVE, "static_order_gate_closed")
        try:
            value: Any = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return ControlDecision(False, ControlState.OBSERVE, "control_unavailable")
        if not isinstance(value, Mapping):
            return ControlDecision(False, ControlState.OBSERVE, "control_invalid")
        try:
            state = ControlState(str(value.get("state", "")))
        except ValueError:
            return ControlDecision(False, ControlState.OBSERVE, "control_state_invalid")
        generation = value.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            return ControlDecision(False, state, "control_generation_invalid")
        if state is not ControlState.ACTIVE:
            return ControlDecision(False, state, f"control_{state.value.lower()}", generation)
        expected = {
            "release_id": self.release_id,
            "config_hash": self.config_hash,
            "quantity": self.quantity,
        }
        for key, wanted in expected.items():
            if value.get(key) != wanted:
                return ControlDecision(False, state, f"authorization_{key}_mismatch", generation)
        if value.get("halt_latched") is True:
            return ControlDecision(False, ControlState.HALTED, "halt_latched", generation)
        return ControlDecision(True, state, "authorized", generation)

    def __call__(self) -> bool:
        return self.decision().allowed

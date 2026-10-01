"""Application Port: State Store interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IStateStore(ABC):
    """Interface for persisting and restoring strategy state across cycles/restarts."""

    @abstractmethod
    def save_state(self, key: str, state: dict[str, Any]) -> None:
        """Persist state dictionary."""
        ...

    @abstractmethod
    def load_state(self, key: str) -> dict[str, Any] | None:
        """Retrieve persisted state dictionary, or None if not found."""
        ...

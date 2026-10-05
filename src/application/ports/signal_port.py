"""Application Port: Signal / Strategy Gateway interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.entities.bar import Bar


class ISignalGateway(ABC):
    """Interface for evaluating strategy signals and returning target positions."""

    @abstractmethod
    def get_target_position(self, timestamp: datetime, bar: Bar | None = None) -> tuple[int, str]:
        """Return (target_position, reason_or_audit_note) for the specified timestamp or bar."""
        ...

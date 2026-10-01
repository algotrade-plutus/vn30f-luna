"""Market-data adapters.

The PostgreSQL driver is an optional runtime concern. Keep that import lazy
so importing this package does not open a database connection.
"""
from typing import Any

from .plutus_bar_source import PlutusBarSource, ReplayBar

__all__ = [
    "PlutusBarSource",
    "PostgresDepthSource",
    "PostgresResearchSource",
    "PostgresTickSource",
    "ReplayBar",
]


def __getattr__(name: str) -> Any:
    if name == "PostgresDepthSource":
        from .postgres_depth_source import PostgresDepthSource

        return PostgresDepthSource
    if name == "PostgresTickSource":
        from .postgres_tick_source import PostgresTickSource

        return PostgresTickSource
    if name == "PostgresResearchSource":
        from .postgres_research_source import PostgresResearchSource

        return PostgresResearchSource
    raise AttributeError(name)

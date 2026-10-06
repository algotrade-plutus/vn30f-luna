"""Market-data adapters.

The PostgreSQL driver is an optional runtime concern. Keep that import lazy
so importing this package does not open a database connection.
"""
from typing import Any

from .plutus_bar_source import PlutusBarSource, ReplayBar

__all__ = [
    "DnseCandleSource",
    "DnseDataError",
    "PlutusBarSource",
    "PostgresDepthSource",
    "PostgresResearchSource",
    "PostgresTickSource",
    "ReplayBar",
    "cache_path",
    "fetch_dnse_bars",
    "load_cached_bars",
    "load_or_fetch_dnse_bars",
    "normalize_bars",
    "payload_to_frame",
    "save_cached_bars",
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
    if name in {
        "DnseCandleSource",
        "DnseDataError",
        "cache_path",
        "fetch_dnse_bars",
        "load_cached_bars",
        "load_or_fetch_dnse_bars",
        "normalize_bars",
        "payload_to_frame",
        "save_cached_bars",
    }:
        from . import dnse_candle_source

        return getattr(dnse_candle_source, name)
    raise AttributeError(name)

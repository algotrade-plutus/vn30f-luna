"""Market-data adapters: DNSE candles and the minute-bar research base."""
from typing import Any

__all__ = [
    "add_front_month_contract",
    "align_to_bar_clock",
    "DnseCandleSource",
    "DnseDataError",
    "cache_path",
    "fetch_dnse_bars",
    "load_cached_bars",
    "load_or_fetch_dnse_bars",
    "normalize_bars",
    "payload_to_frame",
    "save_cached_bars",
]


def __getattr__(name: str) -> Any:
    if name in {
        "add_front_month_contract",
        "align_to_bar_clock",
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

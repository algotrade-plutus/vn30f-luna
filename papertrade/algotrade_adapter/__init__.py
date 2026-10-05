"""Lazy public adapter API: market calendar imports do not require a broker."""

from importlib import import_module


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(name)
    if name == "SafeSignalDrivenAlpha":
        module = "safe_alpha"
    elif name in {"PostgresSpotMarketDataClient", "SplitMarketDataClient", "build_market_data"}:
        module = "market_data"
    else:
        module = "client"
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "OrderBlockedError",
    "SafeSignalDrivenAlpha",
    "ValidatedPaperClient",
    "build_client",
    "SplitMarketDataClient",
    "PostgresSpotMarketDataClient",
    "build_market_data",
]

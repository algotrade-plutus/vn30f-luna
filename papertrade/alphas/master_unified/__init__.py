"""Single PaperTrade runtime for the HybridGated Luna profile."""

from importlib import import_module


def __getattr__(name):
    """Keep public service aliases without loading broker code for pure imports."""
    if name not in __all__:
        raise AttributeError(name)
    module = {"BarAggregator": "bar_aggregator", "SignalComposer": "signal_composer"}.get(
        name, "service"
    )
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "BarAggregator",
    "HybridGatedPaperAlpha",
    "HybridGatedSupervisor",
    "MasterUnifiedPaperAlpha",
    "MasterUnifiedSupervisor",
    "SignalComposer",
    "build_hybrid_gated_service",
    "build_unified_service",
]

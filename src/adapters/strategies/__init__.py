"""Adapters that expose signal outputs to the research runtime."""
from .calibrum_signal_source import (
    CalibrumSignalAdapter,
    CalibrumTargets,
    generate_calibrum_targets,
)

__all__ = [
    "CalibrumSignalAdapter",
    "CalibrumTargets",
    "generate_calibrum_targets",
]


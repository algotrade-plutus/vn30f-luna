"""Adapters that expose signal outputs to the research runtime."""
from .calibrum_signal_source import (
    CalibrumTargets,
    generate_calibrum_targets,
)

__all__ = [
    "CalibrumTargets",
    "generate_calibrum_targets",
]

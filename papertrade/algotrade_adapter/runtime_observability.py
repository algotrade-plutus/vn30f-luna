"""Compatibility imports for runtime observability.

New code imports :mod:`runtime_core.observability`.  This facade keeps existing
release tooling and external imports working during the migration.
"""

from runtime_core.observability import ActivityRecorder, load_release_identity

__all__ = ["ActivityRecorder", "load_release_identity"]

"""Compatibility facade for the shared pure market calendar.

The calendar belongs to the strategy/domain layer. Existing imports from the
adapter package remain valid during migration.
"""

from alphas.market_schedule import *  # noqa: F401,F403

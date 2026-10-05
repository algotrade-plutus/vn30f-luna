"""Shared FOMO predicate; readiness and hard-veto policy are profile-specific."""

from __future__ import annotations


def fomo_pump(
    distance: float,
    ret_2bar: float | None,
    ret_5bar: float | None,
    *,
    distance_threshold: float = 4.77,
    max_ret_2bar: float = 0.010,
    max_ret_5bar: float = 0.011,
) -> bool:
    if distance <= distance_threshold:
        return ret_5bar is not None and ret_5bar > max_ret_5bar
    return ret_2bar is not None and ret_2bar > max_ret_2bar

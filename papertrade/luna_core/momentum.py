"""One-bar T+2 transition. Indicators are computed by the owning adapter."""

from __future__ import annotations


def advance_t2(
    state: int,
    *,
    fast: float | None,
    slow: float | None,
    macro: float | None,
    close: float,
    average: float | None,
    long_threshold: float = 0.008,
    short_threshold: float = -0.010,
) -> tuple[int, tuple[str, ...]]:
    """No same-bar reversal; missing SMA leaves state and reason untouched.

    Research supplies NaN during rolling warmup; runtime supplies None. Both
    fail entry comparisons. Adapters retain their own arithmetic and readiness.
    """
    if average is None:
        return state, ()
    if state == 0:
        if fast is not None and slow is not None:
            if fast > long_threshold and slow > 0 and close > average:
                return 1, ("t2_momentum_long_entry",)
            if (
                fast < short_threshold
                and slow < 0
                and close < average
                and macro is not None
                and macro < 0
            ):
                return -1, ("t2_momentum_short_entry",)
        return 0, ()
    if state == 1:
        if fast is not None and fast < 0:
            return 0, ("t2_long_momentum_exhausted",)
        return 1, ("t2_hold_long",)
    if state == -1:
        if fast is not None and fast > 0:
            return 0, ("t2_short_momentum_exhausted",)
        return -1, ("t2_hold_short",)
    raise ValueError(f"Invalid T+2 state: {state}")

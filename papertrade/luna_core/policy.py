"""Calendar/T+2 priority; callers explicitly choose whether a veto is hard."""


def base_target(calendar: int, momentum: int, *, hard_flat: bool = False) -> int:
    if hard_flat:
        return 0
    return calendar if calendar != 0 else momentum

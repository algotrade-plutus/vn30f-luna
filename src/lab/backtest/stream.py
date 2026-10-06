"""Canonical validation for ``Datetime / Close / Position`` streams."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import BacktestConfig


REQUIRED_COLUMNS = ("Datetime", "Close", "Position")


def validate_position_stream(
    values: pd.DataFrame,
    config: BacktestConfig = BacktestConfig(),
) -> pd.DataFrame:
    aliases = {name.lower(): name for name in REQUIRED_COLUMNS}
    frame = values.rename(
        columns={column: aliases.get(str(column).lower(), column) for column in values}
    )
    missing = [column for column in REQUIRED_COLUMNS if column not in frame]
    if missing:
        raise ValueError(f"position stream missing {missing}")
    frame = frame.loc[:, REQUIRED_COLUMNS].copy()
    frame["Datetime"] = pd.to_datetime(frame.Datetime, errors="raise")
    if frame.Datetime.dt.tz is not None:
        raise ValueError("Datetime must be timezone-naive local time")
    frame["Close"] = pd.to_numeric(frame.Close, errors="raise").astype(float)
    frame["Position"] = (
        pd.to_numeric(frame.Position, errors="raise").fillna(0.0).astype(float)
    )
    if len(frame) < 2:
        raise ValueError("position stream must contain at least two bars")
    if frame.Datetime.duplicated().any():
        raise ValueError("Datetime must be unique")
    if not frame.Datetime.is_monotonic_increasing:
        raise ValueError("Datetime must be strictly chronological")
    if not np.isfinite(frame.Close).all() or (frame.Close <= 0.0).any():
        raise ValueError("Close must be finite and positive")
    if not np.isfinite(frame.Position).all():
        raise ValueError("Position must be finite")
    if config.require_discrete_position:
        distance = np.min(
            np.abs(frame.Position.to_numpy()[:, None] - np.asarray((-1.0, 0.0, 1.0))),
            axis=1,
        )
        if (distance > config.position_tolerance).any():
            invalid = sorted(frame.loc[distance > config.position_tolerance, "Position"].unique())
            raise ValueError(f"Position must remain discrete -1/0/+1; found {invalid}")
        frame["Position"] = frame.Position.round().astype(float)
    elif (frame.Position.abs() > 1.0 + config.position_tolerance).any():
        raise ValueError("Position must remain inside [-1, 1]")
    return frame.reset_index(drop=True)


__all__ = ["REQUIRED_COLUMNS", "validate_position_stream"]

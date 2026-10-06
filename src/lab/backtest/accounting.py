"""Vectorized bar accounting matching standard position timing and fees."""
from __future__ import annotations

import pandas as pd

from .config import BacktestConfig


def build_accounting_frame(
    stream: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    frame = stream.copy()
    frame["ExecutedPosition"] = frame.Position.shift(1).fillna(0.0)
    frame["PriceChange"] = frame.Close.diff().fillna(0.0)
    frame["GrossGain"] = frame.ExecutedPosition * frame.PriceChange
    frame["PositionChange"] = frame.Position.diff().fillna(frame.Position).abs()
    frame["FeeCost"] = frame.PositionChange * config.fee_per_position_unit
    frame["NetGain"] = frame.GrossGain - frame.FeeCost
    frame["GrossPnl"] = frame.GrossGain.cumsum()
    frame["NetPnl"] = frame.NetGain.cumsum()
    frame["GrossBarReturn"] = frame.GrossGain / frame.Close
    frame["NetBarReturn"] = frame.NetGain / frame.Close
    frame["GrossEquity"] = 1.0 + frame.GrossBarReturn.cumsum()
    frame["NetEquity"] = 1.0 + frame.NetBarReturn.cumsum()
    frame["SessionDate"] = frame.Datetime.dt.normalize()
    return frame


__all__ = ["build_accounting_frame"]

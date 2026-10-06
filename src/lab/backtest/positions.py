"""Build an auditable Position stream before any performance calculation."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import BacktestConfig
from .stream import validate_position_stream


@dataclass
class PositionStreamRecorder:
    """Chronological recorder for bar-by-bar execution simulators.

    A policy decides the target position on each canonical bar and records it
    here.  The resulting ``Position`` column is the source of truth; PnL and a
    diagnostic trade ledger are always derived from it afterwards.
    """

    config: BacktestConfig = field(default_factory=BacktestConfig)
    _rows: list[dict] = field(default_factory=list, init=False, repr=False)

    def append(
        self,
        datetime,
        close: float,
        position: float,
        reason: str = "",
    ) -> None:
        timestamp = pd.Timestamp(datetime)
        if self._rows and timestamp <= self._rows[-1]["Datetime"]:
            raise ValueError("position rows must be appended in strict chronology")
        self._rows.append(
            {
                "Datetime": timestamp,
                "Close": close,
                "Position": position,
                "PositionReason": reason,
            }
        )

    def to_frame(self) -> pd.DataFrame:
        if not self._rows:
            raise ValueError("cannot build an empty position stream")
        frame = pd.DataFrame(self._rows)
        validated = validate_position_stream(frame, self.config)
        validated["PositionReason"] = frame.PositionReason.to_numpy()
        return validated


def position_stream_from_commands(
    bars: pd.DataFrame,
    commands: pd.DataFrame,
    config: BacktestConfig = BacktestConfig(),
) -> pd.DataFrame:
    """Expand sparse target-position commands over canonical bars.

    ``commands`` must contain unique ``Datetime`` and ``Position`` values.  A
    command applies on that exact bar and remains active until the next one.
    With standard accounting it therefore earns from that bar's close to the
    next bar's close, never the already-known move into the signal bar.
    """

    required_bars = {"Datetime", "Close"}
    required_commands = {"Datetime", "Position"}
    if missing := required_bars.difference(bars.columns):
        raise ValueError(f"bars missing required columns: {sorted(missing)}")
    if missing := required_commands.difference(commands.columns):
        raise ValueError(f"commands missing required columns: {sorted(missing)}")

    base = bars.loc[:, ["Datetime", "Close"]].copy()
    base["Datetime"] = pd.to_datetime(base.Datetime)
    if base.Datetime.duplicated().any() or not base.Datetime.is_monotonic_increasing:
        raise ValueError("bars must have unique, increasing Datetime")

    sparse = commands.copy()
    sparse["Datetime"] = pd.to_datetime(sparse.Datetime)
    if sparse.Datetime.duplicated().any():
        raise ValueError("commands must contain at most one decision per Datetime")
    unknown = sparse.loc[~sparse.Datetime.isin(base.Datetime), "Datetime"]
    if len(unknown):
        raise ValueError(f"command timestamp is not a canonical bar: {unknown.iloc[0]}")

    extra = [column for column in sparse.columns if column not in {"Datetime", "Position"}]
    merged = base.merge(sparse, on="Datetime", how="left", validate="one_to_one")
    merged["Position"] = merged.Position.ffill().fillna(0.0)
    for column in extra:
        merged[column] = merged[column].fillna("")
    validated = validate_position_stream(merged, config)
    for column in extra:
        validated[column] = merged[column].to_numpy()
    return validated


__all__ = ["PositionStreamRecorder", "position_stream_from_commands"]

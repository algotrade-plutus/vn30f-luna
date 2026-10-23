"""Calibrum targets for a live minute stream, from the same code as the backtest.

Each call rebuilds the market from a short window and reads the last row of
each sleeve: every sleeve resets at the end of a contract, so the window only
needs the current contract plus a few sessions before it (Momentum features,
the Calendar entry at 14:20 of the session before Tuesday). Over 2021-2026 the
last row matches the full-history position at every sampled minute except in
sessions that lack index bars (tests/test_calibrum_live.py).

Parameters are frozen in config/calibrum_live.toml by
``scripts/run_calibrum_1m.py freeze-live``.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import pipeline
from .momentum import RidgeModel

LIVE_CONFIG = pipeline.WORKSPACE / "config" / "calibrum_live.toml"
LEAD_SESSIONS = 5


@dataclass(frozen=True)
class LiveParams:
    basis_window: int
    basis_z_entry: float
    momentum_theta: float
    model: RidgeModel


@dataclass(frozen=True)
class Targets:
    """Each sleeve's side and the vote, after the minute that closed before ``now``."""

    now: pd.Timestamp
    last_minute: pd.Timestamp
    contract: str
    calendar: int
    basis: int
    momentum: int
    vote: int


def load_params(path: Path = LIVE_CONFIG) -> LiveParams:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    model = raw["momentum"]["model"]
    return LiveParams(
        basis_window=int(raw["basis"]["window"]),
        basis_z_entry=float(raw["basis"]["z_entry"]),
        momentum_theta=float(raw["momentum"]["theta"]),
        model=RidgeModel(
            lam=float(model["lam"]),
            median=np.array(model["median"], dtype=float),
            iqr=np.array(model["iqr"], dtype=float),
            beta0=float(model["beta0"]),
            beta=np.array(model["beta"], dtype=float),
        ),
    )


def window(minutes: pd.DataFrame, index_minutes: pd.DataFrame, now: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Minutes closed before ``now``, from LEAD_SESSIONS sessions before the current contract began."""
    minutes = minutes[minutes["Datetime"] < now]
    contract = minutes["Contract"].iloc[-1]
    first_day = minutes.loc[minutes["Contract"] == contract, "Datetime"].iloc[0].normalize()
    sessions = minutes["Datetime"].dt.normalize().drop_duplicates()
    earlier = sessions[sessions < first_day]
    start = earlier.iloc[-LEAD_SESSIONS] if len(earlier) >= LEAD_SESSIONS else sessions.iloc[0]
    keep_futures = minutes[minutes["Datetime"] >= start].reset_index(drop=True)
    keep_index = index_minutes[(index_minutes["Datetime"] >= start) & (index_minutes["Datetime"] < now)]
    return keep_futures, keep_index.reset_index(drop=True)


def targets(minutes: pd.DataFrame, index_minutes: pd.DataFrame, now: pd.Timestamp, params: LiveParams) -> Targets:
    """Sleeve sides and vote from minutes closed before ``now``.

    ``minutes`` holds VN30F1M minute bars with Datetime, OHLCV and Contract;
    ``index_minutes`` the VN30 minute bars. Both are naive exchange time. A
    minute stamped t is closed once the clock passes t + 1 minute.
    """
    futures, index = window(minutes, index_minutes, now)
    market = pipeline.build_market(futures, index, now=now)
    calendar = pipeline.calendar_mtw_positions(market)[-1]
    basis = pipeline.basis_positions(market, params.basis_window, params.basis_z_entry)[-1]
    momentum = pipeline.momentum_positions(market, params.model, params.momentum_theta)[-1]
    return Targets(
        now=now,
        last_minute=futures["Datetime"].iloc[-1],
        contract=str(futures["Contract"].iloc[-1]),
        calendar=int(calendar),
        basis=int(basis),
        momentum=int(momentum),
        vote=int(np.sign(calendar + basis + momentum)),
    )

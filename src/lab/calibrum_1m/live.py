"""Calibrum targets for a live minute stream, from the same code as the backtest.

Each call rebuilds the market from a short window and reads the last row of
each sleeve: every sleeve resets at the end of a contract, so the window only
needs the current contract plus a few sessions before it (Momentum features,
the Calendar entry at 14:20 of the session before Tuesday). Over 2021-2026 the
last row matches the full-history position at every sampled minute except in
sessions that lack index bars (tests/test_calibrum_live.py).

Before the closing auction the live runtime decides one minute early: the
14:29 and 14:30 minutes are left out, so the bars that close the continuous
session (10-minute 14:20, 30-minute 14:00) close at the 14:28 minute and the
order still fills before 14:30. The backtest of that variant (C+B+M, total
407 against 425 million VND, OOS Sharpe 3.29 and 2.86 against 3.20 and 2.87)
is the reference the live runtime is held to.

Parameters are frozen in config/calibrum_live.toml by
``scripts/run_calibrum_1m.py freeze-live``.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import basis as basis_sleeve
from . import momentum as momentum_sleeve
from . import pipeline
from .grid import completes_bar
from .momentum import RidgeModel

LIVE_CONFIG = pipeline.WORKSPACE / "config" / "calibrum_live.toml"
LEAD_SESSIONS = 5
PRE_AUCTION_CUT = ("14:29", "14:30")


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
    # What the sides were decided from, for monitoring: the numbers of the last closed 30-minute bar.
    basis_z: float | None = None  # z on the window so far, also while warming up
    basis_bars: int = 0  # 30-minute bars of the current contract; Basis trades from basis_window
    momentum_score: float | None = None


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


def without_pre_auction(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the 14:29 and 14:30 minutes."""
    return frame[~frame["Datetime"].dt.strftime("%H:%M").isin(PRE_AUCTION_CUT)].reset_index(drop=True)


def decision_clock(now: pd.Timestamp) -> pd.Timestamp:
    """From 14:29 the next print that counts is the 14:45 auction, so the 14:28 minute closes its bars."""
    clock = now.time()
    if pd.Timestamp("14:29").time() <= clock < pd.Timestamp("14:45").time():
        return now.normalize() + pd.Timedelta(hours=14, minutes=31)
    return now


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
    futures, index = window(without_pre_auction(minutes), without_pre_auction(index_minutes), now)
    market = pipeline.build_market(futures, index, now=decision_clock(now))
    calendar = pipeline.calendar_mtw_positions(market)[-1]
    basis = pipeline.basis_positions(market, params.basis_window, params.basis_z_entry)[-1]
    momentum = pipeline.momentum_positions(market, params.model, params.momentum_theta)[-1]
    basis_z, basis_bars, momentum_score = _readings(market, params)
    return Targets(
        now=now,
        last_minute=futures["Datetime"].iloc[-1],
        contract=str(futures["Contract"].iloc[-1]),
        calendar=int(calendar),
        basis=int(basis),
        momentum=int(momentum),
        vote=int(np.sign(calendar + basis + momentum)),
        basis_z=basis_z,
        basis_bars=basis_bars,
        momentum_score=momentum_score,
    )


def _readings(market: pipeline.Market, params: LiveParams) -> tuple[float | None, int, float | None]:
    """At the last closed 30-minute bar: Basis z (also while warming up), the contract's bar count, the Momentum score."""
    labels = market.labels_30m
    closed = labels[completes_bar(labels, market.next_label(labels))]
    if closed.empty:
        return None, 0, None
    last = closed.iloc[-1]
    futures = market.futures_30m[market.futures_30m["Datetime"] <= last]
    bars = futures[futures["Contract"] == futures["Contract"].iloc[-1]]
    spot = market.index_30m[["Datetime", "Close"]].rename(columns={"Close": "Spot"})
    merged = pd.merge_asof(bars[["Datetime", "Close"]], spot, on="Datetime")
    spread = merged["Close"] - merged["Spot"]
    rolling = spread.rolling(params.basis_window, min_periods=basis_sleeve.MIN_PERIODS)
    z = ((spread - rolling.mean()) / (rolling.std() + 1e-6)).iloc[-1]
    features = momentum_sleeve.feature_frame(market.futures_30m_adjusted)
    features = features[features["Datetime"] <= last]
    scores = params.model.score(features[list(momentum_sleeve.FEATURES)].to_numpy(float))
    score = scores[-1] if len(scores) else np.nan
    as_float = lambda value: None if not np.isfinite(value) else round(float(value), 3)  # noqa: E731
    return as_float(z), int(len(bars)), as_float(score)

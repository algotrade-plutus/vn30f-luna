"""Place signal-bar decisions on the minute grid without look-ahead.

A signal bar's close is the close of its last minute row, so a decision made
on that bar takes effect from that row: the lab fills at the signal-bar close.

Live, the stream ends at the latest closed minute, whose bar may still be
running. ``next_label`` (the bar of the next print the market can make) tells
whether that last row closes its bar; without it the last row always does,
which is right for history.
"""
from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from src.domain.strategy.calendar_rules import is_expiry_thursday, is_trading_day, next_trading_day

MORNING_OPEN, MORNING_CLOSE = time(9, 0), time(11, 30)
AFTERNOON_OPEN, AFTERNOON_CLOSE = time(13, 0), time(14, 30)
ATC_PRINT = time(14, 45)


def next_print(now: pd.Timestamp) -> pd.Timestamp:
    """The first minute at or after ``now`` in which VN30F1M can print.

    Continuous trading runs 09:00-11:30 and 13:00-14:30; the closing auction
    prints once at 14:45.
    """
    day, clock = now.normalize(), now.time()
    if not is_trading_day(day.date()) or clock > ATC_PRINT:
        return pd.Timestamp(next_trading_day(day.date())) + pd.Timedelta(hours=9)
    if clock < MORNING_OPEN:
        return day + pd.Timedelta(hours=9)
    if MORNING_CLOSE < clock < AFTERNOON_OPEN:
        return day + pd.Timedelta(hours=13)
    if AFTERNOON_CLOSE < clock < ATC_PRINT:
        return day + pd.Timedelta(hours=14, minutes=45)
    return now.floor("min")


def completes_bar(labels: pd.Series, next_label: pd.Timestamp | None = None) -> np.ndarray:
    """True on the last minute row of each signal bar.

    With ``next_label`` the last row closes its bar only if the next print
    belongs to another bar.
    """
    done = (labels.notna() & labels.ne(labels.shift(-1))).to_numpy(copy=True)
    if next_label is not None and len(done):
        done[-1] = bool(pd.notna(labels.iloc[-1]) and labels.iloc[-1] != next_label)
    return done


def spread_to_minutes(labels: pd.Series, by_label: pd.Series, next_label: pd.Timestamp | None = None) -> np.ndarray:
    """Hold each bar's position from the minute its bar closes until the next bar closes.

    Bars missing from ``by_label`` carry the previous position; rows before the
    first decision are flat.
    """
    done = completes_bar(labels, next_label)
    values = pd.Series(np.nan, index=labels.index)
    values[done] = labels[done].map(by_label).to_numpy()
    return values.ffill().fillna(0.0).to_numpy(copy=True)


def expiry_sessions(stamps: pd.Series) -> np.ndarray:
    """True on every row of an expiry session."""
    days = stamps.dt.date
    expiry = {day for day in days.unique() if is_expiry_thursday(day)}
    return days.isin(expiry).to_numpy()


def last_row_of_contract(contracts: pd.Series) -> np.ndarray:
    """True on the last row of each contract, where every sleeve closes out and resets.

    Expiry-session rules normally leave nothing open, but a contract whose
    expiry session is missing from the data (16/07/2020) would otherwise carry
    its position into the next contract.
    """
    last_row = contracts.ne(contracts.shift(-1)).to_numpy(copy=True)
    last_row[-1] = False
    return last_row


def crosses_roll(positions: np.ndarray, contracts: pd.Series) -> np.ndarray:
    """Rows where a position held from the previous row spans a contract change."""
    changed = contracts.ne(contracts.shift()).to_numpy(copy=True)
    changed[0] = False
    held = np.r_[0.0, positions[:-1]] != 0.0
    return changed & held

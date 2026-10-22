"""Place signal-bar decisions on the minute grid without look-ahead.

A signal bar's close is the close of its last minute row, so a decision made
on that bar takes effect from that row: the lab fills at the signal-bar close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.domain.strategy.calendar_rules import is_expiry_thursday


def completes_bar(labels: pd.Series) -> np.ndarray:
    """True on the last minute row of each signal bar."""
    return (labels.notna() & labels.ne(labels.shift(-1))).to_numpy()


def spread_to_minutes(labels: pd.Series, by_label: pd.Series) -> np.ndarray:
    """Hold each bar's position from the minute its bar closes until the next bar closes.

    Bars missing from ``by_label`` carry the previous position; rows before the
    first decision are flat.
    """
    done = completes_bar(labels)
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

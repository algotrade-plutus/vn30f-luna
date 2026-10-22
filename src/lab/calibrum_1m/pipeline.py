"""Load the minute market once, build sleeve positions on it, and score them by period."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from plutus.evaluation.metrics import maximum_drawdown, sharpe_ratio
from plutus.market.margin import vsd_initial_margin
from src.adapters.data.dnse_minute_bars import (
    bars_10m,
    bars_30m,
    labels_10m,
    labels_30m,
    load_futures_minutes,
    load_index_minutes,
)
from src.adapters.strategies.calendar_mtw_signal_source import calendar_mtw_stream, drop_atc
from src.adapters.strategies.calibrum_signal_source import roll_adjust_front_month
from src.lab.backtest import BacktestConfig, evaluate

from . import basis, momentum
from .grid import completes_bar, crosses_roll, expiry_sessions, last_row_of_contract, spread_to_minutes

WORKSPACE = Path(__file__).resolve().parents[3]
CONFIG_PATH = WORKSPACE / "config" / "research.toml"
# Plutus's Vietnamese-market defaults (plutus.evaluation): 3% risk-free rate, 250 sessions a year.
RISK_FREE_RATE = Decimal("0.03")
TRADING_DAYS = 250


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def periods(config: dict) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Named scoring windows; an open end runs to the last bar."""
    out = {}
    for name in ("in_sample", "valid", "oos1", "oos2"):
        window = config["periods"][name]
        out[name] = (pd.Timestamp(window["start"]), pd.Timestamp(window.get("end", "2100-01-01")))
    return out


@dataclass
class Market:
    """Minute futures grid with the signal bars and session flags built from it."""

    minutes: pd.DataFrame
    labels_10m: pd.Series
    labels_30m: pd.Series
    futures_30m: pd.DataFrame
    futures_30m_adjusted: pd.DataFrame
    index_30m: pd.DataFrame
    expiry: np.ndarray
    no_index: np.ndarray
    roll_end: np.ndarray

    @property
    def close(self) -> np.ndarray:
        return self.minutes["Close"].to_numpy(float)


def load_market(end: date) -> Market:
    """Everything up to ``end`` inclusive; selection stages pass the last valid day."""
    cutoff = pd.Timestamp(end) + pd.Timedelta(days=1)
    minutes = load_futures_minutes()
    minutes = minutes[minutes["Datetime"] < cutoff].reset_index(drop=True)
    index_minutes = load_index_minutes()
    index_minutes = index_minutes[index_minutes["Datetime"] < cutoff].reset_index(drop=True)
    futures_30m = bars_30m(minutes)
    adjusted, _ = roll_adjust_front_month(futures_30m)
    index_days = set(index_minutes["Datetime"].dt.date)
    return Market(
        minutes=minutes,
        labels_10m=labels_10m(minutes["Datetime"]),
        labels_30m=labels_30m(minutes["Datetime"]),
        futures_30m=futures_30m,
        futures_30m_adjusted=adjusted,
        index_30m=bars_30m(index_minutes),
        expiry=expiry_sessions(minutes["Datetime"]),
        no_index=~minutes["Datetime"].dt.date.isin(index_days).to_numpy(),
        roll_end=last_row_of_contract(minutes["Contract"]),
    )


def calendar_mtw_positions(market: Market) -> np.ndarray:
    stream, _, _ = calendar_mtw_stream(drop_atc(bars_10m(market.minutes)))
    position = spread_to_minutes(market.labels_10m, stream.set_index("Datetime")["Position"])
    position[market.roll_end] = 0.0
    return position


def _decision_rows(market: Market, clocks: tuple[str, ...] | None = None, exclude: tuple[str, ...] = ()) -> np.ndarray:
    labels = market.labels_30m
    clock = labels.dt.strftime("%H:%M")
    keep = clock.isin(clocks) if clocks is not None else ~clock.isin(exclude)
    return completes_bar(labels) & keep.to_numpy()


def momentum_scores(market: Market, model: momentum.RidgeModel) -> pd.Series:
    """Score by 30-minute bar label."""
    features = momentum.feature_frame(market.futures_30m_adjusted)
    return pd.Series(model.score(features[list(momentum.FEATURES)].to_numpy(float)), index=features["Datetime"])


def momentum_positions(market: Market, model: momentum.RidgeModel, theta: float) -> np.ndarray:
    decision = _decision_rows(market, clocks=momentum.REGULAR_CLOCKS)
    score = market.labels_30m.map(momentum_scores(market, model)).to_numpy(float)
    expiry_cut = decision & market.expiry & (market.labels_30m.dt.strftime("%H:%M") == "14:00").to_numpy()
    expiry_cut |= market.roll_end
    return momentum.positions(market.close, decision, score, expiry_cut, theta)


def basis_positions(market: Market, window: int, z_entry: float) -> np.ndarray:
    decision = _decision_rows(market, exclude=(basis.ATC_BAR,))
    z = market.labels_30m.map(basis.zscores(market.futures_30m, market.index_30m, window)).to_numpy(float)
    return basis.positions(market.close, decision, z, market.expiry | market.no_index | market.roll_end, z_entry)


def vote(*sleeves: np.ndarray) -> np.ndarray:
    return np.sign(np.sum(sleeves, axis=0))


def account_returns(daily_points: pd.Series, capital: float, point_vnd: float) -> list[Decimal]:
    """Daily returns of an account that starts with ``capital`` and keeps its profit and loss."""
    pnl = daily_points.to_numpy(float) * point_vnd
    equity_before = capital + np.r_[0.0, np.cumsum(pnl)[:-1]]
    return [Decimal(str(value)) for value in pnl / equity_before]


def score_periods(
    market: Market,
    position: np.ndarray,
    windows: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
    config: dict,
) -> pd.DataFrame:
    """Metrics per window from one run over the whole stream (fill at the signal-bar close)."""
    if crosses_roll(position, market.minutes["Contract"]).any():
        raise ValueError("a position is held across a contract roll")
    cost = config["costs"]["points_per_contract_per_side"]
    capital = config["account"]["capital_per_contract_vnd"]
    point_vnd = config["account"]["multiplier_vnd_per_point"]
    stream = pd.DataFrame({"Datetime": market.minutes["Datetime"], "Close": market.close, "Position": position})
    result = evaluate(stream, BacktestConfig(round_trip_fee_points=2 * cost))
    accounting, trades = result.frame, result.trades
    rates = {day: float(vsd_initial_margin(day)) for day in accounting["SessionDate"].dt.date.unique()}
    margin_rate = accounting["SessionDate"].dt.date.map(rates).to_numpy(float)
    utilisation = margin_rate * accounting["Close"].to_numpy() * point_vnd * accounting["Position"].abs().to_numpy() / capital

    rows = {}
    for name, (start, end) in windows.items():
        mask = (accounting["SessionDate"] >= start) & (accounting["SessionDate"] <= end)
        part = accounting.loc[mask]
        if part.empty:
            continue
        daily = part.groupby("SessionDate")["NetGain"].sum()
        returns = account_returns(daily, capital, point_vnd)
        pnl = part["NetGain"].cumsum()
        notional = float((part["Close"] * part["PositionChange"]).sum())
        net = float(part["NetGain"].sum())
        in_window = trades[(trades["EntryDatetime"] >= start) & (trades["EntryDatetime"] < end + pd.Timedelta(days=1))]
        sharpe = sharpe_ratio(returns, risk_free_rate=RISK_FREE_RATE, annualization_factor=TRADING_DAYS)
        drawdown = maximum_drawdown(returns)
        rows[name] = {
            "net_points": net,
            "net_million_vnd": net * point_vnd / 1e6,
            "return_pct": net * point_vnd / capital * 100.0,
            "sharpe": float(sharpe) if sharpe is not None else float("nan"),
            "mdd_points": float((pnl.cummax() - pnl).max()),
            "mdd_pct": -float(drawdown) * 100.0 if drawdown is not None else float("nan"),
            "margin_bps": net / notional * 1e4 if notional else float("nan"),
            "trades": int(len(in_window)),
            "hit_rate": float((in_window["NetPoints"] > 0).mean()) if len(in_window) else float("nan"),
            "cost_points": float(part["FeeCost"].sum()),
            "exposure": float((part["Position"] != 0).mean()),
            "peak_margin_utilisation_pct": float(utilisation[mask.to_numpy()].max()) * 100.0,
            "sessions": int(len(daily)),
        }
    return pd.DataFrame(rows).T


def yearly_net(market: Market, position: np.ndarray, config: dict) -> pd.Series:
    cost = config["costs"]["points_per_contract_per_side"]
    stream = pd.DataFrame({"Datetime": market.minutes["Datetime"], "Close": market.close, "Position": position})
    accounting = evaluate(stream, BacktestConfig(round_trip_fee_points=2 * cost)).frame
    return accounting.groupby(accounting["Datetime"].dt.year)["NetGain"].sum()

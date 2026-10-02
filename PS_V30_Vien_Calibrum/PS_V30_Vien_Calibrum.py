"""PS_V30_Vien_Calibrum — standalone frozen Master Ensemble.

Calibrum combines three independent 30-minute sleeves and returns the sign of
their net vote:

- Ridge H2: frozen five-feature linear model;
- Shinji: adjusted-futures/spot spread mean reversion;
- Calendar: weekday, turn-of-month, pre-holiday and expiry effects.

The module is deliberately self-contained for Finpros submission. It does not
import another Alpha, fit a model, read a sibling config, or execute test code at
import time.
"""
from __future__ import annotations

import calendar as pycalendar
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

try:
    from alpha_base import AlphaBase
except ImportError:
    import loadlibs  # noqa: F401
    from alpha_base import AlphaBase


REGULAR_CLOCKS = {
    "09:00", "09:30", "10:00", "10:30", "11:00", "13:00", "13:30", "14:00"
}

MODEL_KEYS = {
    "ridge_centers", "ridge_scales", "ridge_coef", "ridge_intercept",
    "ensemble_weights",
}


def _load_model(path: Path) -> dict[str, np.ndarray | float]:
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy Calibrum model: {path}")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if set(payload) != MODEL_KEYS:
        raise ValueError(f"Calibrum model keys không hợp lệ: {sorted(payload)}")
    model: dict[str, np.ndarray | float] = {
        "ridge_centers": payload["ridge_centers"].numpy().astype(np.float64),
        "ridge_scales": payload["ridge_scales"].numpy().astype(np.float64),
        "ridge_coef": payload["ridge_coef"].numpy().astype(np.float64),
        "ridge_intercept": float(payload["ridge_intercept"].item()),
        "ensemble_weights": payload["ensemble_weights"].numpy().astype(np.float64),
    }
    if any(np.asarray(model[key]).shape != (5,) for key in (
        "ridge_centers", "ridge_scales", "ridge_coef"
    )):
        raise ValueError("Calibrum Ridge tensors phải có shape (5,)")
    if np.asarray(model["ensemble_weights"]).shape != (3,):
        raise ValueError("Calibrum ensemble_weights phải có shape (3,)")
    if not all(np.isfinite(np.asarray(value)).all() for value in model.values()):
        raise ValueError("Calibrum model chứa giá trị không hữu hạn")
    if (np.asarray(model["ridge_scales"]) <= 0).any():
        raise ValueError("Calibrum ridge_scales phải dương")
    return model

_CLOSED_DATES = """
2017-01-02 2017-01-26 2017-01-27 2017-01-30 2017-01-31 2017-02-01 2017-02-02
2017-04-06 2017-05-01 2017-05-02 2017-09-04
2018-12-31 2018-01-01 2018-02-14 2018-02-15 2018-02-16 2018-02-19 2018-02-20
2018-04-25 2018-04-30 2018-05-01 2018-09-03
2019-01-01 2019-02-04 2019-02-05 2019-02-06 2019-02-07 2019-02-08
2019-04-15 2019-04-29 2019-04-30 2019-05-01 2019-09-02
2020-01-01 2020-01-23 2020-01-24 2020-01-27 2020-01-28 2020-01-29
2020-04-02 2020-04-30 2020-05-01 2020-09-02
2021-01-01 2021-02-10 2021-02-11 2021-02-12 2021-02-15 2021-02-16
2021-04-21 2021-04-30 2021-05-03 2021-09-02 2021-09-03
2022-01-03 2022-01-31 2022-02-01 2022-02-02 2022-02-03 2022-02-04
2022-04-11 2022-05-02 2022-05-03 2022-09-01 2022-09-02
2023-01-02 2023-01-20 2023-01-23 2023-01-24 2023-01-25 2023-01-26
2023-05-01 2023-05-02 2023-05-03 2023-09-01 2023-09-04
2024-01-01 2024-02-08 2024-02-09 2024-02-12 2024-02-13 2024-02-14
2024-04-18 2024-04-29 2024-04-30 2024-05-01 2024-09-02 2024-09-03
2025-01-01 2025-01-27 2025-01-28 2025-01-29 2025-01-30 2025-01-31
2025-04-07 2025-04-30 2025-05-01 2025-09-01 2025-09-02
2026-01-01 2026-02-16 2026-02-17 2026-02-18 2026-02-19 2026-02-20
2026-04-26 2026-04-30 2026-05-01 2026-08-31 2026-09-01 2026-09-02
2027-01-01 2027-02-05 2027-02-08 2027-02-09 2027-02-10 2027-02-11
2027-04-16 2027-04-30 2027-05-03 2027-09-02 2027-09-03
"""
HOSE_CLOSED_INDEX = pd.DatetimeIndex(
    sorted(pd.Timestamp(value) for value in _CLOSED_DATES.split())
)


def _dm_attr(dm: Any, name: str) -> str:
    value = getattr(dm, name, "")
    return str(value() if callable(value) else value).lower()


def _select_dm(dm_list: list[Any], ticker: str, timeframe: str) -> Any:
    matches = [
        dm for dm in dm_list
        if _dm_attr(dm, "ticker") == ticker.lower()
        and _dm_attr(dm, "timeframe") == timeframe.lower()
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Cần đúng một feed {ticker}/{timeframe}, nhận {len(matches)}"
        )
    return matches[0]


def _clean_frame(dm: Any, name: str) -> pd.DataFrame:
    if dm is None or getattr(dm, "data", None) is None:
        raise ValueError(f"Không tìm thấy dữ liệu cho {name}")
    frame = dm.data.copy()
    frame.columns = [str(column).capitalize() for column in frame.columns]
    required = {"Datetime", "Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{name} thiếu cột {sorted(required - set(frame.columns))}")
    frame["Datetime"] = pd.to_datetime(frame["Datetime"])
    numeric = ["Open", "High", "Low", "Close", "Volume"]
    if not np.isfinite(frame[numeric].to_numpy(float)).all():
        raise ValueError(f"{name} chứa OHLCV không hữu hạn")
    return (
        frame.sort_values("Datetime")
        .drop_duplicates("Datetime", keep="last")
        .reset_index(drop=True)
    )


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    result = numerator / denominator
    valid = (
        denominator.abs() > 1e-12
    ) & np.isfinite(numerator) & np.isfinite(denominator)
    return result.where(valid, np.nan)


def _ridge_positions(
    frame: pd.DataFrame,
    parameters: dict[str, Any],
    model: dict[str, np.ndarray | float],
) -> np.ndarray:
    entry_threshold = float(parameters.get("ridge_entry_threshold", 0.18))
    min_hold = int(parameters.get("ridge_min_hold", 2))
    max_hold = int(parameters.get("ridge_max_hold", 8))
    stop_loss = float(parameters.get("ridge_stop_loss_pts", 10.0))

    working = frame
    hour_min = working["Datetime"].dt.strftime("%H:%M")
    regular = working.loc[hour_min.isin(REGULAR_CLOCKS)]
    regular_hour_min = hour_min.loc[regular.index]
    close = regular["Close"].astype(float)
    open_ = regular["Open"].astype(float)
    high = regular["High"].astype(float)
    low = regular["Low"].astype(float)
    volume = regular["Volume"].astype(float)

    true_range = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1, skipna=False)
    atr14 = true_range.shift(1).rolling(14, min_periods=14).mean()
    day = regular["Datetime"].dt.normalize()
    complete = regular[["Open", "High", "Low", "Close", "Volume"]].notna().all(axis=1).groupby(day).cummin()
    first_open = open_.where(regular_hour_min == "09:00").groupby(day).transform("first")
    vwap = _safe_ratio(
        ((((high + low + close) / 3.0) * volume).groupby(day).cumsum()),
        volume.groupby(day).cumsum(),
    )
    feature_vwap = _safe_ratio(close - vwap, atr14).where(complete)
    feature_open = _safe_ratio(close - first_open, atr14).where(complete)
    feature_trend = _safe_ratio(close - close.rolling(4, min_periods=4).mean(), atr14)
    up_squared = close.diff().clip(lower=0) ** 2
    down_squared = close.diff().clip(upper=0) ** 2
    up4 = up_squared.rolling(4, min_periods=4).sum()
    down4 = down_squared.rolling(4, min_periods=4).sum()
    feature_asymmetry = _safe_ratio(up4 - down4, up4 + down4)
    feature_body = _safe_ratio(close - open_, atr14)

    features = np.column_stack([
        feature_vwap.to_numpy(float),
        feature_open.to_numpy(float),
        feature_trend.to_numpy(float),
        feature_asymmetry.to_numpy(float),
        feature_body.to_numpy(float),
    ])
    scaled = np.clip(
        (features - model["ridge_centers"]) / model["ridge_scales"], -8.0, 8.0
    )
    regular_score = model["ridge_intercept"] + scaled @ model["ridge_coef"]
    score = pd.Series(regular_score, index=regular.index).reindex(working.index).to_numpy()

    position = np.zeros(len(working), dtype=int)
    current = 0
    bars_held = 0
    entry_price = 0.0
    clocks = hour_min.to_numpy()
    closes = working["Close"].to_numpy(float)
    for index in range(14, len(working)):
        if clocks[index] == "14:30":
            position[index] = current
            continue
        current_score = score[index]
        current_price = closes[index]
        if np.isnan(current_score):
            position[index] = current
            continue
        if current != 0:
            bars_held += 1
            unrealized = current * (current_price - entry_price)
            score_exit = bars_held >= min_hold and (
                (current == 1 and current_score < 0.0)
                or (current == -1 and current_score > 0.0)
            )
            if unrealized <= -stop_loss or score_exit or bars_held >= max_hold:
                current = 0
                bars_held = 0
                entry_price = 0.0
        if current == 0:
            if current_score >= entry_threshold:
                current = 1
                bars_held = 0
                entry_price = current_price
            elif current_score <= -entry_threshold:
                current = -1
                bars_held = 0
                entry_price = current_price
        position[index] = current
    return position


def _shinji_positions(
    futures: pd.DataFrame,
    spot: pd.DataFrame,
    parameters: dict[str, Any],
) -> np.ndarray:
    window = int(parameters.get("shinji_window", 40))
    z_entry = float(parameters.get("shinji_z_entry", 1.5))
    z_exit = float(parameters.get("shinji_z_exit", 0.0))
    min_hold = int(parameters.get("shinji_min_hold", 2))
    stop_loss = float(parameters.get("shinji_stop_loss", 14.0))

    merged = pd.merge_asof(
        futures.sort_values("Datetime").reset_index(drop=True),
        spot[["Datetime", "Close"]].rename(columns={"Close": "SpotClose"}).sort_values("Datetime").reset_index(drop=True),
        on="Datetime",
        direction="backward",
    )
    close = merged["Close"].to_numpy(float)
    basis = close - merged["SpotClose"].to_numpy(float)
    basis_series = pd.Series(basis)
    basis_mean = basis_series.rolling(window, min_periods=15).mean().to_numpy()
    basis_std = (basis_series.rolling(window, min_periods=15).std() + 1e-6).to_numpy()
    z_basis = np.nan_to_num((basis - basis_mean) / basis_std, nan=0.0)

    position = np.zeros(len(merged), dtype=int)
    current = 0
    bars_held = 0
    entry_price = 0.0
    clocks = merged["Datetime"].dt.strftime("%H:%M").to_numpy()
    for index in range(window, len(merged)):
        if clocks[index] == "14:30":
            position[index] = current
            continue
        z_value = z_basis[index]
        current_price = close[index]
        if current != 0:
            bars_held += 1
            unrealized = current * (current_price - entry_price)
            reverse_long = z_value <= -z_entry and current == -1 and bars_held >= min_hold
            reverse_short = z_value >= z_entry and current == 1 and bars_held >= min_hold
            take_profit = abs(z_value) <= z_exit and bars_held >= min_hold
            if reverse_long:
                current = 1
                bars_held = 0
                entry_price = current_price
            elif reverse_short:
                current = -1
                bars_held = 0
                entry_price = current_price
            elif unrealized <= -stop_loss or take_profit:
                current = 0
                bars_held = 0
                entry_price = 0.0
        else:
            if z_value <= -z_entry:
                current = 1
                bars_held = 0
                entry_price = current_price
            elif z_value >= z_entry:
                current = -1
                bars_held = 0
                entry_price = current_price
        position[index] = current
    return position


def _next_trading_day(dates: pd.Series) -> pd.Series:
    day = pd.Series(pd.to_datetime(dates)).dt.normalize() + pd.Timedelta(days=1)
    for _ in range(12):
        off = (day.dt.dayofweek >= 5) | pd.DatetimeIndex(day).isin(HOSE_CLOSED_INDEX)
        if not off.any():
            break
        day = day.where(~off, day + pd.Timedelta(days=1))
    return day


def _is_pre_holiday(dates: pd.Series) -> np.ndarray:
    current = pd.Series(pd.to_datetime(dates)).dt.normalize().reset_index(drop=True)
    gap = (_next_trading_day(current).reset_index(drop=True) - current).dt.days
    normal_gap = pd.Series(1, index=current.index).where(current.dt.dayofweek != 4, 3)
    return (gap > normal_gap).to_numpy()


def _next_weekday(dates: pd.Series) -> pd.Series:
    step = np.where(pd.Series(dates).dt.dayofweek == 4, 3, 1)
    return pd.Series(dates) + pd.to_timedelta(step, unit="D")


def _weekday_index_in_month(dates: pd.Series) -> np.ndarray:
    day = pd.Series(pd.to_datetime(dates)).dt.normalize().to_numpy().astype("datetime64[D]")
    month_start = day.astype("datetime64[M]").astype("datetime64[D]")
    return np.busday_count(month_start, day)


def _is_expiry_session(dates: pd.Series) -> np.ndarray:
    normalized = pd.Series(pd.to_datetime(dates)).dt.normalize()
    expiries: set[pd.Timestamp] = set()
    for date in normalized.drop_duplicates():
        weeks = pycalendar.monthcalendar(date.year, date.month)
        thursdays = [week[pycalendar.THURSDAY] for week in weeks if week[pycalendar.THURSDAY]]
        if len(thursdays) >= 3:
            expiries.add(pd.Timestamp(year=date.year, month=date.month, day=thursdays[2]))
    return normalized.isin(expiries).to_numpy()


def _long_days(
    dates: pd.Series,
    use_month_start: bool,
    use_preholiday: bool,
    long_dows: tuple[int, ...],
) -> np.ndarray:
    days = pd.Series(pd.to_datetime(dates)).reset_index(drop=True)
    mask = np.zeros(len(days))
    if use_month_start:
        mask = np.where(_weekday_index_in_month(days) < 2, 1.0, mask)
    if use_preholiday:
        mask = np.where(_is_pre_holiday(days), 1.0, mask)
    if long_dows:
        mask = np.where(days.dt.dayofweek.isin(long_dows).to_numpy(), 1.0, mask)
    return mask


def _calendar_positions(frame: pd.DataFrame, parameters: dict[str, Any]) -> np.ndarray:
    long_dows = tuple(parameters.get("calendar_long_dows", (1, 2)))
    use_month_start = bool(parameters.get("calendar_use_month_start", True))
    use_preholiday = bool(parameters.get("calendar_use_preholiday", True))
    use_monday_short = bool(parameters.get("calendar_use_monday_short", True))
    use_expiry = bool(parameters.get("calendar_use_expiry_thursday", True))
    monday_max_gap = parameters.get("calendar_monday_max_gap", 0.0)
    session_end = str(parameters.get("calendar_session_end", "14:30"))

    dates = frame["Datetime"].reset_index(drop=True)
    session_dates = dates.dt.normalize()
    at_session_end = dates.dt.strftime("%H:%M") >= session_end
    flags = {
        "use_month_start": use_month_start,
        "use_preholiday": use_preholiday,
        "long_dows": long_dows,
    }
    today_long = _long_days(session_dates, **flags)
    next_day_long = _long_days(_next_weekday(session_dates), **flags)
    position = np.where(at_session_end, next_day_long, today_long)

    if use_monday_short:
        start_of_month = _weekday_index_in_month(session_dates) < 2
        pre_holiday = _is_pre_holiday(session_dates)
        regular_monday = (
            (session_dates.dt.dayofweek == 0) & (~start_of_month) & (~pre_holiday)
        )
        if monday_max_gap is not None:
            daily_open = frame.groupby(session_dates)["Open"].transform("first")
            daily_close = frame.groupby(session_dates)["Close"].last()
            previous_close = daily_close.shift(1)
            gap_allowed = daily_open - session_dates.map(previous_close) <= float(monday_max_gap)
        else:
            gap_allowed = True
        short = (~at_session_end) & regular_monday & gap_allowed & (position == 0)
        position = np.where(short, -1.0, position)

    if use_expiry:
        expiry_long = (~at_session_end) & _is_expiry_session(session_dates) & (position == 0)
        position = np.where(expiry_long, 1.0, position)
    return position.astype(int)


class CalibrumAlpha(AlphaBase):
    """Standalone sign-net ensemble of frozen Ridge, Shinji and Calendar."""

    def __init__(self, alpha_config: dict[str, Any]) -> None:
        super().__init__(alpha_config)
        self.parameters = dict(alpha_config.get("parameters", {}))
        working_path = Path(alpha_config.get("working_path", Path(__file__).parent))
        model_name = self.parameters.get(
            "model_file", "PS_V30_Vien_Calibrum_model.pt"
        )
        self.model_path = working_path / str(model_name)
        self.model = _load_model(self.model_path)

    def _generate(self, dm_list: list[Any]) -> pd.DataFrame:
        futures = _clean_frame(
            _select_dm(dm_list, "vn30f1m", "30m"), "vn30f1m/30m"
        )
        spot = _clean_frame(_select_dm(dm_list, "vn30", "30m"), "vn30/30m")

        ridge = _ridge_positions(futures, self.parameters, self.model)
        shinji = _shinji_positions(futures, spot, self.parameters)
        calendar = _calendar_positions(futures, self.parameters)
        if not (len(ridge) == len(shinji) == len(calendar) == len(futures)):
            raise ValueError("Ba sleeve Calibrum không thẳng hàng")

        weights = np.asarray(self.model["ensemble_weights"])
        position = np.sign(
            weights[0] * ridge + weights[1] * shinji + weights[2] * calendar
        ).astype(int)
        clocks = futures["Datetime"].dt.strftime("%H:%M").to_numpy()
        for index in np.flatnonzero(clocks == "14:30"):
            if index > 0:
                position[index] = position[index - 1]
        if not np.isin(position, (-1, 0, 1)).all():
            raise ValueError("Calibrum sinh Position ngoài {-1,0,1}")

        output = futures[["Datetime", "Close"]].copy()
        output["Position"] = position
        return output


if __name__ == "__main__":
    pass

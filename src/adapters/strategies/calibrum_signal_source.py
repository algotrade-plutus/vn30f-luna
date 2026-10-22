"""Causal DB/Plutus bridge for the frozen Calibrum signal package.

The copied Calibrum source was written for the ``AlphaBase`` runtime.
This adapter calls only its frozen sleeve functions; it neither imports nor
calls the vendor platform.  Its output is deliberately a *diagnostic* while the research
database exposes a raw front-month contract rather than Calibrum's documented
adjusted continuous future.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
from typing import Any

import numpy as np
import pandas as pd

from src.application.ports.signal_port import ISignalGateway
from src.domain.entities.bar import Bar
from src.domain.strategy.calendar_rules import is_expiry_thursday


_SOURCE_NAME = "PS_V30_Vien_Calibrum.py"
_CONFIG_NAME = "config.json"
_MODEL_NAME = "PS_V30_Vien_Calibrum_model.pt"
_VERIFICATION_NAME = "native_verification.json"


@dataclass(frozen=True)
class CalibrumTargets:
    """Pre-shifted executable targets and their audit evidence."""

    targets: dict[datetime, int]
    diagnostics: dict[str, Any]


class _FrameFeed:
    """Minimal data-manager shape consumed by Calibrum's frozen cleaner."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.data = frame


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _load_frozen_module(package_dir: Path) -> types.ModuleType:
    """Import the archive's functions with a tiny local AlphaBase shim.

    Calibrum's module imports ``AlphaBase`` only to declare its vendor-facing
    class.  The DB bridge never instantiates that class, but providing this
    narrow shim lets us execute the original frozen sleeve functions unchanged.
    """

    source_path = package_dir / _SOURCE_NAME
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing Calibrum source: {source_path}")

    module_name = f"_calibrum_frozen_{_sha256(source_path)[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Calibrum source: {source_path}")

    inserted_alpha_base = "alpha_base" not in sys.modules
    if inserted_alpha_base:
        shim = types.ModuleType("alpha_base")

        class AlphaBase:  # noqa: N801 - frozen source requires this spelling.
            def __init__(self, _alpha_config: dict[str, Any]) -> None:
                pass

        shim.AlphaBase = AlphaBase
        sys.modules["alpha_base"] = shim

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as error:
        if error.name == "torch":
            raise RuntimeError(
                "Calibrum requires PyTorch. Refresh the environment with `make setup`."
            ) from error
        raise
    finally:
        if inserted_alpha_base:
            sys.modules.pop("alpha_base", None)
        sys.modules.pop(module_name, None)
    return module


def pre_shift_positions(
    positions: pd.DataFrame,
    *,
    quantity: int = 1,
    max_position: int = 1,
) -> dict[datetime, int]:
    """Map a completed-bar position to the next available execution interval.

    A Calibrum row at timestamp ``T`` uses the OHLCV close of the bar starting
    at ``T``.  Plutus may therefore receive it only at the next available row,
    not at ``T``.  Row order rather than wall-clock arithmetic preserves the
    lunch break, overnight boundary and missing-bar behavior of the feed.
    """

    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("quantity must be a positive integer")
    if isinstance(max_position, bool) or not isinstance(max_position, int) or max_position < 1:
        raise ValueError("max_position must be a positive integer")
    required = {"Datetime", "Position"}
    if missing := required - set(positions.columns):
        raise ValueError(f"Position frame missing columns: {sorted(missing)}")
    ordered = positions.loc[:, ["Datetime", "Position"]].copy()
    ordered["Datetime"] = pd.to_datetime(ordered["Datetime"])
    if ordered["Datetime"].isna().any() or ordered["Datetime"].duplicated().any():
        raise ValueError("Calibrum timestamps must be non-null and unique")
    ordered = ordered.sort_values("Datetime", kind="stable").reset_index(drop=True)
    values = ordered["Position"].to_numpy()
    if max_position == 1:
        if not np.isin(values, (-1, 0, 1)).all():
            raise ValueError("Calibrum positions must be in {-1, 0, 1}")
    else:
        allowed = np.arange(-max_position, max_position + 1)
        if not np.isin(values, allowed).all():
            raise ValueError(f"Calibrum positions must be in {allowed.tolist()}")

    return {
        stamp.to_pydatetime(): int(position) * quantity
        for stamp, position in zip(ordered["Datetime"].iloc[1:], values[:-1], strict=True)
    }


def apply_session_rules(
    positions: np.ndarray | pd.Series,
    datetimes: pd.Series,
    *,
    expiry_flat: bool = True,
) -> np.ndarray:
    """Apply the ensemble's session rules to bar-close positions.

    The 14:30 ATC bar repeats the 14:00 position, so no new decision is taken
    in the closing auction.  On an expiry session the position is flat from the
    14:00 bar: its target executes in the ATC, so nothing is carried from the
    expiring contract into the next front month.
    """

    out = np.asarray(positions).copy()
    stamps = pd.Series(pd.to_datetime(datetimes)).reset_index(drop=True)
    if len(stamps) != len(out):
        raise ValueError("positions and datetimes must have the same length")
    clocks = stamps.dt.strftime("%H:%M").to_numpy()
    for index in np.flatnonzero(clocks == "14:30"):
        if index > 0:
            out[index] = out[index - 1]
    if expiry_flat:
        sessions = stamps.dt.date
        expiry_days = {day for day in sessions.unique() if is_expiry_thursday(day)}
        expiry = sessions.isin(expiry_days).to_numpy()
        out[expiry & (clocks >= "14:00")] = 0
    return out


def _rolls(frame: pd.DataFrame) -> list[dict[str, str]]:
    if "Contract" not in frame.columns:
        raise ValueError("Futures frame must include Contract for rollover audit")
    ordered = frame.loc[:, ["Datetime", "Contract"]].copy()
    ordered["Datetime"] = pd.to_datetime(ordered["Datetime"])
    ordered = ordered.sort_values("Datetime", kind="stable").reset_index(drop=True)
    changed = ordered["Contract"].ne(ordered["Contract"].shift())
    indices = ordered.index[changed].tolist()[1:]
    return [
        {
            "timestamp": ordered.loc[index, "Datetime"].isoformat(),
            "from_contract": str(ordered.loc[index - 1, "Contract"]),
            "to_contract": str(ordered.loc[index, "Contract"]),
        }
        for index in indices
    ]


def roll_adjust_front_month(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Construct an additive continuous future solely from observed roll edges.

    At a contract transition, the first new-contract open is shifted to equal
    the prior front-month close.  The cumulative additive offset is then
    applied to the later OHLC values.  This removes a mechanical roll jump but
    is deliberately *not* represented as the vendor's unknown adjusted series.
    """

    required = {"Datetime", "Contract", "Open", "High", "Low", "Close"}
    if missing := required - set(frame.columns):
        raise ValueError(f"Futures frame missing columns: {sorted(missing)}")
    adjusted = frame.copy()
    adjusted["Datetime"] = pd.to_datetime(adjusted["Datetime"])
    adjusted = adjusted.sort_values("Datetime", kind="stable").reset_index(drop=True)
    offset = 0.0
    adjustments: list[dict[str, Any]] = []
    previous_contract: str | None = None
    previous_close: float | None = None
    for index, row in adjusted.iterrows():
        contract = str(row["Contract"])
        if previous_contract is not None and contract != previous_contract:
            raw_new_open = float(row["Open"])
            assert previous_close is not None
            increment = previous_close - raw_new_open
            offset += increment
            adjustments.append(
                {
                    "timestamp": row["Datetime"].isoformat(),
                    "from_contract": previous_contract,
                    "to_contract": contract,
                    "previous_raw_close": previous_close,
                    "new_raw_open": raw_new_open,
                    "incremental_offset": increment,
                    "cumulative_offset": offset,
                }
            )
        for column in ("Open", "High", "Low", "Close"):
            adjusted.loc[index, column] = float(row[column]) + offset
        previous_contract = contract
        previous_close = float(row["Close"])
    return adjusted, adjustments


def _shinji_with_roll_guard(
    frozen: types.ModuleType,
    futures: pd.DataFrame,
    spot: pd.DataFrame,
    parameters: dict[str, Any],
) -> np.ndarray:
    """Reset Shinji on each contract and suppress it on expiry sessions.

    Each new front-month contract starts flat and must build its own 40-bar
    Shinji history.  The expiry session itself is also flat for this sleeve.
    Other Calibrum sleeves are deliberately untouched.
    """

    guarded = np.zeros(len(futures), dtype=int)
    segments = futures["Contract"].ne(futures["Contract"].shift()).cumsum()
    for _, segment in futures.groupby(segments, sort=False):
        values = frozen._shinji_positions(segment.copy(), spot, parameters)
        guarded[segment.index.to_numpy()] = values
    guarded[frozen._is_expiry_session(futures["Datetime"])] = 0
    return guarded


def _ridge_with_roll_guard(
    frozen: types.ModuleType,
    futures: pd.DataFrame,
    parameters: dict[str, Any],
    model: dict[str, np.ndarray | float],
) -> np.ndarray:
    """Reset ATR/features/state for every front-month contract transition."""

    guarded = np.zeros(len(futures), dtype=int)
    segments = futures["Contract"].ne(futures["Contract"].shift()).cumsum()
    for _, segment in futures.groupby(segments, sort=False):
        values = frozen._ridge_positions(segment.copy(), parameters, model)
        guarded[segment.index.to_numpy()] = values
    # Suppression at expiry prevents the last old-contract target from being
    # causally carried into the opening interval of the new contract.
    guarded[frozen._is_expiry_session(futures["Datetime"])] = 0
    return guarded


_CALENDAR_LEGS_OFF = {
    "calendar_use_month_start": False,
    "calendar_use_preholiday": False,
    "calendar_use_monday_short": False,
    "calendar_use_expiry_thursday": False,
}


def _core_calendar_positions(
    frozen: types.ModuleType,
    frame: pd.DataFrame,
    parameters: dict[str, Any],
) -> np.ndarray:
    """Calendar with its two core legs: short Monday, long the ``D_long`` days.

    The frozen sleeve runs with every switchable leg off, which leaves the
    weekday longs.  The Monday short is rebuilt here because the frozen one
    skips Mondays that open a month or precede a holiday, a distinction that
    belongs to legs this research does not use.
    """

    position = np.asarray(
        frozen._calendar_positions(frame, {**parameters, **_CALENDAR_LEGS_OFF})
    )
    if not bool(parameters.get("calendar_use_monday_short", True)):
        return position.astype(int)
    stamps = frame["Datetime"].reset_index(drop=True)
    sessions = stamps.dt.normalize()
    session_end = str(parameters.get("calendar_session_end", "14:30"))
    at_session_end = (stamps.dt.strftime("%H:%M") >= session_end).to_numpy()
    monday = (sessions.dt.dayofweek == 0).to_numpy()
    max_gap = parameters.get("calendar_monday_max_gap", 0.0)
    if max_gap is None:
        gap_allowed = np.ones(len(stamps), dtype=bool)
    else:
        opens = frame["Open"].reset_index(drop=True).groupby(sessions).transform("first")
        previous_close = frame["Close"].reset_index(drop=True).groupby(sessions).last().shift(1)
        gap_allowed = (opens - sessions.map(previous_close) <= float(max_gap)).to_numpy()
    short = monday & ~at_session_end & gap_allowed & (position == 0)
    return np.where(short, -1, position).astype(int)


def generate_calibrum_position_stream(
    futures: pd.DataFrame,
    spot: pd.DataFrame,
    package_dir: Path | str,
    *,
    ensemble_mode: str = "vote",
    parameter_overrides: dict[str, Any] | None = None,
    use_shinji: bool = True,
    shinji_basis_price: str = "raw",
    shinji_roll_guard: bool = True,
    ridge_roll_guard: bool = False,
    expiry_flat: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Generate the unshifted Calibrum position stream and audit evidence.

    The returned frame contains ``Datetime``, ``Close`` and ``Position``.
    ``Position`` is the signal known at each bar close. Execution lag is
    applied by the local lab engine or by ``pre_shift_positions`` for Plutus.
    """

    package = Path(package_dir).resolve()
    source_path = package / _SOURCE_NAME
    config_path = package / _CONFIG_NAME
    model_path = package / _MODEL_NAME
    for artifact in (source_path, config_path, model_path):
        if not artifact.is_file():
            raise FileNotFoundError(f"Missing Calibrum frozen artifact: {artifact}")

    config = _load_json(config_path)
    if config.get("class_name") != "CalibrumAlpha":
        raise ValueError("Unexpected Calibrum class_name")
    base_parameters = config.get("parameters")
    if not isinstance(base_parameters, dict):
        raise ValueError("Calibrum config requires an object at parameters")

    parameters = dict(base_parameters)
    overrides = dict(parameter_overrides or {})
    if "model_file" in overrides:
        raise ValueError("model_file cannot be overridden")
    unknown_overrides = sorted(set(overrides) - set(parameters))
    if unknown_overrides:
        raise ValueError(f"Unknown Calibrum parameter overrides: {unknown_overrides}")
    parameters.update(overrides)

    if shinji_basis_price not in {"raw", "roll_adjusted"}:
        raise ValueError("shinji_basis_price must be 'raw' or 'roll_adjusted'")
    if ensemble_mode not in {"vote", "sum"}:
        raise ValueError("ensemble_mode must be 'vote' or 'sum'")
    configured_model = str(parameters.get("model_file", _MODEL_NAME))
    if configured_model != _MODEL_NAME:
        raise ValueError(
            f"Calibrum config model_file must be {_MODEL_NAME!r}, got {configured_model!r}"
        )

    futures = futures.copy()
    if "Contract" not in futures.columns:
        futures["Contract"] = "VN30F1M"

    frozen = _load_frozen_module(package)
    model = frozen._load_model(model_path)
    clean_futures = frozen._clean_frame(_FrameFeed(futures), "VN30F1M/30m")
    clean_spot = frozen._clean_frame(_FrameFeed(spot), "VN30/30m")
    ridge = (
        _ridge_with_roll_guard(frozen, clean_futures, parameters, model)
        if ridge_roll_guard
        else frozen._ridge_positions(clean_futures, parameters, model)
    )
    shinji_futures = clean_futures
    adjustments: list[dict[str, Any]] = []
    if shinji_basis_price == "roll_adjusted":
        shinji_futures, adjustments = roll_adjust_front_month(futures)
        shinji_futures = frozen._clean_frame(
            _FrameFeed(shinji_futures), "roll-adjusted VN30F1M/30m"
        )
    # Shinji trades only sessions with index bars; elsewhere the as-of join
    # would pair futures with a stale index close from an earlier session.
    spot_sessions = set(clean_spot["Datetime"].dt.date)
    covered = shinji_futures["Datetime"].dt.date.isin(spot_sessions).to_numpy()
    sessions_without_spot = sorted(
        {day.isoformat() for day in shinji_futures.loc[~covered, "Datetime"].dt.date}
    )
    shinji = np.zeros(len(clean_futures), dtype=int)
    if use_shinji and covered.any():
        shinji_input = shinji_futures.loc[covered].reset_index(drop=True)
        shinji[covered] = (
            _shinji_with_roll_guard(frozen, shinji_input, clean_spot, parameters)
            if shinji_roll_guard
            else frozen._shinji_positions(shinji_input, clean_spot, parameters)
        )
    calendar = _core_calendar_positions(frozen, clean_futures, parameters)
    if not (len(ridge) == len(shinji) == len(calendar) == len(clean_futures)):
        raise RuntimeError("Calibrum sleeve lengths are not aligned")
    weights = np.asarray(model["ensemble_weights"])
    if ensemble_mode == "vote":
        raw_position = np.sign(
            weights[0] * ridge + weights[1] * shinji + weights[2] * calendar
        ).astype(int)
    else:
        raw_position = (
            weights[0] * ridge + weights[1] * shinji + weights[2] * calendar
        ).astype(int)
    raw_position = apply_session_rules(
        raw_position, clean_futures["Datetime"], expiry_flat=expiry_flat
    )
    if ensemble_mode == "vote":
        if not np.isin(raw_position, (-1, 0, 1)).all():
            raise RuntimeError("Calibrum generated an invalid position")
    else:
        if not np.isin(raw_position, np.arange(-3, 4)).all():
            raise RuntimeError("Calibrum sum generated an invalid position")

    stream = clean_futures[["Datetime", "Close"]].copy()
    stream["Position"] = raw_position
    stream["Ridge"] = ridge
    stream["Shinji"] = shinji
    stream["Calendar"] = calendar

    actual_hashes = {
        "source": _sha256(source_path),
        "config": _sha256(config_path),
        "model": _sha256(model_path),
    }
    verification_path = package / _VERIFICATION_NAME
    recorded_hashes: dict[str, Any] = {}
    if verification_path.is_file():
        recorded_hashes = _load_json(verification_path).get("sha256", {})
    rolls = _rolls(futures)
    diagnostics: dict[str, Any] = {
        "signal_package": str(package),
        "artifact_sha256": actual_hashes,
        "native_verification_sha256": recorded_hashes,
        "artifact_matches_native_verification": {
            name: actual_hashes[name] == recorded_hashes.get(name)
            for name in actual_hashes
        },
        "source_mode": (
            "raw_front_month_roll_diagnostic"
            if shinji_basis_price == "raw"
            else "roll_adjusted_shinji_sensitivity"
        ),
        "source_mode_note": (
            "Calibrum documents an adjusted-futures/spot Shinji sleeve, but the "
            "research candle feed is a raw/continuous front-month series. This run "
            "is not native-parity evidence."
            if shinji_basis_price == "raw"
            else "Shinji alone receives a project-defined roll-adjusted continuous "
            "future; Ridge H2, Calendar, and execution retain raw candles. This is "
            "not verified native-parity evidence."
        ),
        "raw_contract_rolls": rolls,
        "raw_contract_roll_count": len(rolls),
        "shinji_basis_price": shinji_basis_price,
        "roll_adjustments": adjustments,
        "roll_adjustment_note": (
            "At each observed contract transition, the first new-contract open is "
            "additively shifted to the prior raw-contract close. Ridge H2 and Calendar "
            "continue to receive raw bars. This is a project-defined sensitivity "
            "series, not a verified platform adjusted series."
            if shinji_basis_price == "roll_adjusted"
            else None
        ),
        "causality": (
            "Position is the signal known at each completed bar close. Execution "
            "lag is applied by the consumer, e.g. lab engine shift-by-one-bar or "
            "pre_shift_positions for Plutus."
        ),
        "raw_position_counts": dict(sorted(Counter(map(int, raw_position)).items())),
        "sleeves": {
            "ridge_h2": True,
            "ridge_roll_guard": ridge_roll_guard,
            "shinji": use_shinji,
            "shinji_roll_guard": shinji_roll_guard,
            "calendar": True,
            "calendar_legs": "core: Monday short, D_long days long",
        },
        "shinji_sessions_without_spot": sessions_without_spot,
        "expiry_flat": expiry_flat,
        "expiry_flat_note": (
            "The ensemble is flat from the 14:00 bar of each expiry session, so its "
            "target executes in the ATC and no position crosses a contract roll."
            if expiry_flat
            else None
        ),
        "shinji_roll_guard_note": (
            "Shinji is forced flat on expiry sessions and restarted for each "
            "front-month contract; its 40-bar warm-up therefore applies after "
            "every rollover. Ridge H2 and Calendar remain active."
            if shinji_roll_guard
            else None
        ),
        "ridge_roll_guard_note": (
            "Ridge H2 is forced flat on expiry sessions and restarted for each "
            "front-month contract. ATR14, rolling features, position state, and "
            "entry price therefore cannot cross a contract rollover."
            if ridge_roll_guard
            else None
        ),
    }
    if overrides:
        diagnostics["parameter_overrides"] = overrides
    return stream, diagnostics


def generate_calibrum_targets(
    futures: pd.DataFrame,
    spot: pd.DataFrame,
    package_dir: Path | str,
    *,
    quantity: int = 1,
    ensemble_mode: str = "vote",
    use_shinji: bool = True,
    shinji_basis_price: str = "raw",
    shinji_roll_guard: bool = True,
    ridge_roll_guard: bool = False,
    expiry_flat: bool = True,
) -> CalibrumTargets:
    """Generate frozen Calibrum targets for a raw-roll DB/Plutus replay.

    The original package documents Shinji as an *adjusted*-futures/spot sleeve.
    Raw front-month candles therefore remain a diagnostic replay, and the
    diagnostics keep that caveat visible.
    """

    stream, diagnostics = generate_calibrum_position_stream(
        futures,
        spot,
        package_dir,
        ensemble_mode=ensemble_mode,
        use_shinji=use_shinji,
        shinji_basis_price=shinji_basis_price,
        shinji_roll_guard=shinji_roll_guard,
        ridge_roll_guard=ridge_roll_guard,
        expiry_flat=expiry_flat,
    )
    targets = pre_shift_positions(
        stream,
        quantity=quantity,
        max_position=3 if ensemble_mode == "sum" else 1,
    )
    diagnostics["executable_target_counts"] = dict(
        sorted(Counter(targets.values()).items())
    )
    diagnostics["quantity"] = quantity
    diagnostics["ensemble_mode"] = ensemble_mode
    return CalibrumTargets(targets=targets, diagnostics=diagnostics)


class CalibrumSignalAdapter(ISignalGateway):
    """Exposes generated Calibrum targets through the application ISignalGateway port."""

    def __init__(self, targets: CalibrumTargets) -> None:
        self.targets = targets

    def get_target_position(self, timestamp: datetime, bar: Bar | None = None) -> tuple[int, str]:
        pos = self.targets.targets.get(timestamp, 0)
        return pos, f"CALIBRUM_TARGET_{pos}"



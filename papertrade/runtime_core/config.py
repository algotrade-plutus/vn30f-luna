"""Typed, non-secret configuration for the master-unified runtime."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


MAX_MASTER_UNIFIED_QTY = 10


class ConfigError(ValueError):
    """Raised when effective runtime configuration is unsafe or ambiguous."""


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    value = str(env.get(name, default)).strip()
    if not value:
        raise ConfigError(f"{name} must not be empty")
    return value


def _integer(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(env.get(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be in [{minimum}, {maximum}], got {value}")
    return value


def _number(
    env: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = str(env.get(name, default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be numeric") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}, got {value}")
    return value


@dataclass(frozen=True)
class RuntimePaths:
    state_dir: Path
    runtime_dir: Path
    log_dir: Path

    @classmethod
    def discover(cls, app_root: Path | None = None) -> "RuntimePaths":
        container_state = Path("/app/state")
        if container_state.exists():
            return cls(
                state_dir=container_state,
                runtime_dir=Path("/app/runtime"),
                log_dir=Path("/app/logs"),
            )
        root = app_root or Path(__file__).resolve().parents[1]
        return cls(
            state_dir=root / "state",
            runtime_dir=root / "runtime",
            log_dir=root / "logs",
        )


@dataclass(frozen=True)
class MasterUnifiedRuntimeConfig:
    """Validated effective settings used to wire one runtime instance.

    Credentials and the account identifier are intentionally absent.  They are
    consumed only by the broker adapter and are never included in the public
    config fingerprint.
    """

    profile: str
    quantity: int
    rollover_mode: str
    fixed_symbol: str | None
    cancel_after_s: float
    cross_points: float
    eval_interval_s: float
    account_refresh_s: float
    strategy_params: Mapping[str, object]
    paths: RuntimePaths

    def resolve_symbol(self, now, front_month_resolver) -> str:
        if self.rollover_mode == "fixed":
            if not self.fixed_symbol:
                raise ConfigError("VN30F1M is required in fixed rollover mode")
            return self.fixed_symbol
        return front_month_resolver(now)

    def public_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "quantity": self.quantity,
            "rollover_mode": self.rollover_mode,
            "fixed_symbol": self.fixed_symbol,
            "cancel_after_s": self.cancel_after_s,
            "cross_points": self.cross_points,
            "eval_interval_s": self.eval_interval_s,
            "account_refresh_s": self.account_refresh_s,
            "strategy_params": dict(self.strategy_params),
            "paths": {
                "state_dir": str(self.paths.state_dir),
                "runtime_dir": str(self.paths.runtime_dir),
                "log_dir": str(self.paths.log_dir),
            },
        }

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.public_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def _quantity(env: Mapping[str, str]) -> int:
    raw = env.get("HYBRID_GATED_QTY")
    if raw is None:
        raw = env.get("UNIFIED_QTY", env.get("CALENDAR_QTY", "1"))
    return _integer(
        {"EFFECTIVE_QTY": str(raw)},
        "EFFECTIVE_QTY",
        1,
        minimum=1,
        maximum=MAX_MASTER_UNIFIED_QTY,
    )


def _common_params(env: Mapping[str, str], prefix: str) -> dict[str, object]:
    monday_name = f"{prefix}_MONDAY_MAX_GAP_PCT"
    if prefix == "HYBRID_GATED" and monday_name not in env:
        monday_name = "HYBRID_GATED_MONDAY_MAX_GAP"
    return {
        "long_dows": (1, 2),
        "use_month_start": True,
        "use_preholiday": True,
        "use_monday_short": True,
        "use_post_expiry_monday_short": True,
        "post_exp_monday_min_basis_bps": _number(
            env, f"{prefix}_POST_EXP_MON_BASIS", -15.0
        ),
        "use_post_expiry_friday_veto": True,
        "use_december_rally": True,
        "use_expiry_thursday": True,
        "monday_max_gap_pct": _number(env, monday_name, 0.0),
        "use_fomo_gatekeeper": True,
        "max_ret_5bar": _number(env, f"{prefix}_MAX_RET_5BAR", 0.011),
        "max_ret_2bar": _number(env, f"{prefix}_MAX_RET_2BAR", 0.010),
        "ma120_threshold": _number(env, f"{prefix}_MA120_THRESHOLD", 4.77),
        "gate_ma_window": 120,
        "gate_atr_window": 20,
        "use_t2_momentum": True,
        "t2_fast_bars": 20,
        "t2_slow_bars": 50,
        "t2_macro_bars": 120,
        "t2_macro_trend_bars": 200,
        "t2_long_thresh": _number(env, f"{prefix}_T2_LONG_THRESH", 0.008),
        "t2_short_thresh": _number(env, f"{prefix}_T2_SHORT_THRESH", -0.010),
    }


def load_master_unified_config(
    profile: str,
    env: Mapping[str, str] | None = None,
    *,
    paths: RuntimePaths | None = None,
) -> MasterUnifiedRuntimeConfig:
    source = os.environ if env is None else env
    selected = profile.strip().lower()
    if selected != "hybrid":
        raise ConfigError("profile must be hybrid")

    rollover_mode = _text(source, "VN30F_ROLLOVER_MODE", "auto").lower()
    if rollover_mode not in {"auto", "fixed"}:
        raise ConfigError("VN30F_ROLLOVER_MODE must be auto or fixed")
    fixed_symbol = str(source.get("VN30F1M", "")).strip() or None
    if rollover_mode == "fixed" and fixed_symbol is None:
        raise ConfigError("VN30F1M is required in fixed rollover mode")

    prefix = "HYBRID_GATED"
    params = _common_params(source, prefix)

    account_refresh = _number(
        source,
        "ACCOUNT_SNAPSHOT_REFRESH_S",
        30.0,
        minimum=10.0,
        maximum=300.0,
    )
    return MasterUnifiedRuntimeConfig(
        profile=selected,
        quantity=_quantity(source),
        rollover_mode=rollover_mode,
        fixed_symbol=fixed_symbol,
        cancel_after_s=_number(source, f"{prefix}_CANCEL_AFTER_S", 8.0, minimum=1.0),
        cross_points=_number(source, f"{prefix}_CROSS_POINTS", 0.1, minimum=0.0),
        eval_interval_s=_number(source, f"{prefix}_EVAL_INTERVAL_S", 2.0, minimum=0.1),
        account_refresh_s=account_refresh,
        strategy_params=params,
        paths=paths or RuntimePaths.discover(),
    )

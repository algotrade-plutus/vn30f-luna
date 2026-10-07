#!/usr/bin/env python3
"""Shared helpers for local lab Step 4/5/6 scripts."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

PACKAGE_DIR = WORKSPACE / "PS_V30_Vien_Calibrum"

from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    generate_calibrum_position_stream,
)
from src.lab.backtest import BacktestConfig, evaluate  # noqa: E402
from src.lab.backtest.reporting import format_metrics  # noqa: E402

DEFAULT_FEE = 0.8

SUMMARY_METRIC_KEYS = (
    "bars",
    "trading_days",
    "total_profit",
    "total_fee",
    "profit_after_fee",
    "margin",
    "margin_after_fee",
    "sharpe",
    "sharpe_after_fee",
    "mdd_points",
    "mdd_percent",
    "hit_rate",
    "profit_per_trade",
    "profit_per_year",
    "long_trades",
    "short_trades",
)

__all__ = [
    "DEFAULT_FEE",
    "PACKAGE_DIR",
    "SUMMARY_METRIC_KEYS",
    "WORKSPACE",
    "add_common_arguments",
    "build_base_payload",
    "default_caveats",
    "evaluate",
    "format_metrics",
    "format_number",
    "frame_range",
    "generate_calibrum_position_stream",
    "json_safe",
    "load_research_frames",
    "parse_window",
    "resolve_path",
    "run_lab_backtest",
    "safe_ratio",
    "save_lab_plots",
    "selected_metrics",
    "summarize_values",
    "write_json_report",
]


def add_common_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_start: str,
    default_end: str,
    default_report: str,
    include_fee: bool = True,
) -> None:
    parser.add_argument("--start", default=default_start, help="Start date (inclusive), YYYY-MM-DD")
    parser.add_argument("--end", default=default_end, help="End date (inclusive), YYYY-MM-DD")
    parser.add_argument(
        "--source",
        choices=("dnse", "db"),
        default="dnse",
        help="Data source: DNSE parquet cache (default) or PostgreSQL algotradeDB",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="DNSE parquet cache directory; defaults to data/dnse",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="With --source dnse, use only existing parquet cache and do not download",
    )
    parser.add_argument(
        "--report",
        default=default_report,
        help="Output JSON report path; relative paths are resolved from the repo root",
    )
    if include_fee:
        parser.add_argument(
            "--fee",
            type=float,
            default=DEFAULT_FEE,
            help="Round-trip fee in index points; charged as half per position change",
        )


def parse_window(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[date, date]:
    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as exc:
        parser.error(f"invalid date: {exc}")
    if start > end:
        parser.error("--start must not be after --end")
    return start, end


def resolve_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if not path.is_absolute():
        return WORKSPACE / path
    return path


def frame_range(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"rows": 0, "observed_start": None, "observed_end": None}
    return {
        "rows": int(len(frame)),
        "observed_start": frame["Datetime"].min(),
        "observed_end": frame["Datetime"].max(),
    }


def load_research_frames(
    source: str,
    start: date,
    end: date,
    *,
    cache_dir: str | Path | None = None,
    allow_fetch: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load futures and index bars for the local lab engine."""
    if source == "db":
        from src.adapters.data import PostgresResearchSource

        database = None
        try:
            database = PostgresResearchSource()
            futures = database.load_front_month_bars(start, end)
            spot = database.load_index_bars(start, end)
        except Exception as exc:
            raise RuntimeError(
                "Unable to load bars from algotradeDB. Check .env credentials/connectivity, "
                "or use --source dnse."
            ) from exc
        finally:
            if database is not None:
                database.pool.close()

        if futures.empty or spot.empty:
            raise RuntimeError("algotradeDB returned no bars for the requested range.")

        meta = {
            "source": "postgresql:algotradeDB",
            "futures": frame_range(futures),
            "index": frame_range(spot),
        }
        return futures, spot, meta

    if source == "dnse":
        from src.adapters.data import load_or_fetch_dnse_bars

        futures, futures_meta = load_or_fetch_dnse_bars(
            "derivative",
            "VN30F1M",
            start,
            end,
            cache_dir=cache_dir,
            allow_fetch=allow_fetch,
        )
        spot, spot_meta = load_or_fetch_dnse_bars(
            "index",
            "VN30",
            start,
            end,
            cache_dir=cache_dir,
            allow_fetch=allow_fetch,
        )
        if "Contract" not in futures.columns:
            futures = futures.assign(Contract="VN30F1M")

        meta = {
            "source": "dnse:https://api.dnse.com.vn/chart-api/v2/ohlcs",
            "futures": futures_meta,
            "index": spot_meta,
        }
        return futures, spot, meta

    raise ValueError(f"Unknown source: {source}")


def run_lab_backtest(
    futures: pd.DataFrame,
    spot: pd.DataFrame,
    *,
    fee: float = DEFAULT_FEE,
    parameter_overrides: dict[str, Any] | None = None,
    use_shinji: bool = True,
    shinji_basis_price: str = "raw",
    shinji_roll_guard: bool = False,
    ridge_roll_guard: bool = False,
):
    """Generate the unshifted Calibrum position stream and evaluate it locally."""
    stream, diagnostics = generate_calibrum_position_stream(
        futures,
        spot,
        PACKAGE_DIR,
        parameter_overrides=parameter_overrides,
        use_shinji=use_shinji,
        shinji_basis_price=shinji_basis_price,
        shinji_roll_guard=shinji_roll_guard,
        ridge_roll_guard=ridge_roll_guard,
    )
    config = BacktestConfig(round_trip_fee_points=fee)
    result = evaluate(stream, config)
    return result, diagnostics, config


def json_safe(value: Any) -> Any:
    """Convert NumPy/pandas/path/date values into JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def write_json_report(report_path: str | Path, payload: dict[str, Any]) -> Path:
    path = resolve_path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(json_safe(payload), indent=2, ensure_ascii=False, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def default_caveats(source: str) -> list[str]:
    caveats = [
        "Headline README metrics remain Native SDK/evangelion verification numbers from "
        "PS_V30_Vien_Calibrum/native_verification.json.",
        "Lab engine uses local point-based accounting; it is not the Plutus VND execution simulation.",
    ]
    if source == "dnse":
        caveats.append(
            "DNSE data is a public continuous front-month candle cache; it is not native-parity "
            "adjusted contract data."
        )
    else:
        caveats.append(
            "PostgreSQL data is raw front-month data from algotradeDB; it is not native-parity "
            "adjusted contract data."
        )
    return caveats


def build_base_payload(
    *,
    report_name: str,
    sample: str,
    start: date,
    end: date,
    source: str,
    data_meta: dict[str, Any],
    result: Any,
    diagnostics: dict[str, Any],
    config: BacktestConfig,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "report": report_name,
        "engine": "src.lab.backtest",
        "sample": sample,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_window": {"start": start, "end": end},
        "observed_window": {
            "start": result.frame["Datetime"].min(),
            "end": result.frame["Datetime"].max(),
            "bars": int(len(result.frame)),
        },
        "data": data_meta,
        "fee_convention": {
            "round_trip_fee_points": config.round_trip_fee_points,
            "fee_per_position_unit": config.fee_per_position_unit,
            "note": "A 0.8-point round-trip fee is charged as 0.4 point per position change.",
        },
        "config": {
            "annualization_days": config.annualization_days,
            "require_discrete_position": config.require_discrete_position,
            "position_tolerance": config.position_tolerance,
        },
        "metrics": result.metrics.as_dict(),
        "diagnostics": diagnostics,
        "caveats": default_caveats(source),
    }
    if extra:
        payload.update(extra)
    return payload


def selected_metrics(metrics: Any) -> dict[str, Any]:
    return {key: getattr(metrics, key) for key in SUMMARY_METRIC_KEYS if hasattr(metrics, key)}


def format_number(value: Any, fmt: str = "{:.2f}", missing: str = "n/a") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return missing
    if not math.isfinite(number):
        return missing
    return fmt.format(number)


def safe_ratio(numerator: Any, denominator: Any) -> float | None:
    try:
        top = float(numerator)
        bottom = float(denominator)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(top) or not math.isfinite(bottom) or bottom == 0.0:
        return None
    return top / bottom


def summarize_values(values: Any) -> dict[str, float] | None:
    numeric_values: list[float] = []
    for value in values:
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(candidate):
            numeric_values.append(candidate)

    if not numeric_values:
        return None

    return {
        "count": len(numeric_values),
        "min": min(numeric_values),
        "max": max(numeric_values),
        "mean": sum(numeric_values) / len(numeric_values),
        "spread": max(numeric_values) - min(numeric_values),
    }

def save_lab_plots(result: Any, output_stem: str | Path, title: str = "") -> list[Path]:
    """Render the built-in lab plots as simple PNGs and return their paths."""
    import matplotlib

    matplotlib.use("Agg")

    from src.lab.backtest.plotting import plot_daily_profit, plot_pnl

    stem = resolve_path(output_stem)
    stem.parent.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    for name, figure in (
        ("equity", plot_pnl(result, title=title)),
        ("daily_profit", plot_daily_profit(result, title=title)),
    ):
        destination = stem.with_name(f"{stem.name}_{name}.png")
        figure.savefig(destination, dpi=180, bbox_inches="tight")
        outputs.append(destination)

    return outputs

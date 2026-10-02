#!/usr/bin/env python3
"""Native parity and Finpros gate verification for Calibrum."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path("/workspaces/Finpros")
HERE = ROOT / "alphas" / "PS_V30_Vien_Calibrum"
REFERENCE_DIR = ROOT / "alphas" / "PS_V30_Vien_Master_Ensemble"
sys.path[:0] = [str(HERE), str(ROOT), "/home/jovyan/shared-storage/libs"]

import loadlibs  # noqa: E402,F401
import dm_manager  # noqa: E402
from PS_V30_Vien_Calibrum import CalibrumAlpha  # noqa: E402
from alphas.PS_V30_Vien_Master_Ensemble.PS_V30_Vien_Master_Ensemble import (  # noqa: E402
    MasterEnsembleAlpha,
)


FEE = 0.4


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def metric_subset(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "profit_after_fee", "total_profit", "sharpe_after_fee",
        "margin_after_fee", "mdd_point", "mdd", "total_trade", "hitrate",
        "hitrate_long", "hitrate_short", "trading_per_day",
    )
    return {key: metrics.get(key) for key in keys}


def main() -> None:
    if not Path("/.dockerenv").exists():
        raise RuntimeError("Verifier phải chạy trong evangelion-workspace-1")

    config = load_json(HERE / "config.json")
    config["working_path"] = str(HERE)
    requests = [dict(block, bars=8000) for block in config["data"]]
    dm_list = dm_manager.DMManager("calibrum_native_verification").get_data(requests)
    if len(dm_list) != 2:
        raise RuntimeError(f"Cần 2 native DM, nhận {len(dm_list)}")
    for dm in dm_list:
        frame = dm.data
        datetime_column = "datetime" if "datetime" in frame.columns else "Datetime"
        timestamps = pd.to_datetime(frame[datetime_column])
        if not timestamps.dt.year.isin((2020, 2021, 2022)).all():
            raise RuntimeError("Native data vượt phạm vi khóa 2020-2022")

    started = time.perf_counter()
    calibrum = CalibrumAlpha(config)
    actual = calibrum.generate(dm_list).reset_index(drop=True)
    generate_seconds = time.perf_counter() - started

    reference_config = load_json(REFERENCE_DIR / "config.json")
    reference_config["working_path"] = str(REFERENCE_DIR)
    expected = MasterEnsembleAlpha(reference_config).generate(dm_list).reset_index(drop=True)
    if len(actual) != len(expected):
        raise RuntimeError("Calibrum và Master khác số row")
    datetime_match = bool(pd.to_datetime(actual["Datetime"]).equals(pd.to_datetime(expected["Datetime"])))
    close_match = bool(np.array_equal(actual["Close"].to_numpy(float), expected["Close"].to_numpy(float)))
    position_diff = actual["Position"].to_numpy(int) - expected["Position"].to_numpy(int)
    mismatch_count = int(np.count_nonzero(position_diff))
    if not datetime_match or not close_match or mismatch_count:
        raise RuntimeError(
            f"Parity FAIL: datetime={datetime_match}, close={close_match}, positions={mismatch_count}"
        )

    metrics = calibrum.backtest(fee=FEE).Get_metrics()
    calibrum.test_alpha()
    leak_pass = bool(getattr(calibrum, "is_pass_futures_leak", False))
    overfit_pass = bool(getattr(calibrum, "is_pass_overfit", False))
    gates = {
        "generate_under_20_seconds": generate_seconds < 20.0,
        "margin_ge_15_bps": float(metrics["margin_after_fee"]) >= 15.0,
        "sharpe_ge_1_5": float(metrics["sharpe_after_fee"]) >= 1.5,
        "trades_ge_180": int(metrics["total_trade"]) >= 180,
        "futures_leak_pass": leak_pass,
        "overfit_pass": overfit_pass,
        "exact_master_parity": mismatch_count == 0 and datetime_match and close_match,
    }
    result = {
        "alpha": config["name"],
        "scope": {
            "start": str(pd.to_datetime(actual["Datetime"]).min()),
            "end": str(pd.to_datetime(actual["Datetime"]).max()),
            "rows": len(actual),
            "feeds": [
                {"ticker": str(getattr(dm, "ticker", "")),
                 "timeframe": str(getattr(dm, "timeframe", "")),
                 "rows": len(dm.data)}
                for dm in dm_list
            ],
        },
        "generate_seconds": generate_seconds,
        "parity": {
            "datetime_match": datetime_match,
            "close_match": close_match,
            "position_mismatches": mismatch_count,
            "max_position_abs_diff": int(np.max(np.abs(position_diff))),
        },
        "native_metrics": metric_subset(metrics),
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "submission_files": [
            "PS_V30_Vien_Calibrum.py", "config.json",
            "PS_V30_Vien_Calibrum_model.pt",
        ],
        "sha256": {
            "source": sha(HERE / "PS_V30_Vien_Calibrum.py"),
            "config": sha(HERE / "config.json"),
            "model": sha(HERE / "PS_V30_Vien_Calibrum_model.pt"),
        },
        "known_limit": (
            "time_to_start=Auto does not prove that production supplies a completed "
            "30-minute bar; scheduler expansion and partial-bar timing still require "
            "a production payload trace."
        ),
    }
    (HERE / "native_verification.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if not result["all_gates_pass"]:
        raise SystemExit("Calibrum chưa vượt toàn bộ gate")


if __name__ == "__main__":
    main()

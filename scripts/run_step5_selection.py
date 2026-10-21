#!/usr/bin/env python3
"""Step 5: the pre-registered selection tests on the in-sample lab run.

Rule (report chapter 5.1): Sharpe after fee decides; a gap under 0.2 is a tie, broken by lower drawdown per contract,
then by fewer rules. Parameter grids only check stability: both neighbours must stay profitable with at least 70% of
the frozen value's Sharpe. Frozen parameters are never replaced by a neighbour.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from lab_common import PACKAGE_DIR, load_research_frames, write_json_report  # noqa: E402
from src.adapters.strategies.calibrum_signal_source import (  # noqa: E402
    apply_session_rules,
    generate_calibrum_position_stream,
)
from src.lab.backtest import BacktestConfig, evaluate  # noqa: E402

START, END = date(2021, 6, 1), date(2022, 12, 30)
FEE = 0.8
TIE = 0.2
NEIGHBOUR_SHARPE_SHARE = 0.7
CALENDAR_CORE_ONLY = {
    "calendar_use_month_start": False,
    "calendar_use_preholiday": False,
    "calendar_use_expiry_thursday": False,
}


def score(stamps: pd.Series, close: pd.Series, position: np.ndarray, scale: int = 1) -> dict[str, float]:
    stream = pd.DataFrame({"Datetime": stamps, "Close": close, "Position": position})
    metrics = evaluate(stream, BacktestConfig(round_trip_fee_points=FEE, max_position=float(scale))).metrics
    return {
        "net_points": metrics.profit_after_fee / scale,
        "sharpe": metrics.sharpe_after_fee,
        "mdd_points": metrics.mdd_points / scale,
        "trades": metrics.total_trading_quantity / scale,
        "margin_bps": metrics.margin_after_fee,
    }


def sleeve(futures: pd.DataFrame, spot: pd.DataFrame, name: str, overrides: dict[str, Any]) -> dict[str, float]:
    stream, _ = generate_calibrum_position_stream(futures, spot, PACKAGE_DIR, parameter_overrides=overrides)
    return score(stream.Datetime, stream.Close, apply_session_rules(stream[name].to_numpy(), stream.Datetime))


def ensemble(futures: pd.DataFrame, spot: pd.DataFrame, mode: str, overrides: dict[str, Any]) -> dict[str, float]:
    stream, _ = generate_calibrum_position_stream(
        futures, spot, PACKAGE_DIR, ensemble_mode=mode, parameter_overrides=overrides
    )
    return score(stream.Datetime, stream.Close, stream.Position.to_numpy(), 3 if mode == "sum" else 1)


def pick(a_name: str, a: dict, b_name: str, b: dict, b_is_simpler: bool) -> tuple[str, str]:
    gap = a["sharpe"] - b["sharpe"]
    if abs(gap) >= TIE:
        winner = a_name if gap > 0 else b_name
        return winner, f"Sharpe gap {abs(gap):.2f} >= {TIE}"
    if abs(a["mdd_points"] - b["mdd_points"]) > 1e-9:
        winner = a_name if a["mdd_points"] < b["mdd_points"] else b_name
        return winner, f"tie on Sharpe (gap {abs(gap):.2f}); lower drawdown"
    return (b_name if b_is_simpler else a_name), "tie on Sharpe and drawdown; fewer rules"


def stability(results: dict[float, dict], frozen: float) -> dict[str, Any]:
    base = results[frozen]["sharpe"]
    neighbours = {value: r for value, r in results.items() if value != frozen}
    passed = all(r["net_points"] > 0 and r["sharpe"] >= NEIGHBOUR_SHARPE_SHARE * base for r in neighbours.values())
    return {"frozen": frozen, "base_sharpe": base, "stable": passed}


def print_rows(title: str, rows: dict[Any, dict]) -> None:
    print(f"\n{title}")
    frame = pd.DataFrame(rows).T[["net_points", "sharpe", "mdd_points", "trades", "margin_bps"]]
    with pd.option_context("display.float_format", "{:,.2f}".format, "display.width", 120):
        print(frame)


def main() -> int:
    futures, spot, _ = load_research_frames("dnse", START, END, allow_fetch=False)
    report: dict[str, Any] = {"window": [START.isoformat(), END.isoformat()], "fee": FEE, "rule": __doc__}

    calendar = {"full": sleeve(futures, spot, "Calendar", {}), "core": sleeve(futures, spot, "Calendar", CALENDAR_CORE_ONLY)}
    winner, reason = pick("full", calendar["full"], "core", calendar["core"], b_is_simpler=True)
    report["calendar"] = {"results": calendar, "choice": winner, "reason": reason}
    print_rows("Calendar sleeve: full against core legs only", calendar)
    print(f"-> keep {winner} ({reason})")
    calendar_overrides = {} if winner == "full" else CALENDAR_CORE_ONLY

    ridge = {t: sleeve(futures, spot, "Ridge", {"ridge_entry_threshold": t}) for t in (0.14, 0.18, 0.22)}
    report["ridge_threshold"] = {"results": ridge, **stability(ridge, 0.18)}
    print_rows("Ridge sleeve: entry threshold", ridge)
    print(f"-> stable: {report['ridge_threshold']['stable']}")

    shinji = {w: sleeve(futures, spot, "Shinji", {"shinji_window": w}) for w in (30, 40, 50)}
    report["shinji_window"] = {"results": shinji, **stability(shinji, 40)}
    print_rows("Shinji sleeve: z-score window", shinji)
    print(f"-> stable: {report['shinji_window']['stable']}")

    methods = {mode: ensemble(futures, spot, mode, calendar_overrides) for mode in ("vote", "sum")}
    winner, reason = pick("vote", methods["vote"], "sum", methods["sum"], b_is_simpler=False)
    report["ensemble"] = {"results": methods, "choice": winner, "reason": reason}
    print_rows("Ensemble, per contract", methods)
    print(f"-> official choice: {winner} ({reason})")

    path = write_json_report("reports/step5_selection_lab.json", report)
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

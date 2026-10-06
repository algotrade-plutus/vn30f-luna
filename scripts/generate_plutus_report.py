#!/usr/bin/env python3
"""Generate a Markdown summary from Plutus backtest JSON reports."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

DEFAULT_REPORT_FILES = [
    "reports/calibrum_raw_roll_insample_plutus.json",
    "reports/calibrum_raw_roll_guards_oos_2023-2024_1contract_100m.json",
    "reports/calibrum_raw_roll_guards_forward_2025-01-01_2026-10-01_1contract_100m.json",
]
DEFAULT_OUTPUT = "docs/PLUTUS_BACKTEST_REPORT.md"


def resolve_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if not path.is_absolute():
        return WORKSPACE / path
    return path


def as_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def fmt_number(value, spec: str = "{:,.0f}", missing: str = "—", signed: bool = False) -> str:
    number = as_number(value)
    if number is None:
        return missing
    text = spec.format(number)
    if signed and number > 0:
        text = "+" + text
    return text


def fmt_percent(value, decimals: int = 2, missing: str = "—", signed: bool = False) -> str:
    number = as_number(value)
    if number is None:
        return missing
    text = f"{number:.{decimals}f}%"
    if signed and number > 0:
        text = "+" + text
    return text


def get_nested(payload: dict, *keys):
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def fills_count(payload: dict):
    fills = payload.get("fills")
    if isinstance(fills, list):
        return len(fills)
    fallback = payload.get("fully_filled_orders")
    if fallback is not None:
        return fallback
    return get_nested(payload, "order_states", "filled")


def report_section(path: Path, payload: dict) -> list[str]:
    lines = [f"## `{path.name}`", "", "| Metric | Value |", "|---|---|"]

    def add(label: str, value) -> None:
        lines.append(f"| {label} | {value} |")

    add("Status", payload.get("status", "—"))
    engine = payload.get("engine")
    add("Engine", f"`{engine}`" if engine else "—")
    add("Sample", payload.get("sample", "—"))
    add("Signal", payload.get("signal", "—"))
    add(
        "Window",
        f"{payload.get('start_date', '—')} → {payload.get('end_date', '—')}",
    )
    add(
        "Observed data",
        f"{payload.get('observed_data_start', '—')} → {payload.get('observed_data_end', '—')}",
    )
    add("Initial capital (VND)", fmt_number(payload.get("initial_capital")))
    add("Final capital (VND)", fmt_number(payload.get("final_capital")))
    add("Net PnL (VND)", fmt_number(payload.get("net_pnl"), signed=True))
    add("Return", fmt_percent(payload.get("return_pct"), signed=True))
    add("Annualized return", fmt_percent(payload.get("annualized_return_pct"), signed=True))
    add("Sharpe", fmt_number(payload.get("sharpe"), "{:.3f}"))
    add("Max drawdown", fmt_percent(payload.get("mdd_pct"), 3))
    add(
        "Orders / fills",
        f"{fmt_number(payload.get('orders'))} / {fmt_number(fills_count(payload))}",
    )
    add("Total charges (VND)", fmt_number(payload.get("total_charges")))
    add(
        "Peak margin utilisation",
        fmt_percent(payload.get("peak_margin_utilisation_pct"), 2),
    )
    add(
        "Margin warnings / calls / liquidations",
        f"{payload.get('margin_warnings_80', '—')} / "
        f"{payload.get('margin_calls_90', '—')} / "
        f"{payload.get('forced_liquidations_100', '—')}",
    )
    add("Profit factor", fmt_number(
        payload.get("profit_factor_realised_after_linked_fill_charges"), "{:.3f}"
    ))
    evidence = payload.get("execution_evidence")
    add("Execution evidence", f"`{evidence}`" if evidence else "—")
    replay = payload.get("calibrum_replay")
    if isinstance(replay, dict):
        add("Source mode", replay.get("source_mode", "—"))
        add("Raw contract rolls", replay.get("raw_contract_roll_count", "—"))
    lines.append("")
    return lines


def build_markdown(available: list[tuple[Path, dict]], missing: list[str], failed: list[dict]) -> str:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    lines = [
        "# Plutus Execution Report",
        "",
        f"Generated at: {generated_at}",
        "",
        "These reports are supplementary VND-denominated execution simulations produced by "
        "`plutus.market.session.ExchangeSession` (HNX fees, VSDC clearing, PIT, margin model). "
        "They are not the headline point-based numbers, which remain the Native SDK/evangelion "
        "verification results from `PS_V30_Vien_Calibrum/native_verification.json`.",
        "",
    ]

    for path, payload in available:
        lines.extend(report_section(path, payload))

    if missing:
        lines.extend(["## Missing report files", ""])
        lines.extend([f"- `{item}`" for item in missing])
        lines.append("")

    if failed:
        lines.extend(["## Unreadable report files", ""])
        lines.extend([f"- `{item['path']}`: {item['error']}" for item in failed])
        lines.append("")

    lines.extend(
        [
            "## Interpretation caveat",
            "",
            "- Plutus reports simulate execution in VND with statutory charges and margin; compare them against the point-based lab/native numbers only with that context.",
            "- Local lab backtests (`reports/step*_lab.json`) use point-based accounting and are separate from these execution simulations.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-file",
        action="append",
        help="Plutus JSON report to include; repeat for multiple files (defaults to the known set)",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output Markdown path")
    args = parser.parse_args()

    report_files = args.report_file or DEFAULT_REPORT_FILES
    available: list[tuple[Path, dict]] = []
    missing: list[str] = []
    failed: list[dict] = []

    for relative in report_files:
        path = resolve_path(relative)
        if not path.exists():
            missing.append(str(relative))
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            failed.append({"path": str(relative), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not isinstance(payload, dict):
            failed.append({"path": str(relative), "error": "not a JSON object"})
            continue
        available.append((path, payload))

    output_path = resolve_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_markdown(available, missing, failed), encoding="utf-8")

    print(f"Wrote {output_path}")
    for path, payload in available:
        print(
            f"  - {path.name}: {payload.get('status', '?')} "
            f"net_pnl={fmt_number(payload.get('net_pnl'), signed=True)} VND "
            f"sharpe={fmt_number(payload.get('sharpe'), '{:.3f}')}"
        )
    if missing:
        print(f"Missing files: {', '.join(missing)}")
    if not available:
        print("No Plutus report files were available.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

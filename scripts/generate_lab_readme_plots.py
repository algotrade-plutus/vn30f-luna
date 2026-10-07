#!/usr/bin/env python3
"""Generate 6 lab backtest plots (Equity & Daily Profit for IS, OOS, Forward) for README."""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPT_DIR), str(WORKSPACE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from lab_common import (  # noqa: E402
    load_research_frames,
    run_lab_backtest,
    save_lab_plots,
)

PERIODS = [
    {
        "id": "is",
        "name": "In-Sample",
        "start": date(2021, 1, 15),
        "end": date(2022, 12, 30),
        "title": "In-Sample Lab Backtest (2021 - 2022)",
    },
    {
        "id": "oos",
        "name": "Out-of-Sample",
        "start": date(2023, 1, 1),
        "end": date(2024, 12, 19),
        "title": "Out-of-Sample Lab Backtest (2023 - 2024)",
    },
    {
        "id": "forward",
        "name": "Forward",
        "start": date(2025, 1, 1),
        "end": date(2026, 10, 1),
        "title": "Forward Walk Lab Backtest (2025 - 2026)",
    },
    {
        "id": "full",
        "name": "Full Period",
        "start": date(2021, 1, 15),
        "end": date(2026, 10, 1),
        "title": "Full Life-Cycle Lab Backtest (2021 - 2026)",
    },
]


def main() -> int:
    reports_fig_dir = WORKSPACE / "reports" / "figures"
    readme_img_dir = WORKSPACE / "image" / "README"

    reports_fig_dir.mkdir(parents=True, exist_ok=True)
    readme_img_dir.mkdir(parents=True, exist_ok=True)

    generated_files = []

    print("=== Generating 6 Lab Backtest Plots ===")
    for period in PERIODS:
        p_id = period["id"]
        name = period["name"]
        start = period["start"]
        end = period["end"]
        title = period["title"]

        print(f"\nProcessing {name} ({start} -> {end})...")
        futures, spot, meta = load_research_frames("dnse", start, end, allow_fetch=True)
        result, diagnostics, config = run_lab_backtest(futures, spot)

        print(f"  Bars: {len(futures)}")
        print(f"  Profit after fee: {result.metrics.profit_after_fee:.2f} pts")
        print(f"  Sharpe after fee: {result.metrics.sharpe_after_fee:.2f}")

        output_stem = reports_fig_dir / f"{p_id}_lab"
        paths = save_lab_plots(result, output_stem, title=title)

        for p in paths:
            readme_target = readme_img_dir / p.name
            shutil.copy2(p, readme_target)
            generated_files.append((p, readme_target))
            print(f"  Saved: {p.relative_to(WORKSPACE)} and {readme_target.relative_to(WORKSPACE)}")

    print(f"\nSuccessfully generated {len(generated_files)} plot files!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

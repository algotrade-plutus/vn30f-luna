"""Write the strict Plutus Verify v2 results contract without a runtime SDK."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any

_UNITS = {"fraction", "ratio", "count", "currency_usd", "seconds"}


def emit_plutus_results(
    workspace: Path,
    step_id: str,
    metrics: dict[str, tuple[float | int, str]],
    *,
    artifacts: list[dict[str, str]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Atomically emit ``.plutus/run/<step_id>/results.json``."""

    rows = []
    for name, (value, unit) in metrics.items():
        if unit not in _UNITS:
            raise ValueError(f"Unsupported Plutus metric unit: {unit}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Metric {name} is not finite: {value}")
        rows.append({"name": name, "value": value, "unit": unit})

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    payload = {
        "schema_version": "1.0",
        "step_id": step_id,
        "metrics": rows,
        "artifacts": artifacts or [],
        "metadata": {"git_commit": commit or None, **(metadata or {})},
    }
    target = workspace / ".plutus" / "run" / step_id / "results.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target

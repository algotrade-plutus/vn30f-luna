#!/usr/bin/env python3
"""Map the verified production snapshot to local files and Git history."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout if binary else result.stdout.decode().strip()


def historical_matches(repo_path: str, expected_sha256: str, commits: list[str]) -> list[str]:
    matches = []
    for commit in commits:
        result = subprocess.run(
            ["git", "show", f"{commit}:{repo_path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0 and hashlib.sha256(result.stdout).hexdigest() == expected_sha256:
            matches.append(commit)
    return matches


def compare_file(
    *,
    context: str,
    relative: str,
    production: dict[str, Any],
    snapshot_path: Path,
    repo_root: Path,
    commits: list[str],
) -> dict[str, Any]:
    local_path = repo_root / "papertrade" / relative
    local_digest = sha256(local_path)
    expected = str(production["sha256"])
    matches = historical_matches(f"papertrade/{relative}", expected, commits)
    if local_digest == expected:
        classification = "LOCAL_EXACT"
    elif local_digest is None:
        classification = "PRODUCTION_ONLY"
    elif matches:
        classification = "LOCAL_CHANGED_FROM_TRACKED_BASELINE"
    else:
        classification = "RECOVERED_PRODUCTION_DIFFERS_FROM_LOCAL"
    return {
        "context": context,
        "path": relative,
        "snapshot_path": str(snapshot_path),
        "origin": production.get("origin"),
        "origin_source": production.get("source"),
        "production_sha256": expected,
        "local_path": str(local_path),
        "local_sha256": local_digest,
        "classification": classification,
        "git_exact_commits": matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "runtime-baseline/production-source",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "runtime-baseline/source-map.json",
    )
    args = parser.parse_args()

    repo_root = Path(git("rev-parse", "--show-toplevel"))
    manifest = json.loads((args.snapshot / "source-manifest.json").read_text())
    commits = str(git("rev-list", "--all")).splitlines()
    files = []
    for relative, production in manifest["files"].items():
        files.append(
            compare_file(
                context="trading",
                relative=relative,
                production=production,
                snapshot_path=args.snapshot / "app" / relative,
                repo_root=repo_root,
                commits=commits,
            )
        )
    for relative, production in manifest.get("dashboard_files", {}).items():
        files.append(
            compare_file(
                context="dashboard",
                relative=relative,
                production=production,
                snapshot_path=args.snapshot / "dashboard-app" / relative,
                repo_root=repo_root,
                commits=commits,
            )
        )

    production_paths = {item["path"] for item in files if item["context"] == "trading"}
    local_only = []
    for root_name in ("algotrade_adapter", "alphas", "luna_core", "scripts", "dashboard"):
        root = repo_root / "algotrade" / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".html", ".js", ".css"}:
                continue
            relative = str(path.relative_to(repo_root / "algotrade"))
            if relative not in production_paths:
                local_only.append(relative)

    counts: dict[str, int] = {}
    for item in files:
        key = str(item["classification"])
        counts[key] = counts.get(key, 0) + 1
    output = {
        "schema_version": 1,
        "production_image": manifest["image"],
        "snapshot_verified": bool(manifest.get("verified_against_effective_runtime")),
        "summary": dict(sorted(counts.items())),
        "files": sorted(files, key=lambda item: (item["context"], item["path"])),
        "local_only_files": local_only,
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(f"Wrote production source map to {args.output}")
    print(json.dumps(output["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

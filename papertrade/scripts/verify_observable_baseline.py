#!/usr/bin/env python3
"""Verify the strategy-preserving baseline plus observability release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


STRATEGY_OVERRIDES = (
    "algotrade_adapter/safe_alpha.py",
    "alphas/master_unified/service.py",
    "alphas/master_unified/genesis_engine.py",
    "alphas/master_unified/schedule.py",
)
OBSERVABILITY_OVERRIDES = (
    "algotrade_adapter/runtime_observability.py",
    "scripts/container_entrypoint.py",
    "scripts/verify_flat_account.py",
    "dashboard/server.py",
    "dashboard/static/index.html",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def effective_digest(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, value in sorted(files.items()):
        digest.update(path.encode() + b"\0" + value.encode() + b"\n")
    return digest.hexdigest()


def host_bundle_digest(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, value in sorted(files.items()):
        digest.update(path.encode() + b"\0" + value.encode() + b"\n")
    return digest.hexdigest()


def verify_local(root: Path, release: dict[str, Any]) -> None:
    captured = json.loads(
        (root / "production-source" / "source-manifest.json").read_text()
    )
    if release["base_image"] != captured["image"]:
        raise ValueError("Observable release base differs from captured production")

    files = release.get("source_files")
    if not isinstance(files, dict):
        raise ValueError("Observable release has no source_files map")
    for path in STRATEGY_OVERRIDES:
        source = root / "production-source" / "app" / path
        observed = sha256(source)
        expected = str(captured["files"][path]["sha256"])
        if observed != expected or files.get(path) != expected:
            raise ValueError(f"Captured strategy override changed: {path}")
    for path in OBSERVABILITY_OVERRIDES:
        observed = sha256(root / "observable-overrides" / path)
        if files.get(path) != observed:
            raise ValueError(f"Frozen observability override changed: {path}")
    for path, expected in files.items():
        observed = sha256(root / "observable-source" / "app" / path)
        if observed != expected:
            raise ValueError(f"Merged observable source changed: {path}")

    calculated = effective_digest({str(k): str(v) for k, v in files.items()})
    if calculated != release.get("effective_source_sha256"):
        raise ValueError("Observable effective source digest mismatch")
    if release.get("behavior_policy") != "preserve_ec2_strategy_add_read_only_observability":
        raise ValueError("Unexpected observable release behavior policy")
    expected_bundle = release.get("host_bundle_files")
    if not isinstance(expected_bundle, dict) or not expected_bundle:
        raise ValueError("Observable release has no host bundle file map")
    observed_bundle = {}
    for path in sorted((root.parent / "deploy").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            relative = path.relative_to(root.parent).as_posix()
            mode = path.stat().st_mode & 0o777
            observed_bundle[relative] = f"{mode:04o}:{sha256(path)}"
    if observed_bundle != expected_bundle:
        raise ValueError("Observable host bundle files changed")
    if host_bundle_digest(observed_bundle) != release.get("host_bundle_sha256"):
        raise ValueError("Observable host bundle digest mismatch")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", str(release.get("release_id"))):
        raise ValueError("Unsafe observable release ID")

    dockerfile = (root / "Dockerfile.observable").read_text()
    first = next(line.strip() for line in dockerfile.splitlines() if line.strip())
    if first != f"FROM {release['base_image']}":
        raise ValueError("Observable Dockerfile does not pin captured image digest")


def verify_image(image: str, release: dict[str, Any]) -> None:
    probe = """import hashlib,json,pathlib,sys
paths=json.load(sys.stdin)
result={}
for relative in paths:
    path=pathlib.Path('/app')/relative
    result[relative]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
result['__release__']=json.loads(pathlib.Path('/app/release.json').read_text())
print(json.dumps(result,separators=(',',':')))
"""
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-i", "--platform", "linux/amd64",
            "--entrypoint", "python", image, "-c", probe,
        ],
        input=json.dumps(sorted(release["source_files"])),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=120,
    )
    observed = json.loads(result.stdout)
    mismatches = {
        path: {"expected": expected, "observed": observed.get(path)}
        for path, expected in release["source_files"].items()
        if observed.get(path) != expected
    }
    if mismatches:
        raise ValueError(f"Observable image source mismatch: {mismatches}")
    if observed.get("__release__") != release:
        raise ValueError("Embedded observable release manifest differs")

    inspect = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image], text=True)
    )[0]
    labels = inspect.get("Config", {}).get("Labels", {}) or {}
    if labels.get("org.opencontainers.image.version") != release["release_id"]:
        raise ValueError("Observable image release label differs")
    if labels.get("io.algotrade.source-sha256") != release["effective_source_sha256"]:
        raise ValueError("Observable image source label differs")
    if (inspect.get("Os"), inspect.get("Architecture")) != ("linux", "amd64"):
        raise ValueError("Observable image must be linux/amd64")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / "runtime-baseline")
    parser.add_argument("--image")
    args = parser.parse_args()
    release = json.loads((args.root / "observable-release-manifest.json").read_text())
    verify_local(args.root, release)
    if args.image:
        verify_image(args.image, release)
    print(json.dumps({
        "release_id": release["release_id"],
        "effective_source_sha256": release["effective_source_sha256"],
        "files_verified": len(release["source_files"]),
        "image_verified": bool(args.image),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

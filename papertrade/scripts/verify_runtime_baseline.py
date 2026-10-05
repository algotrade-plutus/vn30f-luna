#!/usr/bin/env python3
"""Verify the recovered source snapshot and optional immutable baseline image."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def effective_digest(manifest: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for group in ("files", "dashboard_files"):
        for path, item in sorted(manifest.get(group, {}).items()):
            digest.update(group.encode() + b"\0" + path.encode() + b"\0")
            digest.update(str(item["sha256"]).encode() + b"\n")
    return digest.hexdigest()


def expected_unified_files(manifest: dict[str, Any]) -> dict[str, str]:
    expected = {
        path: str(item["sha256"])
        for path, item in manifest["files"].items()
    }
    expected.update(
        {
            path: str(item["sha256"])
            for path, item in manifest.get("dashboard_files", {}).items()
        }
    )
    return expected


def verify_snapshot(root: Path, manifest: dict[str, Any]) -> None:
    for path, item in manifest["files"].items():
        actual = sha256(root / "production-source" / "app" / path)
        if actual != item["sha256"]:
            raise ValueError(f"Trading snapshot hash mismatch: {path}")
    for path, item in manifest.get("dashboard_files", {}).items():
        actual = sha256(root / "production-source" / "dashboard-app" / path)
        if actual != item["sha256"]:
            raise ValueError(f"Dashboard snapshot hash mismatch: {path}")


def verify_image(image: str, expected: dict[str, str], release: dict[str, Any]) -> None:
    probe = """import hashlib,json,pathlib,sys
paths=json.load(sys.stdin)
result={}
for relative in paths:
    p=pathlib.Path('/app')/relative
    result[relative]=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
result['__release__']=json.loads(pathlib.Path('/app/release.json').read_text())
print(json.dumps(result,separators=(',',':')))
"""
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-i", "--platform", "linux/amd64",
            "--entrypoint", "python", image, "-c", probe,
        ],
        input=json.dumps(sorted(expected)),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=120,
    )
    observed = json.loads(result.stdout)
    mismatches = {
        path: {"expected": digest, "observed": observed.get(path)}
        for path, digest in expected.items()
        if observed.get(path) != digest
    }
    if mismatches:
        raise ValueError(f"Image source mismatch: {mismatches}")
    if observed.get("__release__") != release:
        raise ValueError("Embedded release manifest differs from local manifest")

    inspect = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image], text=True)
    )[0]
    labels = inspect.get("Config", {}).get("Labels", {}) or {}
    if labels.get("org.opencontainers.image.version") != release["release_id"]:
        raise ValueError("Image version label does not match release ID")
    if labels.get("io.algotrade.source-sha256") != release["effective_source_sha256"]:
        raise ValueError("Image source label does not match effective source digest")
    if inspect.get("Architecture") != "amd64" or inspect.get("Os") != "linux":
        raise ValueError("Baseline image must be linux/amd64")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1] / "runtime-baseline"
    )
    parser.add_argument("--image")
    args = parser.parse_args()

    source_manifest = json.loads(
        (args.root / "production-source" / "source-manifest.json").read_text()
    )
    release = json.loads((args.root / "release-manifest.json").read_text())
    verify_snapshot(args.root, source_manifest)

    calculated = effective_digest(source_manifest)
    if calculated != release["effective_source_sha256"]:
        raise ValueError(
            f"Effective source digest mismatch: {calculated} != "
            f"{release['effective_source_sha256']}"
        )
    if release["base_image"] != source_manifest["image"]:
        raise ValueError("Release base image differs from captured image")

    expected = expected_unified_files(source_manifest)
    for path, digest in release["overrides"].items():
        if expected.get(path) != digest:
            raise ValueError(f"Release override does not match snapshot: {path}")

    dockerfile = (args.root / "Dockerfile").read_text()
    first_instruction = next(
        line.strip() for line in dockerfile.splitlines() if line.strip()
    )
    if first_instruction != f"FROM {release['base_image']}":
        raise ValueError("Dockerfile does not pin the captured base image digest")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", release["release_id"]):
        raise ValueError("Release ID is not safe for an image tag")

    if args.image:
        verify_image(args.image, expected, release)

    print(
        json.dumps(
            {
                "release_id": release["release_id"],
                "effective_source_sha256": calculated,
                "files_verified": len(expected),
                "image_verified": bool(args.image),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

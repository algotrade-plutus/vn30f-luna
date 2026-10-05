#!/usr/bin/env python3
"""Freeze the recovered EC2 strategy plus reviewed observability/host files."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Iterable


ALGOTRADE_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = ALGOTRADE_ROOT / "runtime-baseline"
OBSERVABILITY_FILES = (
    "algotrade_adapter/runtime_observability.py",
    "scripts/container_entrypoint.py",
    "scripts/verify_flat_account.py",
    "dashboard/server.py",
    "dashboard/static/index.html",
)
STRATEGY_OVERRIDES = (
    "algotrade_adapter/safe_alpha.py",
    "alphas/master_unified/service.py",
    "alphas/master_unified/genesis_engine.py",
    "alphas/master_unified/schedule.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_map(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, value in sorted(files.items()):
        digest.update(path.encode() + b"\0" + value.encode() + b"\n")
    return digest.hexdigest()


def regular_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            yield path


def main() -> int:
    captured = json.loads(
        (BASELINE_ROOT / "production-source/source-manifest.json").read_text()
    )
    override_root = BASELINE_ROOT / "observable-overrides"
    for relative in OBSERVABILITY_FILES:
        source = ALGOTRADE_ROOT / relative
        destination = override_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    merged_root = BASELINE_ROOT / "observable-source/app"
    if merged_root.exists():
        shutil.rmtree(merged_root)
    shutil.copytree(
        BASELINE_ROOT / "production-source/app",
        merged_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for source in regular_files(override_root):
        relative = source.relative_to(override_root)
        destination = merged_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    source_files = {
        path: str(item["sha256"])
        for path, item in captured["files"].items()
    }
    source_files.update({
        path: str(item["sha256"])
        for path, item in captured.get("dashboard_files", {}).items()
    })
    for path in regular_files(override_root):
        source_files[path.relative_to(override_root).as_posix()] = sha256(path)
    effective_source = digest_map(source_files)

    host_root = ALGOTRADE_ROOT / "deploy"
    host_files = {
        path.relative_to(ALGOTRADE_ROOT).as_posix(): (
            f"{path.stat().st_mode & 0o777:04o}:{sha256(path)}"
        )
        for path in regular_files(host_root)
    }
    host_digest = digest_map(host_files)
    combined = hashlib.sha256(
        f"{effective_source}\0{host_digest}\n".encode()
    ).hexdigest()
    release_id = f"ec2-baseline-observable-20260924-{combined[:12]}"
    overrides = (*STRATEGY_OVERRIDES, *OBSERVABILITY_FILES)
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "source_kind": "recovered_ec2_effective_runtime_plus_observability",
        "git_commit": None,
        "effective_source_sha256": effective_source,
        "host_bundle_sha256": host_digest,
        "host_bundle_files": host_files,
        "base_image": captured["image"],
        "platform": "linux/amd64",
        "source_files": source_files,
        "overrides": {path: source_files[path] for path in overrides},
        "behavior_policy": "preserve_ec2_strategy_add_read_only_observability",
    }
    (BASELINE_ROOT / "observable-release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    dockerfile_path = BASELINE_ROOT / "Dockerfile.observable"
    dockerfile = dockerfile_path.read_text()
    dockerfile = re.sub(
        r'org\.opencontainers\.image\.version="[^"]+"',
        f'org.opencontainers.image.version="{release_id}"',
        dockerfile,
    )
    dockerfile = re.sub(
        r'io\.algotrade\.source-sha256="[0-9a-f]+"',
        f'io.algotrade.source-sha256="{effective_source}"',
        dockerfile,
    )
    dockerfile_path.write_text(dockerfile)
    print(json.dumps({
        "release_id": release_id,
        "effective_source_sha256": effective_source,
        "host_bundle_sha256": host_digest,
        "source_files": len(source_files),
        "host_files": len(host_files),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Reconstruct the effective EC2 source without reading runtime secrets."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_OVERRIDES = {
    "/var/lib/algotrade/safe_alpha.py": "algotrade_adapter/safe_alpha.py",
    "/var/lib/algotrade/service.py": "alphas/master_unified/service.py",
    "/var/lib/algotrade/genesis_engine.py": "alphas/master_unified/genesis_engine.py",
    "/var/lib/algotrade/schedule.py": "alphas/master_unified/schedule.py",
}

DASHBOARD_OVERRIDE = "/var/lib/algotrade/dashboard-static/index.html"

HOST_ARTIFACT_PREFIXES = (
    "/usr/local/bin/algotrade-",
    "/usr/local/bin/auto_reentry_watchdog.py",
    "/etc/systemd/system/algotrade-",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run(*args: str, timeout: int = 60) -> str:
    result = subprocess.run(
        args,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def aws(*args: str, timeout: int = 60) -> str:
    return run("aws", *args, timeout=timeout)


def ssm_command(instance_id: str, region: str, shell_command: str) -> str:
    command_id = aws(
        "ssm", "send-command",
        "--region", region,
        "--instance-ids", instance_id,
        "--document-name", "AWS-RunShellScript",
        "--parameters", json.dumps({"commands": [shell_command]}),
        "--comment", "Read-only PaperTrade source baseline capture",
        "--query", "Command.CommandId",
        "--output", "text",
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = aws(
            "ssm", "get-command-invocation",
            "--region", region,
            "--command-id", command_id,
            "--instance-id", instance_id,
            "--query", "Status",
            "--output", "text",
        )
        if status == "Success":
            return aws(
                "ssm", "get-command-invocation",
                "--region", region,
                "--command-id", command_id,
                "--instance-id", instance_id,
                "--query", "StandardOutputContent",
                "--output", "text",
            )
        if status in {"Failed", "Cancelled", "TimedOut"}:
            raise RuntimeError(f"SSM source read failed with status {status}")
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for SSM command {command_id}")


def fetch_file(
    *,
    path: str,
    size: int,
    expected_sha256: str,
    instance_id: str,
    region: str,
    chunk_size: int = 10_000,
) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        count = min(chunk_size, size - offset)
        remote = (
            "python3 -c "
            + shlex.quote(
                "import base64,sys;"
                "f=open(sys.argv[1],'rb');"
                "f.seek(int(sys.argv[2]));"
                "sys.stdout.write(base64.b64encode(f.read(int(sys.argv[3]))).decode())"
            )
            + " "
            + shlex.quote(path)
            + f" {offset} {count}"
        )
        encoded = ssm_command(instance_id, region, remote)
        chunks.append(base64.b64decode(encoded, validate=True))
        offset += count
    value = b"".join(chunks)
    if len(value) != size:
        raise ValueError(f"Size mismatch for {path}: expected {size}, got {len(value)}")
    actual = sha256_bytes(value)
    if actual != expected_sha256:
        raise ValueError(f"SHA256 mismatch for {path}: expected {expected_sha256}, got {actual}")
    return value


def assert_no_embedded_secret(path: str, value: bytes) -> None:
    if b"\x00" in value:
        raise ValueError(f"Refusing binary baseline artifact: {path}")
    text = value.decode("utf-8")
    forbidden = {
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
        "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "credential_url": re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
    }
    for label, pattern in forbidden.items():
        if pattern.search(text):
            raise ValueError(f"Refusing {path}: detected possible {label}")


def image_from_inventory(inventory: dict[str, Any]) -> str:
    trading = next(
        item for item in inventory["containers"] if item.get("name") == "algotrade-paper"
    )
    digests = trading.get("repo_digests") or []
    if not digests:
        raise ValueError("Trading image has no immutable repo digest")
    return str(digests[0])


def copy_image_source(
    image: str,
    source_manifest: list[dict[str, Any]],
    destination: Path,
) -> dict[str, dict[str, Any]]:
    container_name = f"algotrade-source-capture-{uuid.uuid4().hex[:12]}"
    container_id = run(
        "docker", "create", "--platform", "linux/amd64",
        "--name", container_name,
        "--entrypoint", "/bin/true",
        image,
    )
    records: dict[str, dict[str, Any]] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="algotrade-image-") as tmp:
            root = Path(tmp) / "app"
            root.mkdir()
            run("docker", "cp", f"{container_id}:/app/.", str(root), timeout=120)
            for item in source_manifest:
                relative = str(item["path"])
                source = root / relative
                if not source.is_file():
                    raise FileNotFoundError(f"Image source missing: {relative}")
                value = source.read_bytes()
                assert_no_embedded_secret(relative, value)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
                records[relative] = {
                    "origin": "image",
                    "source": image,
                    "sha256": sha256_bytes(value),
                    "size": len(value),
                }
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "runtime-baseline/baseline-inventory.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "runtime-baseline/production-source",
    )
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing snapshot: {args.output}")
    inventory = json.loads(args.inventory.read_text())
    capture = inventory["capture"]
    instance_id = str(capture["instance_id"])
    region = str(capture["region"])
    image = image_from_inventory(inventory)

    with tempfile.TemporaryDirectory(
        prefix="production-source-staging-", dir=str(args.output.parent)
    ) as staging_name:
        staging = Path(staging_name)
        source_root = staging / "app"
        dashboard_root = staging / "dashboard-app"
        host_root = staging / "host"
        records = copy_image_source(image, inventory["source_manifest"], source_root)
        dashboard_records: dict[str, dict[str, Any]] = {}

        host_override_meta = {
            str(item["path"]): item
            for item in inventory.get("host_overrides", [])
            if item.get("exists")
        }
        dashboard_mount = next(
            (
                mount
                for container in inventory.get("containers", [])
                if container.get("name") == "algotrade-dashboard"
                for mount in container.get("mounts", [])
                if mount.get("source") == "/var/lib/algotrade/dashboard-static/index.html"
            ),
            None,
        )
        if dashboard_mount:
            dashboard_path = DASHBOARD_OVERRIDE
            size_raw = ssm_command(instance_id, region, f"stat -c %s {shlex.quote(dashboard_path)}")
            sha_raw = ssm_command(instance_id, region, f"sha256sum {shlex.quote(dashboard_path)} | cut -d' ' -f1")
            host_override_meta[dashboard_path] = {
                "path": dashboard_path,
                "size": int(size_raw),
                "sha256": sha_raw,
            }

        for host_path, relative in SOURCE_OVERRIDES.items():
            meta = host_override_meta.get(host_path)
            if not meta:
                continue
            value = fetch_file(
                path=host_path,
                size=int(meta["size"]),
                expected_sha256=str(meta["sha256"]),
                instance_id=instance_id,
                region=region,
            )
            assert_no_embedded_secret(host_path, value)
            target = source_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            records[relative] = {
                "origin": "host_override",
                "source": host_path,
                "sha256": sha256_bytes(value),
                "size": len(value),
            }

        dashboard_meta = host_override_meta.get(DASHBOARD_OVERRIDE)
        if dashboard_meta:
            value = fetch_file(
                path=DASHBOARD_OVERRIDE,
                size=int(dashboard_meta["size"]),
                expected_sha256=str(dashboard_meta["sha256"]),
                instance_id=instance_id,
                region=region,
            )
            assert_no_embedded_secret(DASHBOARD_OVERRIDE, value)
            relative = "dashboard/static/index.html"
            target = dashboard_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            dashboard_records[relative] = {
                "origin": "host_override",
                "source": DASHBOARD_OVERRIDE,
                "sha256": sha256_bytes(value),
                "size": len(value),
            }

        for meta in inventory.get("host_files", []):
            host_path = str(meta.get("path", ""))
            if not meta.get("exists") or not host_path.startswith(HOST_ARTIFACT_PREFIXES):
                continue
            value = fetch_file(
                path=host_path,
                size=int(meta["size"]),
                expected_sha256=str(meta["sha256"]),
                instance_id=instance_id,
                region=region,
            )
            assert_no_embedded_secret(host_path, value)
            target = host_root / host_path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)

        effective = {item["path"]: item["sha256"] for item in inventory["source_manifest"]}
        mismatches = {
            path: {"expected": expected, "actual": records.get(path, {}).get("sha256")}
            for path, expected in effective.items()
            if records.get(path, {}).get("sha256") != expected
        }
        if mismatches:
            raise ValueError(f"Effective source verification failed: {mismatches}")

        manifest = {
            "schema_version": 1,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "inventory": str(args.inventory),
            "image": image,
            "files": dict(sorted(records.items())),
            "dashboard_files": dict(sorted(dashboard_records.items())),
            "verified_against_effective_runtime": True,
        }
        (staging / "source-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        staging.rename(args.output)

    print(f"Wrote verified effective source snapshot to {args.output}")
    print(f"Captured {len(records)} application files")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        FileExistsError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        TimeoutError,
        ValueError,
    ) as exc:
        print(f"effective source capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Capture a sanitized, read-only inventory of the PaperTrade EC2 runtime."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REMOTE_SCRIPT = r'''python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def command(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            args, text=True, stderr=subprocess.DEVNULL, timeout=20
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def json_command(*args: str, default: object) -> object:
    raw = command(*args)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def sha256(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def file_meta(path: str) -> dict[str, object]:
    item = Path(path)
    try:
        stat = item.stat()
    except OSError:
        return {"path": path, "exists": False}
    return {
        "path": path,
        "exists": True,
        "size": stat.st_size,
        "mode": oct(stat.st_mode & 0o777),
        "sha256": sha256(path) if item.is_file() else None,
    }


def redact_name(value: str) -> str:
    return re.sub(r"(?<![A-Za-z])\d{6,}(?![A-Za-z])", "<redacted-number>", value)


def list_tree(root: str, max_depth: int = 2) -> list[dict[str, object]]:
    base = Path(root)
    if not base.exists():
        return []
    output = []
    for item in sorted(base.rglob("*")):
        try:
            relative = item.relative_to(base)
            if len(relative.parts) > max_depth:
                continue
            stat = item.stat()
        except OSError:
            continue
        output.append({
            "path": redact_name(str(relative)),
            "kind": "dir" if item.is_dir() else "file",
            "size": stat.st_size if item.is_file() else None,
            "mode": oct(stat.st_mode & 0o777),
        })
    return output


def read_json(path: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def selected_health() -> dict[str, object]:
    health = read_json("/var/lib/algotrade/runtime/health.json")
    keys = (
        "status", "healthy", "mode", "alpha", "symbol", "index_symbol",
        "spot_source", "order_gate", "configured_qty", "desired_qty",
        "positions", "reasons", "fix_logged_on", "worker_alive",
        "feed_age_s", "spot_feed_age_s", "portfolio_age_s", "basis_ready",
        "basis_stale", "last_error", "uptime_s", "next_decision_at",
        "next_signal_day", "next_calendar_target_qty", "next_reasons",
    )
    return {key: health.get(key) for key in keys}


def service_view(name: str) -> dict[str, object]:
    raw = command(
        "systemctl", "show", name,
        "--property=ActiveState,SubState,UnitFileState,NRestarts,ExecMainStartTimestamp,FragmentPath,DropInPaths,ExecStart",
        "--no-pager",
    )
    values: dict[str, object] = {"name": name}
    if raw is None:
        values["available"] = False
        return values
    values["available"] = True
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value
    fragment = str(values.get("FragmentPath", ""))
    values["fragment"] = file_meta(fragment) if fragment else None
    return values


def container_view(name: str) -> dict[str, object]:
    configured_image = command("docker", "inspect", "--format", "{{.Config.Image}}", name)
    image_id = command("docker", "inspect", "--format", "{{.Image}}", name)
    mounts = json_command(
        "docker", "inspect", "--format", "{{json .Mounts}}", name, default=[]
    )
    labels = json_command(
        "docker", "inspect", "--format", "{{json .Config.Labels}}", name, default={}
    )
    return {
        "name": name,
        "configured_image": configured_image,
        "image_id": image_id,
        "repo_digests": (
            json_command(
                "docker", "image", "inspect", "--format", "{{json .RepoDigests}}",
                image_id, default=[],
            )
            if image_id
            else []
        ),
        "labels": {
            key: labels.get(key)
            for key in (
                "org.opencontainers.image.created",
                "org.opencontainers.image.revision",
                "org.opencontainers.image.source",
                "org.opencontainers.image.version",
            )
        } if isinstance(labels, dict) else {},
        "state": command(
            "docker", "inspect", "--format",
            "{{.State.Status}} / {{if .State.Health}}{{.State.Health.Status}}{{end}}",
            name,
        ),
        "started_at": command("docker", "inspect", "--format", "{{.State.StartedAt}}", name),
        "restart_count": command("docker", "inspect", "--format", "{{.RestartCount}}", name),
        "mounts": [
            {
                "type": item.get("Type"),
                "source": item.get("Source"),
                "destination": item.get("Destination"),
                "rw": item.get("RW"),
            }
            for item in mounts
            if isinstance(item, dict)
        ] if isinstance(mounts, list) else [],
        "ports": json_command(
            "docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}",
            name, default={},
        ),
    }


def source_manifest() -> list[dict[str, object]]:
    raw = command(
        "docker", "exec", "algotrade-paper", "python", "-c",
        """import hashlib,json,pathlib
roots=[pathlib.Path('/app/algotrade_adapter'),pathlib.Path('/app/alphas'),pathlib.Path('/app/luna_core'),pathlib.Path('/app/scripts'),pathlib.Path('/app/dashboard')]
out=[]
for root in roots:
    if not root.exists(): continue
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.suffix in {'.py','.html','.js','.css'}:
            b=p.read_bytes(); out.append({'path':str(p.relative_to('/app')),'size':len(b),'sha256':hashlib.sha256(b).hexdigest()})
print(json.dumps(out,separators=(',',':')))""",
    )
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


known_host_files = [
    "/usr/local/bin/algotrade-run",
    "/usr/local/bin/algotrade-run-genesis-pg",
    "/usr/local/bin/algotrade-render-env",
    "/etc/systemd/system/algotrade-paper.service",
    "/etc/systemd/system/algotrade-dashboard.service",
    "/etc/systemd/system/algotrade-reentry-watchdog.service",
    "/etc/systemd/system/algotrade-reentry-watchdog.timer",
    "/usr/local/bin/algotrade-reentry-watchdog",
    "/usr/local/bin/auto_reentry_watchdog.py",
]

unit_files = command("systemctl", "list-unit-files", "--no-legend", "--no-pager") or ""
related_units = sorted({
    line.split()[0]
    for line in unit_files.splitlines()
    if line and any(word in line.lower() for word in ("algotrade", "reentry", "watchdog"))
})

inventory = {
    "schema_version": 1,
    "host": {
        "hostname": command("hostname"),
        "kernel": command("uname", "-srmo"),
        "os_release": {
            line.split("=", 1)[0]: line.split("=", 1)[1].strip().strip('"')
            for line in (Path("/etc/os-release").read_text().splitlines() if Path("/etc/os-release").exists() else [])
            if "=" in line and line.split("=", 1)[0] in {"NAME", "VERSION_ID", "PLATFORM_ID"}
        },
        "docker_version": command("docker", "version", "--format", "{{.Server.Version}}"),
        "architecture": command("uname", "-m"),
        "disk": command("df", "-P", "/opt/algotrade", "/var/lib/algotrade", "/var/log/algotrade"),
    },
    "services": [
        service_view("algotrade-paper"),
        service_view("algotrade-dashboard"),
        service_view("algotrade-reentry-watchdog"),
    ],
    "related_units": related_units,
    "containers": [container_view("algotrade-paper"), container_view("algotrade-dashboard")],
    "health": selected_health(),
    "source_manifest": source_manifest(),
    "host_files": [file_meta(path) for path in known_host_files],
    "host_overrides": [
        file_meta(path)
        for path in (
            "/var/lib/algotrade/safe_alpha.py",
            "/var/lib/algotrade/service.py",
            "/var/lib/algotrade/genesis_engine.py",
            "/var/lib/algotrade/schedule.py",
        )
    ],
    "trees": {
        "opt_algotrade": list_tree("/opt/algotrade", max_depth=2),
        "var_lib_algotrade": list_tree("/var/lib/algotrade", max_depth=2),
        "cron_names": list_tree("/etc/cron.d", max_depth=1),
    },
    "git": {
        "work_tree": command("git", "-C", "/opt/algotrade", "rev-parse", "--show-toplevel"),
        "commit": command("git", "-C", "/opt/algotrade", "rev-parse", "HEAD"),
    },
}

print(json.dumps(inventory, ensure_ascii=False, separators=(",", ":")))
PY'''


def aws(*args: str, timeout: int = 45) -> str:
    result = subprocess.run(
        ["aws", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return result.stdout.strip()


def capture(instance_id: str, region: str) -> dict[str, Any]:
    parameters = json.dumps({"commands": [REMOTE_SCRIPT]})
    command_id = aws(
        "ssm", "send-command",
        "--region", region,
        "--instance-ids", instance_id,
        "--document-name", "AWS-RunShellScript",
        "--parameters", parameters,
        "--comment", "Read-only sanitized PaperTrade baseline inventory",
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
            payload = aws(
                "ssm", "get-command-invocation",
                "--region", region,
                "--command-id", command_id,
                "--instance-id", instance_id,
                "--query", "StandardOutputContent",
                "--output", "text",
            )
            inventory = json.loads(payload)
            inventory["capture"] = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "instance_id": instance_id,
                "region": region,
                "ssm_command_id": command_id,
            }
            return inventory
        if status in {"Failed", "Cancelled", "TimedOut"}:
            error = aws(
                "ssm", "get-command-invocation",
                "--region", region,
                "--command-id", command_id,
                "--instance-id", instance_id,
                "--query", "StandardErrorContent",
                "--output", "text",
            )
            raise RuntimeError(f"SSM inventory failed with {status}: {error}")
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for SSM command {command_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", default="i-04ccc8700d99ec425")
    parser.add_argument("--region", default="ap-southeast-1")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "runtime-baseline" / "baseline-inventory.json",
    )
    args = parser.parse_args()

    inventory = capture(args.instance_id, args.region)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    print(f"Wrote sanitized inventory to {args.output}")
    print(f"Captured {len(inventory.get('source_manifest', []))} source files")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"baseline capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)

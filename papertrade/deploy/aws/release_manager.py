#!/usr/bin/env python3
"""Install or roll back an immutable PaperTrade release on one EC2 host.

The controller never enables order submission. Every switch writes a release
descriptor with ``ALGOTRADE_FORCE_HOLD=true`` and verifies a fresh HOLD
heartbeat from the selected release before reporting success.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


PUBLIC_RELEASE_FIELDS = (
    "schema_version",
    "release_id",
    "source_kind",
    "git_commit",
    "effective_source_sha256",
    "platform",
    "behavior_policy",
    "host_bundle_sha256",
)
TERMINAL_ORDER_STATES = {
    "2", "4", "8", "C", "FILLED", "CANCELED", "CANCELLED",
    "REJECTED", "EXPIRED", "DONEFORDAY", "DONE_FOR_DAY",
}
IMAGE_DIGEST_RE = re.compile(r"^[^\s]+@sha256:[0-9a-f]{64}$")
RELEASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class Paths:
    def __init__(self, root: Path = Path("/")) -> None:
        self.root = root
        self.install = root / "opt/algotrade"
        self.releases = self.install / "releases"
        self.current = self.install / "current"
        self.config = root / "etc/algotrade"
        self.release_env = self.config / "release.env"
        self.runtime = root / "var/lib/algotrade/runtime"
        self.safety = self.runtime / "safety.json"
        self.state = root / "var/lib/algotrade/state"
        self.ops = root / "var/lib/algotrade/ops"
        self.backups = root / "var/lib/algotrade/backups"
        self.journal = self.ops / "deploy-journal.jsonl"
        self.lock = self.ops / "deploy.lock"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def public_release(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value.get(key) for key in PUBLIC_RELEASE_FIELDS}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def host_bundle_files(bundle: Path) -> dict[str, str]:
    deploy = bundle / "deploy"
    if not deploy.is_dir():
        raise ValueError(f"Release bundle has no deploy directory: {bundle}")
    result = {}
    for path in sorted(deploy.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(bundle).as_posix()
        mode = path.stat().st_mode & 0o777
        result[relative] = f"{mode:04o}:{sha256(path)}"
    if not result:
        raise ValueError("Release host bundle is empty")
    return result


def host_bundle_digest(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, value in sorted(files.items()):
        digest.update(path.encode() + b"\0" + value.encode() + b"\n")
    return digest.hexdigest()


def verify_host_bundle(bundle: Path, manifest: dict[str, Any]) -> None:
    expected = manifest.get("host_bundle_files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Release manifest has no host bundle file map")
    observed = host_bundle_files(bundle)
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        changed = sorted(
            path for path in set(expected) & set(observed)
            if expected[path] != observed[path]
        )
        raise ValueError(
            f"Host bundle mismatch: missing={missing}, unexpected={unexpected}, changed={changed}"
        )
    calculated = host_bundle_digest(observed)
    if calculated != manifest.get("host_bundle_sha256"):
        raise ValueError("Host bundle digest differs from release manifest")


def validate_release(manifest: dict[str, Any], image_ref: str) -> None:
    release_id = manifest.get("release_id")
    if not isinstance(release_id, str) or not RELEASE_ID_RE.fullmatch(release_id):
        raise ValueError("Release ID is missing or unsafe")
    if manifest.get("platform") != "linux/amd64":
        raise ValueError("Release platform must be linux/amd64")
    digest = manifest.get("effective_source_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Release source digest is missing or invalid")
    if not IMAGE_DIGEST_RE.fullmatch(image_ref):
        raise ValueError("Image must be an immutable repository@sha256 reference")
    bundle_digest = manifest.get("host_bundle_sha256")
    if not isinstance(bundle_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", bundle_digest):
        raise ValueError("Release host bundle digest is missing or invalid")


def parse_release_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            result[key] = value
    return result


def working_order_count(account: dict[str, Any]) -> int | None:
    orders = account.get("orders")
    if not isinstance(orders, list):
        return None
    count = 0
    for order in orders:
        if not isinstance(order, dict):
            return None
        status = str(order.get("status", "")).upper().replace(" ", "")
        terminal = status in TERMINAL_ORDER_STATES or status.endswith((
            "FULLYFILLED", "CANCELED", "CANCELLED", "REJECTED",
            "EXPIRED", "DONEFORDAY", "CANCELEDSUCCESSFULLY",
            "CANCELLEDSUCCESSFULLY",
        ))
        if not status or not terminal:
            count += 1
    return count


def positions_are_flat(account: dict[str, Any]) -> bool | None:
    positions = account.get("positions")
    if not isinstance(positions, list):
        return None
    if any(not isinstance(item, dict) or "quantity" not in item for item in positions):
        return None
    try:
        return all(float(item["quantity"]) == 0 for item in positions)
    except (TypeError, ValueError):
        return None


def preflight(paths: Paths) -> dict[str, Any]:
    health = read_json(paths.runtime / "health.json")
    account = read_json(paths.runtime / "account.json")
    env = parse_release_env(paths.release_env)
    account_updated_at = account.get("updated_at")
    try:
        account_age_s = max(0.0, time.time() - float(account_updated_at))
    except (TypeError, ValueError):
        account_age_s = None
    health_updated_at = health.get("updated_at")
    try:
        health_age_s = max(0.0, time.time() - float(health_updated_at))
    except (TypeError, ValueError):
        health_age_s = None
    return {
        "current_release_id": env.get("ALGOTRADE_RELEASE_ID"),
        "current_image_ref": env.get("ALGOTRADE_IMAGE_REF"),
        "health_status": health.get("status"),
        "health_updated_at": health_updated_at,
        "health_age_s": health_age_s,
        "mode": health.get("mode"),
        "order_gate": health.get("order_gate"),
        "account_updated_at": account_updated_at,
        "account_age_s": account_age_s,
        "account_status": account.get("status"),
        "flat": positions_are_flat(account),
        "working_orders": working_order_count(account),
    }


def assert_runtime_ready(preflight_result: dict[str, Any]) -> None:
    health_age = preflight_result.get("health_age_s")
    if not isinstance(health_age, (int, float)) or health_age > 45:
        raise RuntimeError("Deploy requires a runtime heartbeat no older than 45 seconds")
    if preflight_result.get("health_status") not in {"healthy", "running"}:
        raise RuntimeError("Deploy requires a healthy/running source runtime")
    if (
        preflight_result.get("mode") == "hold"
        and preflight_result.get("order_gate") not in (False, "false")
    ):
        raise RuntimeError("HOLD runtime must have its order gate closed")


def assert_account_quiet(preflight_result: dict[str, Any]) -> None:
    age = preflight_result.get("account_age_s")
    if not isinstance(age, (int, float)) or age > 120:
        raise RuntimeError("Deploy requires an account snapshot no older than 120 seconds")
    if preflight_result.get("account_status") not in (None, "healthy"):
        raise RuntimeError("Deploy requires a complete healthy account snapshot")
    if preflight_result.get("flat") is not True:
        raise RuntimeError("Deploy requires a verified flat account snapshot")
    if preflight_result.get("working_orders") != 0:
        raise RuntimeError("Deploy requires exactly zero verified working orders")


def assert_quiet(preflight_result: dict[str, Any]) -> None:
    assert_runtime_ready(preflight_result)
    assert_account_quiet(preflight_result)


def atomic_write(path: Path, content: str, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    temporary.replace(path)


def append_journal(paths: Paths, operation_id: str, state: str, **details: Any) -> None:
    paths.ops.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "operation_id": operation_id,
        "timestamp": time.time(),
        "state": state,
        **details,
    }
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with paths.journal.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def write_safety_verification(
    paths: Paths,
    broker: dict[str, Any],
    *,
    operation_id: str,
    phase: str,
    release_id: str,
) -> None:
    """Persist only the sanitized result of an on-demand REST safety probe."""
    atomic_write(
        paths.safety,
        json.dumps({
            "schema_version": 1,
            "updated_at": time.time(),
            "status": "verified",
            "source": "broker_rest",
            "flat": broker.get("flat") is True,
            "nonflat_positions": int(broker.get("nonflat_positions", 0)),
            "working_orders": int(broker.get("working_orders", 0)),
            "order_gate": False,
            "operation_id": operation_id,
            "phase": phase,
            "release_id": release_id,
        }, ensure_ascii=False, sort_keys=True) + "\n",
    )


@contextmanager
def deploy_lock(paths: Paths) -> Iterator[None]:
    paths.ops.mkdir(parents=True, exist_ok=True)
    with paths.lock.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another deploy operation holds the host lock") from exc
        yield


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def image_release(image_ref: str) -> dict[str, Any]:
    raw = run(
        "docker", "run", "--rm", "--platform", "linux/amd64",
        "--entrypoint", "cat", image_ref, "/app/release.json", capture=True,
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Image release manifest is not an object")
    return value


def verify_broker_flat(image_ref: str) -> dict[str, Any]:
    raw = run(
        "docker", "run", "--rm", "--platform", "linux/amd64",
        "--env-file", "/run/algotrade/paperbroker.env",
        "--env", "PAPERBROKER_ALLOW_ORDERS=false",
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
        "--workdir", "/tmp", "--entrypoint", "python", image_ref,
        "/app/scripts/verify_flat_account.py",
        capture=True,
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("REST safety probe returned invalid JSON")
    if (
        value.get("status") != "verified"
        or value.get("flat") is not True
        or value.get("working_orders") != 0
        or value.get("order_gate") is not False
    ):
        raise RuntimeError("REST safety probe did not verify flat/no-working-orders")
    return value


def release_env(release_id: str, image_ref: str) -> str:
    return "\n".join((
        f"ALGOTRADE_RELEASE_ID={release_id}",
        f"ALGOTRADE_IMAGE_REF={image_ref}",
        "ALGOTRADE_FORCE_HOLD=true",
        "ALGOTRADE_INSTALL_DIR=/opt/algotrade/current",
        "",
    ))


def stage_release(paths: Paths, bundle: Path, manifest_path: Path, image_ref: str) -> Path:
    manifest = read_json(manifest_path)
    verify_host_bundle(bundle, manifest)
    release_id = str(manifest["release_id"])
    target = paths.releases / release_id
    if target.exists():
        existing = read_json(target / "release.json")
        if public_release(existing) != public_release(manifest):
            raise RuntimeError(f"Existing release directory differs: {target}")
        existing_env = parse_release_env(target / "release.env")
        if existing_env.get("ALGOTRADE_IMAGE_REF") != image_ref:
            raise RuntimeError(f"Existing release image differs: {target}")
        return target
    temporary = paths.releases / f".{release_id}.{uuid.uuid4().hex}.tmp"
    temporary.mkdir(parents=True)
    shutil.copytree(bundle / "deploy", temporary / "deploy")
    shutil.copy2(manifest_path, temporary / "release.json")
    atomic_write(temporary / "release.env", release_env(release_id, image_ref))
    temporary.replace(target)
    return target


def switch_current(paths: Paths, target: Path) -> None:
    paths.install.mkdir(parents=True, exist_ok=True)
    if paths.current.exists() and not paths.current.is_symlink():
        raise RuntimeError(f"Current release pointer is not a symlink: {paths.current}")
    temporary = paths.install / f".current.{uuid.uuid4().hex}"
    temporary.symlink_to(target)
    temporary.replace(paths.current)


def install_units(paths: Paths, target: Path) -> None:
    systemd_dir = paths.root / "etc/systemd/system"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
        dropins = systemd_dir / f"{name}.d"
        if dropins.exists() and not dropins.is_dir():
            raise RuntimeError(f"Unexpected systemd drop-in path: {dropins}")
        if dropins.is_dir():
            shutil.rmtree(dropins)
        shutil.copy2(target / "deploy/aws" / name, systemd_dir / name)
    run("systemctl", "daemon-reload")


def backup_state(paths: Paths, operation_id: str) -> Path:
    paths.backups.mkdir(parents=True, exist_ok=True)
    destination = paths.backups / f"{operation_id}.tar.gz"
    with tarfile.open(destination, "w:gz") as archive:
        for source, arcname in ((paths.state, "state"), (paths.runtime, "runtime")):
            if source.exists():
                archive.add(source, arcname=arcname, recursive=True)
    os.chmod(destination, 0o600)
    return destination


def capture_control_state(paths: Paths, operation_id: str) -> Path:
    """Capture host control files needed to recover the pre-migration launcher."""
    paths.backups.mkdir(parents=True, exist_ok=True)
    destination = paths.backups / f"{operation_id}-control"
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    unit_dir = paths.root / "etc/systemd/system"
    units: dict[str, bool] = {}
    dropins: dict[str, bool] = {}
    for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
        source = unit_dir / name
        units[name] = source.is_file()
        if source.is_file():
            shutil.copy2(source, destination / name)
        source_dropins = unit_dir / f"{name}.d"
        if source_dropins.exists() and not source_dropins.is_dir():
            raise RuntimeError(f"Unexpected systemd drop-in path: {source_dropins}")
        dropins[name] = source_dropins.is_dir()
        if source_dropins.is_dir():
            shutil.copytree(source_dropins, destination / f"{name}.d")
    current_target = os.readlink(paths.current) if paths.current.is_symlink() else None
    if paths.current.exists() and not paths.current.is_symlink():
        raise RuntimeError(f"Current release pointer is not a symlink: {paths.current}")
    metadata = {
        "schema_version": 1,
        "units": units,
        "dropins": dropins,
        "current_target": current_target,
        "release_env_exists": paths.release_env.is_file(),
    }
    if paths.release_env.is_file():
        shutil.copy2(paths.release_env, destination / "release.env")
    atomic_write(
        destination / "control-state.json",
        json.dumps(metadata, sort_keys=True) + "\n",
        mode=0o600,
    )
    return destination


def restore_control_state(paths: Paths, snapshot: Path) -> None:
    metadata = read_json(snapshot / "control-state.json")
    units = metadata.get("units") if isinstance(metadata.get("units"), dict) else {}
    dropins = (
        metadata.get("dropins")
        if isinstance(metadata.get("dropins"), dict)
        else {}
    )
    unit_dir = paths.root / "etc/systemd/system"
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
        destination = unit_dir / name
        if units.get(name) is True:
            shutil.copy2(snapshot / name, destination)
        else:
            destination.unlink(missing_ok=True)
        destination_dropins = unit_dir / f"{name}.d"
        if destination_dropins.exists() and not destination_dropins.is_dir():
            raise RuntimeError(
                f"Unexpected systemd drop-in path: {destination_dropins}"
            )
        if destination_dropins.is_dir():
            shutil.rmtree(destination_dropins)
        if dropins.get(name) is True:
            shutil.copytree(
                snapshot / f"{name}.d",
                destination_dropins,
            )

    current_target = metadata.get("current_target")
    if paths.current.is_symlink():
        paths.current.unlink()
    elif paths.current.exists():
        raise RuntimeError(f"Cannot restore over non-symlink current path: {paths.current}")
    if isinstance(current_target, str) and current_target:
        paths.install.mkdir(parents=True, exist_ok=True)
        paths.current.symlink_to(current_target)

    if metadata.get("release_env_exists") is True:
        atomic_write(paths.release_env, (snapshot / "release.env").read_text())
    else:
        paths.release_env.unlink(missing_ok=True)
    run("systemctl", "daemon-reload")


def stop_services() -> None:
    subprocess.run(
        ["systemctl", "disable", "--now", "algotrade-reentry-watchdog.service"],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    run("systemctl", "stop", "algotrade-dashboard.service", "algotrade-paper.service")
    for name in ("algotrade-paper", "algotrade-dashboard"):
        status = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        if status.returncode == 0 and status.stdout.strip() == "true":
            raise RuntimeError(f"Container still running after stop: {name}")


def start_services() -> None:
    run("systemctl", "start", "algotrade-paper.service", "algotrade-dashboard.service")


def wait_for_hold(paths: Paths, release_id: str, timeout: float = 90) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = read_json(paths.runtime / "health.json")
        release = health.get("release") if isinstance(health.get("release"), dict) else {}
        fresh = time.time() - float(health.get("updated_at") or 0) < 45
        gate = health.get("order_gate")
        if (
            fresh
            and health.get("status") == "healthy"
            and health.get("mode") == "hold"
            and gate in (False, "false")
            and release.get("release_id") == release_id
        ):
            return health
        time.sleep(2)
    raise RuntimeError("Timed out waiting for fresh HOLD heartbeat from selected release")


def wait_for_runtime(
    paths: Paths,
    *,
    minimum_updated_at: float,
    timeout: float = 90,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = read_json(paths.runtime / "health.json")
        try:
            updated_at = float(health.get("updated_at") or 0)
        except (TypeError, ValueError):
            updated_at = 0
        if updated_at >= minimum_updated_at and health.get("status") in {
            "healthy", "running",
        }:
            return health
        time.sleep(2)
    raise RuntimeError("Timed out waiting for restored runtime heartbeat")


def recover_previous_control(
    paths: Paths,
    operation_id: str,
    snapshot: Path,
    timeout: float,
) -> None:
    try:
        stop_services()
        restore_control_state(paths, snapshot)
        started_at = time.time()
        start_services()
        wait_for_runtime(paths, minimum_updated_at=started_at - 1, timeout=timeout)
    except BaseException as recovery_error:
        append_journal(
            paths,
            operation_id,
            "NEEDS_OPERATOR",
            recovery_error_type=type(recovery_error).__name__,
        )
        raise RuntimeError("Automatic recovery failed; operator action is required") from recovery_error
    append_journal(paths, operation_id, "ROLLED_BACK")


def command_plan(args: argparse.Namespace, paths: Paths) -> int:
    manifest = read_json(args.manifest)
    validate_release(manifest, args.image_ref)
    result = {
        "action": "install_release_in_hold",
        "desired_release": public_release(manifest),
        "desired_image_ref": args.image_ref,
        "preflight": preflight(paths),
        "mutates_broker": False,
        "enables_orders": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def command_apply(args: argparse.Namespace, paths: Paths) -> int:
    if paths.root == Path("/") and os.geteuid() != 0:
        raise PermissionError("apply must run as root on the EC2 host")
    manifest = read_json(args.manifest)
    validate_release(manifest, args.image_ref)
    release_id = str(manifest["release_id"])
    operation_id = f"deploy-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    with deploy_lock(paths):
        before = preflight(paths)
        append_journal(paths, operation_id, "PREPARING", desired_release=release_id, before=before)
        control_snapshot = capture_control_state(paths, operation_id)
        mutation_started = False
        try:
            assert_runtime_ready(before)
            run("docker", "pull", args.image_ref)
            embedded = image_release(args.image_ref)
            if public_release(embedded) != public_release(manifest):
                raise RuntimeError("Image release identity differs from reviewed manifest")
            target = stage_release(paths, args.bundle, args.manifest, args.image_ref)
            ready = preflight(paths)
            assert_runtime_ready(ready)
            if ready.get("mode") == "hold":
                broker_preflight = verify_broker_flat(args.image_ref)
                write_safety_verification(
                    paths,
                    broker_preflight,
                    operation_id=operation_id,
                    phase="preflight",
                    release_id=release_id,
                )
                append_journal(
                    paths,
                    operation_id,
                    "BROKER_PREFLIGHT_VERIFIED",
                    flat=broker_preflight["flat"],
                    working_orders=broker_preflight["working_orders"],
                )
            else:
                assert_account_quiet(ready)
            append_journal(paths, operation_id, "QUIESCING")
            mutation_started = True
            stop_services()
            append_journal(paths, operation_id, "STOPPED")
            broker = verify_broker_flat(args.image_ref)
            write_safety_verification(
                paths,
                broker,
                operation_id=operation_id,
                phase="stopped",
                release_id=release_id,
            )
            append_journal(
                paths,
                operation_id,
                "BROKER_VERIFIED",
                flat=broker["flat"],
                working_orders=broker["working_orders"],
            )
            backup = backup_state(paths, operation_id)
            switch_current(paths, target)
            atomic_write(paths.release_env, release_env(release_id, args.image_ref))
            install_units(paths, target)
            append_journal(paths, operation_id, "SWITCHED", backup=str(backup))
            start_services()
            append_journal(paths, operation_id, "VERIFYING")
            health = wait_for_hold(paths, release_id, args.timeout)
        except BaseException as exc:
            append_journal(paths, operation_id, "FAILED", error_type=type(exc).__name__)
            if mutation_started:
                recover_previous_control(
                    paths, operation_id, control_snapshot, args.timeout
                )
            raise
        append_journal(paths, operation_id, "INSTALLED_VERIFIED", release_id=release_id)
    print(json.dumps({
        "operation_id": operation_id,
        "state": "INSTALLED_VERIFIED",
        "release_id": release_id,
        "mode": health.get("mode"),
        "order_gate": health.get("order_gate"),
    }, sort_keys=True))
    return 0


def command_rollback(args: argparse.Namespace, paths: Paths) -> int:
    if paths.root == Path("/") and os.geteuid() != 0:
        raise PermissionError("rollback must run as root on the EC2 host")
    target = paths.releases / args.release_id
    manifest = read_json(target / "release.json")
    env = parse_release_env(target / "release.env")
    image_ref = env.get("ALGOTRADE_IMAGE_REF", "")
    validate_release(manifest, image_ref)
    operation_id = f"rollback-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    with deploy_lock(paths):
        before = preflight(paths)
        append_journal(paths, operation_id, "QUIESCING", desired_release=args.release_id, before=before)
        control_snapshot = capture_control_state(paths, operation_id)
        mutation_started = False
        try:
            assert_runtime_ready(before)
            if before.get("mode") == "hold":
                broker_preflight = verify_broker_flat(image_ref)
                write_safety_verification(
                    paths,
                    broker_preflight,
                    operation_id=operation_id,
                    phase="preflight",
                    release_id=args.release_id,
                )
                append_journal(
                    paths,
                    operation_id,
                    "BROKER_PREFLIGHT_VERIFIED",
                    flat=broker_preflight["flat"],
                    working_orders=broker_preflight["working_orders"],
                )
            else:
                assert_account_quiet(before)
            mutation_started = True
            stop_services()
            append_journal(paths, operation_id, "STOPPED")
            broker = verify_broker_flat(image_ref)
            write_safety_verification(
                paths,
                broker,
                operation_id=operation_id,
                phase="stopped",
                release_id=args.release_id,
            )
            append_journal(
                paths,
                operation_id,
                "BROKER_VERIFIED",
                flat=broker["flat"],
                working_orders=broker["working_orders"],
            )
            backup_state(paths, operation_id)
            switch_current(paths, target)
            atomic_write(paths.release_env, release_env(args.release_id, image_ref))
            install_units(paths, target)
            append_journal(paths, operation_id, "SWITCHED")
            start_services()
            append_journal(paths, operation_id, "VERIFYING")
            health = wait_for_hold(paths, args.release_id, args.timeout)
        except BaseException as exc:
            append_journal(paths, operation_id, "FAILED", error_type=type(exc).__name__)
            if mutation_started:
                recover_previous_control(
                    paths, operation_id, control_snapshot, args.timeout
                )
            raise
        append_journal(paths, operation_id, "INSTALLED_VERIFIED")
    print(json.dumps({
        "operation_id": operation_id,
        "state": "INSTALLED_VERIFIED",
        "release_id": args.release_id,
        "mode": health.get("mode"),
        "order_gate": health.get("order_gate"),
    }, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/"), help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--image-ref", required=True)
    plan.set_defaults(func=command_plan)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--manifest", type=Path, required=True)
    apply.add_argument("--image-ref", required=True)
    apply.add_argument("--bundle", type=Path, required=True)
    apply.add_argument("--timeout", type=float, default=90)
    apply.set_defaults(func=command_apply)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("release_id")
    rollback.add_argument("--timeout", type=float, default=90)
    rollback.set_defaults(func=command_rollback)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args, Paths(args.root))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"release manager failed: {exc}", file=sys.stderr)
        raise SystemExit(2)

#!/usr/bin/env python3
"""Read-only operator CLI for PaperTrade code identity and runtime state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PAPERTRADE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PAPERTRADE_ROOT.parent
ALGOTRADE_ROOT = PAPERTRADE_ROOT
BASELINE_ROOT = ALGOTRADE_ROOT / "runtime-baseline"
HCM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def live_status() -> dict[str, Any]:
    result = subprocess.run(
        [str(ALGOTRADE_ROOT / "scripts" / "check_live_alpha.sh")],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("Live status response must be a JSON object")
    return value


def recovered_baseline_match(live: dict[str, Any]) -> dict[str, Any]:
    manifest = load_json(BASELINE_ROOT / "production-source" / "source-manifest.json")
    release = load_json(BASELINE_ROOT / "release-manifest.json")
    if not manifest:
        return {"status": "UNKNOWN", "reason": "local baseline manifest missing"}
    code = live.get("code") if isinstance(live.get("code"), dict) else {}
    repo_digests = code.get("repo_digests") if isinstance(code.get("repo_digests"), list) else []
    image_matches = manifest.get("image") in repo_digests

    expected_mounts = {
        str(item["source"]): str(item["sha256"])
        for item in manifest.get("files", {}).values()
        if item.get("origin") == "host_override"
    }
    observed_mounts = {
        str(item.get("source")): item.get("sha256")
        for item in code.get("code_mounts", [])
        if isinstance(item, dict)
    }
    mount_results = {
        path: {
            "expected": digest,
            "observed": observed_mounts.get(path),
            "matches": observed_mounts.get(path) == digest,
        }
        for path, digest in expected_mounts.items()
    }
    unexpected = sorted(set(observed_mounts) - set(expected_mounts))
    mounts_match = bool(expected_mounts) and all(
        item["matches"] for item in mount_results.values()
    ) and not unexpected
    matches = image_matches and mounts_match
    return {
        "status": "RECOVERED_MATCH" if matches else "MISMATCH",
        "image_matches": image_matches,
        "mounts_match": mounts_match,
        "mounts": mount_results,
        "unexpected_code_mounts": unexpected,
        "local_source": str(BASELINE_ROOT / "production-source" / "app"),
        "manifest": str(BASELINE_ROOT / "production-source" / "source-manifest.json"),
        "release": public_release_identity(release),
    }


def public_release_identity(release: dict[str, Any]) -> dict[str, Any]:
    return {
        key: release.get(key)
        for key in (
            "schema_version", "release_id", "source_kind", "git_commit",
            "effective_source_sha256", "platform", "behavior_policy",
            "host_bundle_sha256",
        )
    }


def immutable_release_match(live: dict[str, Any]) -> dict[str, Any] | None:
    code = live.get("code") if isinstance(live.get("code"), dict) else {}
    release = code.get("release_manifest")
    if not isinstance(release, dict) or not release.get("effective_source_sha256"):
        return None
    configured_image = str(code.get("configured_image") or "")
    repo_digests = code.get("repo_digests") if isinstance(code.get("repo_digests"), list) else []
    image_is_pinned = "@sha256:" in configured_image and configured_image in repo_digests
    candidates = (
        (
            BASELINE_ROOT / "release-manifest.json",
            BASELINE_ROOT / "production-source" / "app",
        ),
        (
            BASELINE_ROOT / "observable-release-manifest.json",
            BASELINE_ROOT / "observable-source" / "app",
        ),
    )
    for manifest_path, source_path in candidates:
        local = load_json(manifest_path)
        if (
            release.get("release_id") == local.get("release_id")
            and release.get("effective_source_sha256")
            == local.get("effective_source_sha256")
        ):
            return {
                "status": (
                    "IMMUTABLE_MATCH"
                    if image_is_pinned and not code.get("code_mounts")
                    else "MISMATCH"
                ),
                "image_is_pinned": image_is_pinned,
                "local_source": str(source_path),
                "manifest": str(manifest_path),
                "release": release,
            }
    return {
        "status": "MISMATCH",
        "image_is_pinned": image_is_pinned,
        "local_source": None,
        "release": release,
    }


def enrich(live: dict[str, Any]) -> dict[str, Any]:
    identity = immutable_release_match(live) or recovered_baseline_match(live)
    code = dict(live.get("code")) if isinstance(live.get("code"), dict) else {}
    code["identity_status"] = identity.get("status", "UNKNOWN")
    result = {**live, "code": code, "source_identity": identity}
    account = (
        result.get("account_snapshot")
        if isinstance(result.get("account_snapshot"), dict)
        else {}
    )
    if result.get("mode") == "hold" or account.get("live") is not True:
        result["working_orders"] = None
        result["actual_positions"] = None
    return result


def format_time(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), HCM_TZ)
        else:
            parsed = datetime.fromisoformat(str(value)).astimezone(HCM_TZ)
        return parsed.strftime("%Y-%m-%d %H:%M:%S ICT")
    except (TypeError, ValueError):
        return str(value)


def short_digest(value: Any) -> str:
    text = str(value or "UNKNOWN")
    if "@sha256:" in text:
        prefix, digest = text.rsplit("@sha256:", 1)
        return f"{prefix}@sha256:{digest[:12]}"
    if text.startswith("sha256:"):
        return text[:19]
    return text


def gate_label(value: Any) -> str:
    if value is True or (isinstance(value, str) and value.lower() == "true"):
        return "OPEN"
    if value is False or (isinstance(value, str) and value.lower() == "false"):
        return "CLOSED"
    return "UNKNOWN"


def age_label(value: Any) -> str:
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "UNKNOWN"
    if seconds < 120:
        return f"{seconds}s"
    if seconds < 7_200:
        return f"{seconds // 60}m"
    return f"{seconds // 3_600}h"


def describe_activity(event: dict[str, Any]) -> str:
    event_type = event.get("type")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if event_type == "runtime_snapshot":
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        return (
            f"runtime {state.get('status') or 'UNKNOWN'}; "
            f"target={state.get('desired_qty', 'UNKNOWN')}; "
            f"positions={json.dumps(state.get('positions'), ensure_ascii=False, sort_keys=True)}"
        )
    if event_type == "runtime_transition":
        changed = payload.get("changed") if isinstance(payload.get("changed"), dict) else {}
        parts = []
        for key, transition in changed.items():
            if not isinstance(transition, dict):
                continue
            parts.append(f"{key}: {transition.get('before')} -> {transition.get('after')}")
        return "; ".join(parts) if parts else "runtime state changed"
    return str(event_type or "runtime event")


def format_status(data: dict[str, Any]) -> str:
    code = data.get("code") if isinstance(data.get("code"), dict) else {}
    identity = data.get("source_identity") if isinstance(data.get("source_identity"), dict) else {}
    service = data.get("service") if isinstance(data.get("service"), dict) else {}
    mounts = code.get("code_mounts") if isinstance(code.get("code_mounts"), list) else []
    repo_digests = code.get("repo_digests") if isinstance(code.get("repo_digests"), list) else []
    digest = repo_digests[0] if repo_digests else code.get("container_image_id")
    release = code.get("release_manifest") if isinstance(code.get("release_manifest"), dict) else {}
    if not release and isinstance(identity.get("release"), dict):
        release = identity["release"]
    positions = data.get("actual_positions")
    reasons = data.get("reasons") if isinstance(data.get("reasons"), list) else []
    orders = data.get("recent_orders") if isinstance(data.get("recent_orders"), list) else []
    activity = data.get("activity") if isinstance(data.get("activity"), list) else []
    account_snapshot = (
        data.get("account_snapshot")
        if isinstance(data.get("account_snapshot"), dict)
        else {}
    )
    safety = data.get("safety") if isinstance(data.get("safety"), dict) else {}
    safety_summary = "UNKNOWN"
    if safety.get("status") == "verified":
        safety_summary = (
            f"{'FLAT' if safety.get('flat') is True else 'NON-FLAT'}, "
            f"working={safety.get('working_orders', 'UNKNOWN')} "
            f"({age_label(safety.get('age_s'))} ago)"
        )

    lines = [
        "CODE",
        f"  identity:       {identity.get('status', 'UNKNOWN')}",
        f"  release:        {release.get('release_id') or 'recovered EC2 baseline'}",
        f"  source SHA:     {str(release.get('effective_source_sha256') or 'UNKNOWN')[:12]}",
        f"  runtime source: {code.get('runtime_source') or 'UNKNOWN'}",
        f"  local source:   {identity.get('local_source') or 'UNKNOWN'}",
        f"  EC2 checkout:   {code.get('host_checkout') or 'UNKNOWN'}",
        f"  Git commit:     {code.get('git_revision_label') or code.get('host_git_commit') or 'UNKNOWN'}",
        f"  image:          {short_digest(code.get('configured_image'))}",
        f"  digest:         {short_digest(digest)}",
        f"  code mounts:    {len(mounts)}",
    ]
    for mount in mounts:
        lines.append(
            "    - "
            f"{mount.get('source')} -> {mount.get('destination')} "
            f"sha256:{str(mount.get('sha256') or 'UNKNOWN')[:12]}"
        )

    lines.extend(
        [
            "",
            "PROCESS",
            f"  service:        {service.get('active_state') or 'UNKNOWN'}",
            f"  container:      {service.get('container') or 'UNKNOWN'}",
            f"  restarts:       {service.get('restart_count') or 'UNKNOWN'}",
            f"  alpha:          {data.get('alpha') or 'UNKNOWN'}",
            f"  config:         {data.get('config_profile') or 'UNKNOWN'} / "
            f"{str(data.get('config_hash') or 'UNKNOWN')[:12]}",
            f"  mode / gate:    {data.get('mode') or data.get('status') or 'UNKNOWN'} / "
            f"{gate_label(data.get('order_gate'))}",
            f"  heartbeat:      {format_time(data.get('updated_at'))}",
            f"  broker view:    {str(account_snapshot.get('kind') or 'UNKNOWN').upper()} "
            f"(snapshot age {age_label(account_snapshot.get('age_s'))})",
            f"  REST verified:  {safety_summary}",
            "",
            "BOT NOW",
            f"  symbol:         {data.get('symbol') or 'UNKNOWN'}",
            f"  target:         {data.get('target_qty') if data.get('target_qty') is not None else 'UNKNOWN'}",
            f"  positions:      {json.dumps(positions, ensure_ascii=False, sort_keys=True) if positions is not None else 'UNKNOWN'}",
            f"  working orders: {data.get('working_orders') if data.get('working_orders') is not None else 'UNKNOWN'}",
            f"  reason:         {' + '.join(map(str, reasons)) if reasons else 'none'}",
            f"  next decision:  {format_time(data.get('next_decision_at'))}",
            f"  feed age:       {age_label(data.get('feed_age_s'))} futures / "
            f"{age_label(data.get('spot_feed_age_s'))} spot",
            f"  portfolio age:  {age_label(data.get('portfolio_age_s'))}",
            f"  last error:     {data.get('last_error') or 'none'}",
            "",
            "RECENT ACTIVITY",
        ]
    )
    if not activity:
        lines.append("  unavailable (runtime predates activity recorder)")
    else:
        for event in reversed(activity[-5:]):
            lines.append(
                f"  - {format_time(event.get('timestamp'))} "
                f"{describe_activity(event)}"
            )

    lines.extend(
        [
            "",
            "RECENT EXECUTION "
            f"({str(account_snapshot.get('kind') or 'unknown').replace('_', ' ')})",
        ]
    )
    if not orders:
        lines.append("  none in sanitized snapshot")
    else:
        for order in orders[:5]:
            lines.append(
                "  - "
                f"{order.get('order_date') or 'UNKNOWN'} "
                f"{order.get('side') or '?'} {order.get('quantity') or '?'} "
                f"{order.get('symbol') or '?'} @ {order.get('avg_fill_price') or order.get('price') or '?'} "
                f"[{order.get('status') or 'UNKNOWN'}]"
            )
    return "\n".join(lines)


def current_local_comparison(identity: dict[str, Any] | None = None) -> dict[str, Any]:
    identity = identity or {}
    manifest_path = Path(str(identity.get("manifest") or ""))
    if not manifest_path.is_file():
        manifest_path = BASELINE_ROOT / "production-source" / "source-manifest.json"
    manifest = load_json(manifest_path)
    files = manifest.get("source_files")
    if isinstance(files, dict):
        expected_files = {path: {"sha256": digest} for path, digest in files.items()}
    else:
        expected_files = manifest.get("files", {})
    exact = changed = missing = 0
    details = []
    for path, item in expected_files.items():
        local = ALGOTRADE_ROOT / path
        observed = sha256(local)
        expected = str(item["sha256"])
        state = "EXACT" if observed == expected else "MISSING" if observed is None else "CHANGED"
        exact += state == "EXACT"
        changed += state == "CHANGED"
        missing += state == "MISSING"
        if state != "EXACT":
            details.append({"path": path, "state": state})
    return {"exact": exact, "changed": changed, "missing": missing, "details": details}


def command_status(args: argparse.Namespace) -> int:
    data = enrich(live_status())
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_status(data))
    return 0


def command_source(args: argparse.Namespace) -> int:
    data = enrich(live_status())
    identity = data["source_identity"]
    path = identity.get("local_source")
    if not path or not Path(path).is_dir():
        print("Cannot map the live runtime to a verified local source snapshot", file=sys.stderr)
        return 2
    print(path)
    if args.open:
        subprocess.run(["open", path], check=True)
    return 0


def command_compare(args: argparse.Namespace) -> int:
    data = enrich(live_status())
    local = current_local_comparison(data["source_identity"])
    result = {
        "live": data["source_identity"],
        "local_workspace_vs_production": local,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Live runtime: {result['live'].get('status', 'UNKNOWN')}")
        print(f"Production source: {result['live'].get('local_source', 'UNKNOWN')}")
        print(
            "Local workspace vs production: "
            f"{local['exact']} exact, {local['changed']} changed, {local['missing']} missing"
        )
        for item in local["details"]:
            print(f"  - {item['state']}: {ALGOTRADE_ROOT.name}/{item['path']}")
    return 0 if result["live"].get("status") in {"RECOVERED_MATCH", "IMMUTABLE_MATCH"} else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="botctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="show live code and bot state")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)
    source = subparsers.add_parser("source", help="locate the verified live source")
    source.add_argument("--open", action="store_true")
    source.set_defaults(func=command_source)
    compare = subparsers.add_parser("compare", help="compare EC2, baseline, and local code")
    compare.add_argument("--json", action="store_true")
    compare.set_defaults(func=command_compare)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as exc:
        print(f"botctl failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
set -euo pipefail

# Read the sanitized PaperTrade runtime without opening an interactive SSM session.
# The command never reads the rendered environment, broker credentials, or state DB.
instance_id="${ALGOTRADE_INSTANCE_ID:-i-04ccc8700d99ec425}"
aws_region="${AWS_REGION:-ap-southeast-1}"

command -v aws >/dev/null || {
  echo "AWS CLI is required" >&2
  exit 1
}

read -r -d '' remote_command <<'PY' || true
python3 - <<'PYTHON'
import json
import hashlib
import subprocess
import time
from pathlib import Path

runtime = Path("/var/lib/algotrade/runtime")
ACTIVITY_FIELDS = {
    "status", "healthy", "mode", "alpha", "symbol", "order_gate",
    "configured_qty", "desired_qty", "positions", "reasons",
    "fix_logged_on", "worker_alive", "config_profile", "config_hash",
    "last_error",
}

def read(name):
    try:
        value = json.loads((runtime / name).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}

health = read("health.json")
account = read("account.json")
safety = read("safety.json")
orders = account.get("orders") if isinstance(account.get("orders"), list) else []
terminal = ("filled", "canceled", "cancelled", "rejected", "expired", "done")
working = [
    item for item in orders
    if not any(word in str(item.get("status", "")).lower() for word in terminal)
]

def age_seconds(value):
    try:
        return max(0.0, time.time() - float(value))
    except (TypeError, ValueError):
        return None

account_age = age_seconds(account.get("updated_at"))
account_fresh = (
    account_age is not None
    and account_age <= 120
    and account.get("status") == "healthy"
)
account_live = health.get("mode") == "alpha" and account_fresh
safety_age = age_seconds(safety.get("updated_at"))

def order_view(item):
    return {
        key: item.get(key)
        for key in (
            "symbol", "side", "quantity", "filled_quantity", "leaves_quantity",
            "price", "avg_fill_price", "status", "order_date", "last_update",
        )
    }

def activity_view(item):
    if not isinstance(item, dict):
        return None
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    state = payload.get("state") if isinstance(payload.get("state"), dict) else None
    changed = payload.get("changed") if isinstance(payload.get("changed"), dict) else None
    safe_payload = {}
    if state is not None:
        safe_payload["state"] = {
            key: value for key, value in state.items() if key in ACTIVITY_FIELDS
        }
    if changed is not None:
        safe_payload["changed"] = {
            key: value for key, value in changed.items() if key in ACTIVITY_FIELDS
        }
    return {
        key: item.get(key)
        for key in (
            "schema_version", "sequence", "timestamp", "runtime_instance_id",
            "release_id", "type",
        )
    } | {"payload": safe_payload}

def read_activity(limit=20):
    path = runtime / "activity.jsonl"
    try:
        lines = path.read_bytes()[-1_000_000:].splitlines()[-limit:]
    except OSError:
        return []
    result = []
    for raw in lines:
        if len(raw) > 64_000:
            continue
        try:
            event = activity_view(json.loads(raw))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if event is not None:
            result.append(event)
    return result

def command(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None

def json_command(*args, default=None):
    raw = command(*args)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default

def sha256(path):
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None

container_image_ref = command(
    "docker", "inspect", "--format", "{{.Config.Image}}", "algotrade-paper"
)
container_image_id = command(
    "docker", "inspect", "--format", "{{.Image}}", "algotrade-paper"
)
repo_digests = (
    json_command(
        "docker", "image", "inspect", "--format", "{{json .RepoDigests}}",
        container_image_id,
        default=[],
    )
    if container_image_id
    else []
)
labels = json_command(
    "docker", "inspect", "--format", "{{json .Config.Labels}}",
    "algotrade-paper", default={},
) or {}
mounts = json_command(
    "docker", "inspect", "--format", "{{json .Mounts}}",
    "algotrade-paper", default=[],
) or []
code_mounts = [
    {
        "source": item.get("Source"),
        "destination": item.get("Destination"),
        "read_only": not bool(item.get("RW", False)),
        "sha256": sha256(str(item.get("Source", ""))),
    }
    for item in mounts
    if str(item.get("Destination", "")).startswith("/app/")
    and (
        str(item.get("Destination", "")).endswith(".py")
        or "/alphas/" in str(item.get("Destination", ""))
        or "/algotrade_adapter/" in str(item.get("Destination", ""))
    )
]
host_git_commit = command("git", "-C", "/opt/algotrade", "rev-parse", "HEAD")
host_git_dirty = command(
    "git", "-C", "/opt/algotrade", "status", "--porcelain", "--untracked-files=no"
)
current_release = command("readlink", "-f", "/opt/algotrade/current")
identity_status = "REMOTE_DRIFT" if code_mounts else "UNKNOWN"
release_manifest = health.get("release") if isinstance(health.get("release"), dict) else {}
if not release_manifest:
    release_manifest = read("release.json") if (runtime / "release.json").exists() else {}
if not release_manifest:
    try:
        release_manifest = json.loads(
            command("docker", "exec", "algotrade-paper", "cat", "/app/release.json") or "{}"
        )
    except json.JSONDecodeError:
        release_manifest = {}

print(json.dumps({
    "code": {
        "identity_status": identity_status,
        "runtime_source": (
            "mixed: /app image plus host bind-mounted Python files"
            if code_mounts
            else "/app (inside the container image)"
        ),
        "host_release": current_release,
        "host_checkout": "/opt/algotrade",
        "host_git_commit": host_git_commit,
        "host_git_dirty": bool(host_git_dirty) if host_git_dirty is not None else None,
        "configured_image": container_image_ref,
        "container_image_id": container_image_id,
        "repo_digests": repo_digests,
        "git_revision_label": labels.get("org.opencontainers.image.revision"),
        "release_label": labels.get("org.opencontainers.image.version"),
        "release_manifest": {
            key: release_manifest.get(key)
            for key in (
                "schema_version", "release_id", "source_kind", "git_commit",
                "effective_source_sha256", "platform", "behavior_policy",
            )
        } if release_manifest else None,
        "code_mounts": code_mounts,
    },
    "account_snapshot": {
        "status": account.get("status") or "unavailable",
        "updated_at": account.get("updated_at"),
        "age_s": account_age,
        "fresh": account_fresh,
        "live": account_live,
        "kind": "live" if account_live else "last_known",
    },
    "safety": {
        key: safety.get(key)
        for key in (
            "schema_version", "updated_at", "status", "source", "flat",
            "nonflat_positions", "working_orders", "order_gate", "phase",
            "release_id",
        )
    } | {"age_s": safety_age} if safety else None,
    "updated_at": health.get("updated_at"),
    "status": health.get("status"),
    "mode": health.get("mode"),
    "healthy": health.get("healthy"),
    "alpha": health.get("alpha"),
    "config_profile": health.get("config_profile"),
    "config_hash": health.get("config_hash"),
    "symbol": health.get("symbol"),
    "index_symbol": health.get("index_symbol"),
    "spot_source": health.get("spot_source"),
    "order_gate": health.get("order_gate"),
    "target_qty": health.get("desired_qty"),
    "reasons": health.get("reasons"),
    "actual_positions": health.get("positions"),
    "next_decision_at": health.get("next_decision_at"),
    "next_signal_day": health.get("next_signal_day"),
    "next_calendar_target_qty": health.get("next_calendar_target_qty"),
    "next_reasons": health.get("next_reasons"),
    "feed_age_s": health.get("feed_age_s"),
    "spot_feed_age_s": health.get("spot_feed_age_s"),
    "portfolio_age_s": health.get("portfolio_age_s"),
    "basis": health.get("basis"),
    "basis_ready": health.get("basis_ready"),
    "basis_stale": health.get("basis_stale"),
    "last_error": health.get("last_error"),
    "service": {
        "active_state": command("systemctl", "is-active", "algotrade-paper"),
        "restart_count": command("systemctl", "show", "algotrade-paper", "--property=NRestarts", "--value"),
        "container": command("docker", "inspect", "--format", "{{.State.Status}} / {{if .State.Health}}{{.State.Health.Status}}{{end}}", "algotrade-paper"),
    },
    "working_orders": len(working) if account_live else None,
    "last_known_working_orders": len(working) if account else None,
    "recent_orders": [order_view(item) for item in orders[:5]],
    "activity": read_activity(),
}, ensure_ascii=False, separators=(",", ":")))
PYTHON
PY

parameters="$(python3 -c 'import json, sys; print(json.dumps({"commands": [sys.stdin.read()]}))' <<<"$remote_command")"
command_id="$(aws ssm send-command \
  --region "$aws_region" \
  --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript \
  --parameters "$parameters" \
  --comment "Read-only PaperTrade alpha status" \
  --query 'Command.CommandId' \
  --output text)"

for _ in $(seq 1 20); do
  status="$(aws ssm get-command-invocation \
    --region "$aws_region" \
    --command-id "$command_id" \
    --instance-id "$instance_id" \
    --query Status \
    --output text)"
  case "$status" in
    Success)
      aws ssm get-command-invocation \
        --region "$aws_region" \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query StandardOutputContent \
        --output text
      exit 0
      ;;
    Failed|Cancelled|TimedOut)
      aws ssm get-command-invocation \
        --region "$aws_region" \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query StandardErrorContent \
        --output text >&2
      exit 1
      ;;
  esac
  sleep 1
done

echo "Timed out waiting for SSM command $command_id" >&2
exit 1

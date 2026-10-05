"""Release identity and bounded activity timeline for the local runtime."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional


RELEASE_FIELDS = (
    "schema_version",
    "release_id",
    "source_kind",
    "git_commit",
    "effective_source_sha256",
    "platform",
    "behavior_policy",
    "host_bundle_sha256",
)

ACTIVITY_FIELDS = (
    "status",
    "healthy",
    "mode",
    "alpha",
    "symbol",
    "order_gate",
    "configured_qty",
    "desired_qty",
    "positions",
    "reasons",
    "fix_logged_on",
    "worker_alive",
    "last_error",
)

SENSITIVE_KEY_RE = re.compile(
    r"(?:password|passwd|secret|token|authorization|credential|account_id)",
    re.IGNORECASE,
)
SENSITIVE_TEXT_RES = (
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)\b(password|token|secret|authorization)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(https?://[^\s/:@]+:)[^\s/@]+@"),
)


def load_release_identity(path: Path = Path("/app/release.json")) -> Optional[dict[str, Any]]:
    """Read only public provenance fields from the image release manifest."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    release = {key: value.get(key) for key in RELEASE_FIELDS}
    if not isinstance(release.get("release_id"), str) or not release["release_id"]:
        return None
    return release


def _safe_text(value: str) -> str:
    result = value[:2_000]
    for pattern in SENSITIVE_TEXT_RES:
        if pattern.pattern.startswith("(?i)(https"):
            result = pattern.sub(r"\1[REDACTED]@", result)
        elif pattern.groups:
            result = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", result)
        else:
            result = pattern.sub("[REDACTED]", result)
    return result


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, Mapping):
        result = {}
        for key, item in list(value.items())[:100]:
            text_key = str(key)
            result[text_key] = (
                "[REDACTED]"
                if SENSITIVE_KEY_RE.search(text_key)
                else _safe_value(item, depth=depth + 1)
            )
        return result
    return _safe_text(str(value))


class ActivityRecorder:
    """Write state transitions as bounded JSON Lines without blocking on network."""

    def __init__(
        self,
        path: Path = Path("/app/runtime/activity.jsonl"),
        *,
        max_bytes: int = 5_000_000,
        backups: int = 2,
        runtime_instance_id: Optional[str] = None,
        release: Optional[dict[str, Any]] = None,
    ) -> None:
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        if not 0 <= backups <= 10:
            raise ValueError("backups must be in [0, 10]")
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self.runtime_instance_id = runtime_instance_id or uuid.uuid4().hex
        self.release = release
        self.sequence = 0
        self.previous: Optional[dict[str, Any]] = None
        self.last_write_error: Optional[str] = None

    def _rotate(self, incoming_bytes: int) -> None:
        try:
            current = self.path.stat().st_size
        except FileNotFoundError:
            return
        if current + incoming_bytes <= self.max_bytes:
            return
        if self.backups == 0:
            self.path.unlink(missing_ok=True)
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backups}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            target = self.path.with_name(f"{self.path.name}.{index + 1}")
            if source.exists():
                source.replace(target)
        self.path.replace(self.path.with_name(f"{self.path.name}.1"))

    def record(self, event_type: str, payload: Mapping[str, Any]) -> bool:
        self.sequence += 1
        event = {
            "schema_version": 1,
            "sequence": self.sequence,
            "timestamp": time.time(),
            "runtime_instance_id": self.runtime_instance_id,
            "release_id": self.release.get("release_id") if self.release else None,
            "type": str(event_type),
            "payload": _safe_value(payload),
        }
        encoded = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate(len(encoded))
            with self.path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            self.last_write_error = f"{type(exc).__name__}: {exc}"
            return False
        self.last_write_error = None
        return True

    def observe(self, snapshot: Mapping[str, Any]) -> bool:
        current = {
            key: _safe_value(snapshot.get(key))
            for key in ACTIVITY_FIELDS
            if key in snapshot
        }
        if self.previous is None:
            self.previous = current
            return self.record("runtime_snapshot", {"state": current})
        changed = {
            key: {"before": self.previous.get(key), "after": current.get(key)}
            for key in sorted(set(self.previous) | set(current))
            if self.previous.get(key) != current.get(key)
        }
        self.previous = current
        if not changed:
            return False
        return self.record("runtime_transition", {"changed": changed})

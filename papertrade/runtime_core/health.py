"""Atomic health snapshot writer shared by runtime entrypoints."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .observability import ActivityRecorder


class HealthWriter:
    def __init__(
        self,
        path: Path,
        *,
        release: Mapping[str, Any] | None,
        activity: ActivityRecorder,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.release = dict(release) if release is not None else None
        self.activity = activity
        self.clock = clock

    def write(self, status: str, **extra: Any) -> dict[str, Any]:
        payload = {
            "status": status,
            "updated_at": self.clock(),
            **extra,
            "runtime_instance_id": self.activity.runtime_instance_id,
            "release": self.release,
            "observability_error": self.activity.last_write_error,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        self.activity.observe(payload)
        return payload

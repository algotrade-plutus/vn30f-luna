#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path

path = Path("/app/runtime/health.json")
if not path.exists():
    raise SystemExit(1)
data = json.loads(path.read_text())
fresh = time.time() - float(data.get("updated_at", 0)) < 45
healthy = data.get("status") in {"healthy", "running"}
raise SystemExit(0 if fresh and healthy else 1)

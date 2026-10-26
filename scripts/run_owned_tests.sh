#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -n "${PYTHON:-}" ]]; then
    export PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}"
    "$PYTHON" -m pytest tests -q "$@"
else
    exec uv run --python 3.12 pytest tests -q "$@"
fi

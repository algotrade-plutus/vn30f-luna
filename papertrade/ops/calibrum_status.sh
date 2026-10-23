#!/usr/bin/env bash
# Read-only: runner container, health and the last journal lines. Usage: calibrum_status.sh [lines, default 12]
here="$(cd "$(dirname "$0")" && pwd)"
lines="${1:-12}"
"$here/ssm_run.sh" "docker ps --filter name=calibrum --format '{{.Names}} {{.Status}}'
echo '--- health'; cat /var/lib/calibrum/test/health.json 2>/dev/null || echo '(no health yet)'
echo '--- journal'; tail -n $lines /var/lib/calibrum/test/journal.jsonl 2>/dev/null || echo '(no journal yet)'"

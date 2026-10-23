#!/usr/bin/env bash
# Read-only: service, timer, container, health and the last journal lines.
# Usage: calibrum_status.sh [lines, default 12] [live|test, default live]
here="$(cd "$(dirname "$0")" && pwd)"
lines="${1:-12}"
state="/var/lib/calibrum/${2:-live}"
"$here/ssm_run.sh" "echo \"service: \$(systemctl is-active calibrum.service) / \$(systemctl is-enabled calibrum.service 2>/dev/null); timer: \$(systemctl list-timers calibrum.timer --no-legend | awk '{print \$1, \$2, \$3}')\"
grep -s CALIBRUM_IMAGE= /etc/calibrum/release.env; grep -s . /etc/calibrum/calibrum.env | tr '\n' ' '; echo
docker ps --filter name=calibrum --format '{{.Names}} {{.Status}}'
ls $state/HALT 2>/dev/null && echo 'HALT is set'
echo '--- health'; cat $state/health.json 2>/dev/null || echo '(no health yet)'
echo; echo '--- journal'; tail -n $lines $state/journal.jsonl 2>/dev/null || echo '(no journal yet)'"

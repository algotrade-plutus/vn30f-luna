#!/usr/bin/env bash
# Clear HALT and start the runner now (it exits by itself outside a session or on a non-trading day).
here="$(cd "$(dirname "$0")" && pwd)"
"$here/ssm_run.sh" "rm -f /var/lib/calibrum/live/HALT; systemctl start calibrum.service; sleep 20
systemctl is-active calibrum.service; tail -n 3 /var/lib/calibrum/live/journal.jsonl 2>/dev/null"

#!/usr/bin/env bash
# Stop new orders at once (HALT, which survives restarts and the next mornings) and stop the runner.
# Any open position stays open. calibrum_resume.sh undoes this.
here="$(cd "$(dirname "$0")" && pwd)"
"$here/ssm_run.sh" "touch /var/lib/calibrum/live/HALT /var/lib/calibrum/test/HALT 2>/dev/null; sleep 3
systemctl stop calibrum.service; docker stop -t 30 calibrum-test >/dev/null 2>&1 || true
docker ps --filter name=calibrum --format '{{.Names}} {{.Status}}'; echo 'HALT set; runner stopped'"

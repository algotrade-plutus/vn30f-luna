#!/usr/bin/env bash
# Stop new orders at once (HALT file), then stop the runner container. Any open position stays open.
here="$(cd "$(dirname "$0")" && pwd)"
"$here/ssm_run.sh" "touch /var/lib/calibrum/test/HALT; sleep 3; docker stop -t 30 calibrum-test 2>&1 | tail -1; docker ps --filter name=calibrum --format '{{.Names}} {{.Status}}'"

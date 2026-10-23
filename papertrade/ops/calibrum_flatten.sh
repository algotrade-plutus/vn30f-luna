#!/usr/bin/env bash
# Stop the runner, close the position in the managed contract, and leave the runner stopped.
# Start it again with calibrum_resume.sh (it will trade the current vote with the configured qty).
here="$(cd "$(dirname "$0")" && pwd)"
"$here/ssm_run.sh" 'set -e
systemctl stop calibrum.service
source /etc/calibrum/release.env
[ -f /run/algotrade/paperbroker.env ] || /opt/calibrum/deploy/render-env.sh
exec 9>/var/lib/algotrade/ops/execution.lock
flock -n 9 || { echo "execution lock is held by another runtime"; exit 1; }
docker run --rm --name calibrum-flatten --env-file /run/algotrade/paperbroker.env -e CALIBRUM_STATE_DIR=/state \
  --tmpfs /tmp -w /state --mount type=bind,src=/var/lib/calibrum/live,dst=/state \
  --entrypoint python "$CALIBRUM_IMAGE" -m papertrade.calibrum.flatten 2>&1 | grep -v -i "password\|username\|554=" | tail -20'

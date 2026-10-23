#!/usr/bin/env bash
# Start the Calibrum runner in ACTIVE mode on EC2 until 14:46 today. Usage: calibrum_active.sh [qty, default 1]
qty="${1:-1}"
here="$(cd "$(dirname "$0")" && pwd)"
"$here/ssm_run.sh" "set -e
mkdir -p /var/lib/calibrum/test && chmod 777 /var/lib/calibrum/test
[ -f /run/algotrade/paperbroker.env ] || /opt/algotrade/current/deploy/aws/render-env.sh
docker rm -f calibrum-test >/dev/null 2>&1 || true
until=\$(TZ=Asia/Ho_Chi_Minh date '+%Y-%m-%d 14:46')
setsid nohup flock -n /var/lib/algotrade/ops/execution.lock docker run --rm --name calibrum-test \
  --env-file /run/algotrade/paperbroker.env -e PAPERBROKER_ALLOW_ORDERS=true \
  --read-only --tmpfs /tmp --cap-drop ALL -w /state --mount type=bind,src=/var/lib/calibrum/test,dst=/state \
  calibrum-paper:test --mode active --qty $qty --state-dir /state --until \"\$until\" \
  > /var/lib/calibrum/test/console.log 2>&1 < /dev/null &
sleep 25; docker ps --filter name=calibrum-test --format '{{.Names}} {{.Status}}'; grep -v -i 'password\|username\|554=' /var/lib/calibrum/test/console.log | tail -5"

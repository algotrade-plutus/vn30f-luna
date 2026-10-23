#!/usr/bin/env bash
# Order-path smoke test on EC2 (cancel test + 1-contract round trip). Run during continuous trading.
here="$(cd "$(dirname "$0")" && pwd)"
"$here/ssm_run.sh" 'set -e
mkdir -p /var/lib/calibrum/test && chmod 777 /var/lib/calibrum/test
[ -f /run/algotrade/paperbroker.env ] || /opt/algotrade/current/deploy/aws/render-env.sh
exec 9>/var/lib/algotrade/ops/execution.lock
flock -n 9 || { echo "execution lock is held by another runtime"; exit 1; }
docker run --rm --name calibrum-smoke --env-file /run/algotrade/paperbroker.env -e CALIBRUM_STATE_DIR=/state \
  --tmpfs /tmp -w /state --mount type=bind,src=/var/lib/calibrum/test,dst=/state \
  --entrypoint python calibrum-paper:test -m papertrade.calibrum.smoke 2>&1 | grep -v -i "password\|username\|554=" | tail -30'

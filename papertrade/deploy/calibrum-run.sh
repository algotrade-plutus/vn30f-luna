#!/usr/bin/env bash
# One trading day of the Calibrum runner in Docker. systemd (calibrum.service) owns this process.
set -euo pipefail
source /etc/calibrum/release.env   # CALIBRUM_IMAGE
source /etc/calibrum/calibrum.env  # CALIBRUM_MODE, CALIBRUM_QTY, CALIBRUM_ALLOW_ORDERS
state=/var/lib/calibrum/live

# One owner of the PaperTrade execution session on this host, shared with any other launcher.
mkdir -p /var/lib/algotrade/ops
exec 9>/var/lib/algotrade/ops/execution.lock
flock -n 9 || { echo "another trading runtime holds the execution lock" >&2; exit 1; }

/opt/calibrum/deploy/render-env.sh
docker rm -f calibrum-live >/dev/null 2>&1 || true
exec docker run --rm --name calibrum-live \
  --env-file /run/algotrade/paperbroker.env \
  -e PAPERBROKER_ALLOW_ORDERS="$CALIBRUM_ALLOW_ORDERS" -e CALIBRUM_MODE="$CALIBRUM_MODE" -e CALIBRUM_QTY="$CALIBRUM_QTY" \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges=true -w /state \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=5 \
  --mount type=bind,src="$state",dst=/state \
  "$CALIBRUM_IMAGE" --state-dir /state

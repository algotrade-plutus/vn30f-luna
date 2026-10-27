#!/usr/bin/env bash
# Read-only dashboard over the runner's state, on 127.0.0.1:8080. systemd (calibrum-dashboard.service) owns this process.
# No secrets: it reads health.json and journal.jsonl and never talks to the broker.
set -euo pipefail
source /etc/calibrum/release.env   # CALIBRUM_IMAGE
docker rm -f calibrum-dashboard >/dev/null 2>&1 || true
exec docker run --rm --name calibrum-dashboard \
  --read-only --cap-drop ALL --security-opt no-new-privileges=true \
  --log-driver json-file --log-opt max-size=5m --log-opt max-file=2 \
  -p 127.0.0.1:8080:8080 \
  --mount type=bind,src=/var/lib/calibrum/live,dst=/state,readonly \
  --entrypoint python "$CALIBRUM_IMAGE" -m papertrade.calibrum.dashboard --state-dir /state --port 8080

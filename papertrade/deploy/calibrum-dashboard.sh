#!/usr/bin/env bash
# Read-only dashboard over the runner's state, on 127.0.0.1:8080. systemd (calibrum-dashboard.service) owns this process.
# No secrets: it reads health.json and journal.jsonl and never talks to the broker.
# 127.0.0.1:8081 is the public view that calibrum-tunnel.service publishes. CPU and memory are capped so that
# visitors cannot slow the runner on this t3.small.
set -euo pipefail
source /etc/calibrum/release.env   # CALIBRUM_IMAGE
docker rm -f calibrum-dashboard >/dev/null 2>&1 || true
exec docker run --rm --name calibrum-dashboard \
  --read-only --cap-drop ALL --security-opt no-new-privileges=true \
  --log-driver json-file --log-opt max-size=5m --log-opt max-file=2 \
  --cpus 0.5 --memory 640m --pids-limit 64 \
  -p 127.0.0.1:8080:8080 -p 127.0.0.1:8081:8081 \
  --mount type=bind,src=/var/lib/calibrum/live,dst=/state,readonly \
  --entrypoint python "$CALIBRUM_IMAGE" -m papertrade.calibrum.dashboard --state-dir /state --port 8080 --public-port 8081

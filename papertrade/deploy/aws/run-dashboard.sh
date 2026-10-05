#!/usr/bin/env bash
set -euo pipefail

image="${ALGOTRADE_IMAGE_REF:-${ALGOTRADE_IMAGE:-algotrade-paper:local}}"

docker rm -f algotrade-dashboard >/dev/null 2>&1 || true
exec docker run --name algotrade-dashboard \
  --restart no \
  --log-driver json-file \
  --log-opt max-size=5m \
  --log-opt max-file=3 \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --pids-limit 64 \
  --memory 128m \
  --publish 127.0.0.1:8080:8080 \
  --mount type=bind,src=/var/lib/algotrade/runtime,dst=/data,readonly \
  --health-cmd "python -m dashboard.healthcheck" \
  --health-interval 30s \
  --health-timeout 5s \
  --health-start-period 5s \
  --health-retries 3 \
  --entrypoint python \
  "$image" -m dashboard.server

#!/usr/bin/env bash
set -euo pipefail

install_dir="${ALGOTRADE_INSTALL_DIR:-/opt/algotrade}"
image="${ALGOTRADE_IMAGE_REF:-${ALGOTRADE_IMAGE:-algotrade-paper:local}}"
force_hold="${ALGOTRADE_FORCE_HOLD:-false}"

mkdir -p /var/lib/algotrade/ops
exec 9>/var/lib/algotrade/ops/execution.lock
if ! flock -n 9; then
  echo "Another trading runtime owns the execution lock" >&2
  exit 1
fi

if [[ "$force_hold" == "true" ]]; then
  mode_args=(--env PAPERTRADING_MODE=hold --env PAPERBROKER_ALLOW_ORDERS=false)
else
  mode_args=()
fi

"$install_dir/deploy/aws/render-env.sh"
docker rm -f algotrade-paper >/dev/null 2>&1 || true
exec docker run --name algotrade-paper \
  --env-file /run/algotrade/paperbroker.env \
  "${mode_args[@]}" \
  --restart no \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=5 \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --mount type=bind,src=/var/lib/algotrade/runtime,dst=/app/runtime \
  --mount type=bind,src=/var/lib/algotrade/state,dst=/app/state \
  --mount type=bind,src=/var/log/algotrade,dst=/app/logs \
  "$image"

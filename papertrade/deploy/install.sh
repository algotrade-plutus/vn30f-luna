#!/usr/bin/env bash
# Install a built image as the Calibrum release and (re)install the units. Run as root on the EC2.
# Usage: install.sh <image tag>. Does not start the runner: the timer and boot do.
set -euo pipefail
image="$1"
src="$(cd "$(dirname "$0")" && pwd)"
docker image inspect "$image" >/dev/null

install -d -m 750 /opt/calibrum/deploy /etc/calibrum
install -m 750 "$src/calibrum-run.sh" "$src/render-env.sh" "$src/calibrum-dashboard.sh" /opt/calibrum/deploy/
install -m 644 "$src/calibrum.service" "$src/calibrum.timer" "$src/calibrum-dashboard.service" /etc/systemd/system/
install -d -o 10001 -g 10001 -m 750 /var/lib/calibrum/live
# Operating knobs survive redeploys; edit this file to change them.
[ -f /etc/calibrum/calibrum.env ] || printf 'CALIBRUM_MODE=active\nCALIBRUM_QTY=10\nCALIBRUM_ALLOW_ORDERS=true\n' > /etc/calibrum/calibrum.env
previous="$(grep -s '^CALIBRUM_IMAGE=' /etc/calibrum/release.env | cut -d= -f2 || true)"
printf 'CALIBRUM_IMAGE=%s\nCALIBRUM_PREVIOUS_IMAGE=%s\nCALIBRUM_INSTALLED_AT=%s\n' \
  "$image" "$previous" "$(date -u +%FT%TZ)" > /etc/calibrum/release.env

systemctl daemon-reload
systemctl enable calibrum.service calibrum.timer >/dev/null
systemctl start calibrum.timer
# The old bot's dashboard held 127.0.0.1:8080 and shows a runtime that no longer trades.
if systemctl list-unit-files algotrade-dashboard.service >/dev/null 2>&1; then
  systemctl disable --now algotrade-dashboard.service >/dev/null 2>&1 || true
fi
systemctl enable calibrum-dashboard.service >/dev/null
systemctl restart calibrum-dashboard.service   # picks up the new image; the runner is not touched
echo "installed $image (previous ${previous:-none}); $(systemctl list-timers calibrum.timer --no-legend | awk '{print "next start", $1, $2, $3}')"

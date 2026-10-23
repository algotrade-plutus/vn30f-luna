#!/usr/bin/env bash
# Install a built image as the Calibrum release and (re)install the units. Run as root on the EC2.
# Usage: install.sh <image tag>. Does not start the runner: the timer and boot do.
set -euo pipefail
image="$1"
src="$(cd "$(dirname "$0")" && pwd)"
docker image inspect "$image" >/dev/null

install -d -m 750 /opt/calibrum/deploy /etc/calibrum
install -m 750 "$src/calibrum-run.sh" "$src/render-env.sh" /opt/calibrum/deploy/
install -m 644 "$src/calibrum.service" "$src/calibrum.timer" /etc/systemd/system/
install -d -o 10001 -g 10001 -m 750 /var/lib/calibrum/live
# Operating knobs survive redeploys; edit this file to change them.
[ -f /etc/calibrum/calibrum.env ] || printf 'CALIBRUM_MODE=active\nCALIBRUM_QTY=10\nCALIBRUM_ALLOW_ORDERS=true\n' > /etc/calibrum/calibrum.env
previous="$(grep -s '^CALIBRUM_IMAGE=' /etc/calibrum/release.env | cut -d= -f2 || true)"
printf 'CALIBRUM_IMAGE=%s\nCALIBRUM_PREVIOUS_IMAGE=%s\nCALIBRUM_INSTALLED_AT=%s\n' \
  "$image" "$previous" "$(date -u +%FT%TZ)" > /etc/calibrum/release.env

systemctl daemon-reload
systemctl enable calibrum.service calibrum.timer >/dev/null
systemctl start calibrum.timer
echo "installed $image (previous ${previous:-none}); $(systemctl list-timers calibrum.timer --no-legend | awk '{print "next start", $1, $2, $3}')"

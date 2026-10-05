#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root on Amazon Linux 2023" >&2
  exit 1
fi

dnf update -y
dnf install -y docker jq util-linux
systemctl enable --now docker
mkdir -p \
  /opt/algotrade/releases \
  /etc/algotrade \
  /var/lib/algotrade/runtime \
  /var/lib/algotrade/state \
  /var/lib/algotrade/control \
  /var/lib/algotrade/ops \
  /var/lib/algotrade/backups \
  /var/log/algotrade
chmod 750 /opt/algotrade /var/lib/algotrade /var/log/algotrade
chmod 750 /opt/algotrade/releases /etc/algotrade /var/lib/algotrade/control /var/lib/algotrade/ops /var/lib/algotrade/backups
chown -R 10001:10001 /var/lib/algotrade /var/log/algotrade
echo "Host ready. Copy this directory to /opt/algotrade, build the image, then install the systemd unit."

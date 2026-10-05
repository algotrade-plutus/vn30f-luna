#!/usr/bin/env bash
set -euo pipefail

install_dir="${ALGOTRADE_INSTALL_DIR:-/opt/algotrade}"
cd "$install_dir"
docker build --platform linux/amd64 --tag algotrade-paper:local .
mkdir -p /etc/algotrade
ln -sfn "$install_dir" "$install_dir/current"
cat >/etc/algotrade/release.env <<'ENV'
ALGOTRADE_RELEASE_ID=local-bootstrap
ALGOTRADE_IMAGE_REF=algotrade-paper:local
ALGOTRADE_FORCE_HOLD=true
ALGOTRADE_INSTALL_DIR=/opt/algotrade/current
ENV
chmod 0640 /etc/algotrade/release.env
install -m 0644 deploy/aws/algotrade-paper.service /etc/systemd/system/algotrade-paper.service
install -m 0644 deploy/aws/algotrade-dashboard.service /etc/systemd/system/algotrade-dashboard.service
chmod 0755 deploy/aws/render-env.sh deploy/aws/run-container.sh deploy/aws/run-dashboard.sh
systemctl daemon-reload
systemctl enable --now algotrade-paper.service
systemctl enable --now algotrade-dashboard.service

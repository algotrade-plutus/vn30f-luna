#!/usr/bin/env bash
set -euxo pipefail

aws_region="__AWS_REGION__"
secret_id="__SECRET_ID__"
image_ref="__IMAGE_REF__"

dnf update -y
dnf install -y docker
systemctl enable --now docker
systemctl enable --now amazon-ssm-agent || true

mkdir -p /run/algotrade /var/lib/algotrade/runtime /var/lib/algotrade/state /var/log/algotrade
chmod 700 /run/algotrade
chown -R 10001:10001 /var/lib/algotrade /var/log/algotrade

cat >/usr/local/bin/algotrade-render-env <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
runtime_dir=/run/algotrade
env_file="$runtime_dir/paperbroker.env"
mkdir -p "$runtime_dir"
chmod 700 "$runtime_dir"
umask 077
temp_file="$(mktemp "$runtime_dir/paperbroker.env.XXXXXX")"
aws secretsmanager get-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$ALGOTRADE_SECRET_ID" \
  --query SecretString \
  --output text \
| python3 -c '
import json, re, sys
data = json.load(sys.stdin)
for key, value in sorted(data.items()):
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        raise SystemExit(f"invalid environment key: {key!r}")
    value = str(value)
    if "\n" in value or "\r" in value:
        raise SystemExit(f"multiline secret is not supported: {key}")
    print(f"{key}={value}")
' > "$temp_file"
mv "$temp_file" "$env_file"
chmod 600 "$env_file"
SCRIPT

cat >/usr/local/bin/algotrade-run <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
/usr/local/bin/algotrade-render-env
registry="${ALGOTRADE_IMAGE_REF%%/*}"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$registry" >/dev/null
docker pull "$ALGOTRADE_IMAGE_REF"
docker rm -f algotrade-paper >/dev/null 2>&1 || true
exec docker run --name algotrade-paper \
  --env-file /run/algotrade/paperbroker.env \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=5 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --mount type=bind,src=/var/lib/algotrade/runtime,dst=/app/runtime \
  --mount type=bind,src=/var/lib/algotrade/state,dst=/app/state \
  --mount type=bind,src=/var/log/algotrade,dst=/app/logs \
  "$ALGOTRADE_IMAGE_REF"
SCRIPT

cat >/usr/local/bin/algotrade-dashboard-run <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
registry="${ALGOTRADE_IMAGE_REF%%/*}"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$registry" >/dev/null
docker pull "$ALGOTRADE_IMAGE_REF"
docker rm -f algotrade-dashboard >/dev/null 2>&1 || true
exec docker run --name algotrade-dashboard \
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
  "$ALGOTRADE_IMAGE_REF" -m dashboard.server
SCRIPT

chmod 0755 /usr/local/bin/algotrade-render-env /usr/local/bin/algotrade-run /usr/local/bin/algotrade-dashboard-run

cat >/etc/systemd/system/algotrade-paper.service <<UNIT
[Unit]
Description=Algotrade Paper Trading Runtime
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
Environment=AWS_REGION=$aws_region
Environment=ALGOTRADE_SECRET_ID=$secret_id
Environment=ALGOTRADE_IMAGE_REF=$image_ref
ExecStart=/usr/local/bin/algotrade-run
ExecStop=-/usr/bin/docker stop -t 20 algotrade-paper
Restart=always
RestartSec=10
TimeoutStartSec=0
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/algotrade-dashboard.service <<UNIT
[Unit]
Description=Private Algotrade Account Dashboard
After=docker.service network-online.target algotrade-paper.service
Wants=network-online.target algotrade-paper.service
Requires=docker.service

[Service]
Type=simple
Environment=AWS_REGION=$aws_region
Environment=ALGOTRADE_IMAGE_REF=$image_ref
ExecStart=/usr/local/bin/algotrade-dashboard-run
ExecStop=-/usr/bin/docker stop -t 10 algotrade-dashboard
Restart=always
RestartSec=10
TimeoutStartSec=0
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now algotrade-paper.service
systemctl enable --now algotrade-dashboard.service

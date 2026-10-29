#!/usr/bin/env bash
# Publish the dashboard's public view (127.0.0.1:8081) at https://calibrum.binarysearch.id.vn through a Cloudflare
# tunnel. systemd (calibrum-tunnel.service) owns this process. The connector only dials out to Cloudflare; no port
# opens on the EC2. The tunnel credentials live in SSM (/calibrum/cloudflared-credentials, SecureString) and are
# passed to the container through a root-only env file under /run.
set -euo pipefail
: "${AWS_REGION:=ap-southeast-1}"
parameter=/calibrum/cloudflared-credentials
image=cloudflare/cloudflared:2026.5.0

runtime_dir=/run/calibrum-tunnel
install -d -m 700 "$runtime_dir"
umask 077
if ! aws ssm get-parameter --region "$AWS_REGION" --name "$parameter" --with-decryption \
    --query Parameter.Value --output text > "$runtime_dir/credentials" 2> "$runtime_dir/error"; then
  if grep -q ParameterNotFound "$runtime_dir/error"; then
    echo "no $parameter in SSM: the dashboard stays private"
    exit 0
  fi
  cat "$runtime_dir/error" >&2
  exit 1
fi
tunnel_id="$(python3 -c '
import json, sys
creds = json.load(open(sys.argv[1]))
with open(sys.argv[2], "w") as env:
    env.write("TUNNEL_CRED_CONTENTS=" + json.dumps(creds, separators=(",", ":")) + "\n")
print(creds["TunnelID"])
' "$runtime_dir/credentials" "$runtime_dir/env")"
rm -f "$runtime_dir/credentials" "$runtime_dir/error"

docker rm -f calibrum-tunnel >/dev/null 2>&1 || true
exec docker run --rm --name calibrum-tunnel \
  --network host --read-only --cap-drop ALL --security-opt no-new-privileges=true \
  --cpus 0.25 --memory 128m --pids-limit 64 \
  --log-driver json-file --log-opt max-size=5m --log-opt max-file=2 \
  --env-file "$runtime_dir/env" \
  "$image" tunnel --no-autoupdate run --url http://127.0.0.1:8081 "$tunnel_id"

#!/usr/bin/env bash
# Open the read-only dashboard: forwards the EC2's 127.0.0.1:8080 to http://localhost:${1:-18080} through SSM.
# Needs the AWS CLI and session-manager-plugin. Ctrl-C closes the tunnel.
set -euo pipefail
instance="${ALGOTRADE_INSTANCE_ID:-i-04ccc8700d99ec425}"
port="${1:-18080}"
echo "dashboard: http://localhost:$port  (Ctrl-C to close)"
( sleep 4; command -v open >/dev/null && open "http://localhost:$port" ) &
exec aws ssm start-session --region ap-southeast-1 --target "$instance" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"8080\"],\"localPortNumber\":[\"$port\"]}"

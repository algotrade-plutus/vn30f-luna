#!/usr/bin/env bash
set -euo pipefail

instance_id="${ALGOTRADE_INSTANCE_ID:-i-04ccc8700d99ec425}"
aws_region="${AWS_REGION:-ap-southeast-1}"
local_port="${1:-8080}"

command -v aws >/dev/null || {
  echo "AWS CLI is required" >&2
  exit 1
}
command -v session-manager-plugin >/dev/null || {
  echo "AWS Session Manager plugin is required" >&2
  exit 1
}

echo "Opening private dashboard at http://localhost:${local_port}"
if command -v open >/dev/null; then
  (sleep 2; open "http://localhost:${local_port}") &
fi

exec aws ssm start-session \
  --region "$aws_region" \
  --target "$instance_id" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"8080\"],\"localPortNumber\":[\"${local_port}\"]}"

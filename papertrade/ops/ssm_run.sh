#!/usr/bin/env bash
# Usage: ssm_run.sh "<shell command>"  — runs on the PaperTrade EC2 via SSM and prints output.
set -euo pipefail
instance="${ALGOTRADE_INSTANCE_ID:-i-04ccc8700d99ec425}"
params=$(python3 -c 'import json,sys; print(json.dumps({"commands":[sys.argv[1]],"executionTimeout":["600"]}))' "$1")
id=$(aws ssm send-command --region ap-southeast-1 --instance-ids "$instance" \
  --document-name AWS-RunShellScript --parameters "$params" --query Command.CommandId --output text)
for _ in $(seq 1 120); do
  status=$(aws ssm get-command-invocation --region ap-southeast-1 --command-id "$id" --instance-id "$instance" \
    --query Status --output text 2>/dev/null || echo Pending)
  case "$status" in Success|Failed|Cancelled|TimedOut) break;; esac
  sleep 2
done
aws ssm get-command-invocation --region ap-southeast-1 --command-id "$id" --instance-id "$instance" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' --output text

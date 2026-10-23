#!/usr/bin/env bash
# Build the committed runtime on the EC2 as calibrum-paper:<git sha> and install it as the release.
# The runner is not started: calibrum.timer starts it on the next weekday morning (or at boot).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/../.."
# PaperTrade image that carries paperbroker-client 0.2.8 and QuickFIX for linux/amd64.
base="943193395259.dkr.ecr.ap-southeast-1.amazonaws.com/algotrade-paper@sha256:d352f82b902ea92f4d18591188e7674c152888380e5aacc4640a9f19cef779a6"
sha="$(git rev-parse --short=12 HEAD)"
if ! git diff --quiet HEAD -- src config papertrade; then
  echo "uncommitted changes under src, config or papertrade: commit first, so the tag names the code" >&2
  exit 1
fi
work="$(mktemp -d)"
git archive --format=tar.gz -o "$work/code.tgz" HEAD src config papertrade/calibrum papertrade/deploy papertrade/Dockerfile.calibrum
base64 < "$work/code.tgz" | tr -d '\n' > "$work/code.b64"
split -b 30000 "$work/code.b64" "$work/code.part."
"$here/ssm_run.sh" 'rm -rf /opt/calibrum-build && mkdir -p /opt/calibrum-build && : > /opt/calibrum-build/code.b64' >/dev/null
for part in "$work"/code.part.*; do "$here/ssm_run.sh" "printf '%s' '$(cat "$part")' >> /opt/calibrum-build/code.b64" >/dev/null; done
want=$(shasum -a 256 "$work/code.b64" | cut -c1-16)
"$here/ssm_run.sh" "set -e
test \"\$(sha256sum /opt/calibrum-build/code.b64 | cut -c1-16)\" = '$want' || { echo 'checksum mismatch'; exit 1; }
cd /opt/calibrum-build && base64 -d code.b64 | tar xzf -
docker build -q -f papertrade/Dockerfile.calibrum --build-arg BASE='$base' -t calibrum-paper:$sha . | tail -1
bash papertrade/deploy/install.sh calibrum-paper:$sha"

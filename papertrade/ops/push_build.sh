#!/usr/bin/env bash
# Upload the working tree's runtime code to the EC2 and build calibrum-paper:test there.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"
cd "$here/../.."
COPYFILE_DISABLE=1 tar --no-xattrs -czf "$work/code.tgz" --exclude=__pycache__ src config papertrade/calibrum papertrade/Dockerfile.calibrum
base64 < "$work/code.tgz" | tr -d '\n' > "$work/code.b64"
rm -f "$work"/code.part.*; split -b 30000 "$work/code.b64" "$work/code.part."
"$here/ssm_run.sh" 'rm -rf /opt/calibrum-build && mkdir -p /opt/calibrum-build && : > /opt/calibrum-build/code.b64' >/dev/null
for part in "$work"/code.part.*; do "$here/ssm_run.sh" "printf '%s' '$(cat "$part")' >> /opt/calibrum-build/code.b64" >/dev/null; done
want=$(shasum -a 256 "$work/code.b64" | cut -c1-16)
"$here/ssm_run.sh" "set -e
test \"\$(sha256sum /opt/calibrum-build/code.b64 | cut -c1-16)\" = '$want' || { echo 'checksum mismatch'; exit 1; }
cd /opt/calibrum-build && base64 -d code.b64 | tar xzf - && source /etc/algotrade/release.env
docker build -q -f papertrade/Dockerfile.calibrum --build-arg BASE=\"\$ALGOTRADE_IMAGE_REF\" -t calibrum-paper:test . | tail -1"

# Production runtime baseline — 2026-09-24

This directory records the effective PaperTrade runtime captured read-only from
the EC2 instance. It contains source and operational metadata, never runtime
credentials, rendered environment values, broker account identifiers, state
databases, or raw broker payloads.

## Result

Snapshot bên dưới mô tả runtime cũ tại thời điểm capture. Từ ngày 2026-09-24,
EC2 đã chạy release immutable
`ec2-baseline-observable-20260924-015c4e1b1be0` ở forced HOLD; `botctl` báo
`IMMUTABLE_MATCH`, không còn Python code mount và dashboard chỉ bind loopback.

At capture time, the production runtime was recoverable but not attributable to
one Git commit. It consisted of an ECR image plus four writable Python bind
mounts:

| Effective path | Source |
|---|---|
| `/app/algotrade_adapter/safe_alpha.py` | `/var/lib/algotrade/safe_alpha.py` |
| `/app/alphas/master_unified/service.py` | `/var/lib/algotrade/service.py` |
| `/app/alphas/master_unified/genesis_engine.py` | `/var/lib/algotrade/genesis_engine.py` |
| `/app/alphas/master_unified/schedule.py` | `/var/lib/algotrade/schedule.py` |

The dashboard separately bind-mounted its static `index.html`. The image had no
Git revision/release label, `/opt/algotrade` was not a Git work tree, and there
was no `/opt/algotrade/current` release pointer. `botctl` therefore labeled that
runtime `RECOVERED_MATCH`: its exact effective source was known and matched this
snapshot, but it was still hot-patched.

At the last inventory capture, the trading and dashboard services were active,
the trading container was healthy, the managed position and working-order list
were empty, the target was zero, and the order gate was open. These are
time-sensitive observations; use `botctl status` for current truth.

An extra `algotrade-reentry-watchdog.service` and its script exist on the host.
The unit is disabled and inactive. The script can create a second FIX client,
cancel orders, and start the trading service, so it remains part of the
baseline evidence but must not be re-enabled in the final single-owner runtime.

## Source mapping

The verified effective trading snapshot has 23 application files:

- 15 are byte-for-byte equal to the current local workspace.
- 3 match an older tracked Git version while local code has changed.
- 6 differ from local and have no exact blob in the available Git history.
- The current local runtime also has decomposed modules that do not exist in
  production, including `alpha.py`, `signal_composer.py`, `supervisor.py`,
  `bar_aggregator.py`, and `luna_core`.

Open the exact recovered production source at:

```text
algotrade/runtime-baseline/production-source/app
```

`source-map.json` contains the per-file hashes, origins, local comparison, and
matching Git commits. `production-source/source-manifest.json` is the canonical
snapshot manifest. `baseline-inventory.json` is the sanitized host/runtime
inventory.

## Behavior evidence

The current `test_master_unified_service.py` suite was executed against the
recovered production source in isolation:

```text
23 passed, 4 failed
```

Three failures exercise local-only composer/take-profit/re-entry behavior that
production does not contain. The fourth exercises the newer rule that blocks
opening exposure when the basis feed is stale; production still emits the
entry after the reversal close. These failures are expected characterization
evidence and prove that the local strategy changes must not be silently folded
into the immutable baseline.

The normal local PaperTrade suite currently reports:

```text
100 passed, 1 skipped
```

The skipped test requires native QuickFIX, which is verified in the Linux image
path rather than the local macOS environment.

## Immutable local candidate

Release ID:

```text
ec2-baseline-20260924-74f9b42fbda8
```

The `Dockerfile` pins the exact current ECR base digest and bakes the four
Python overrides plus dashboard override into the image. The effective-source
digest is:

```text
74f9b42fbda88c74683ab3a974f98cb16905dfc8094d021f5cf8f54a5b037d90
```

Local image `algotrade-paper:baseline-74f9b42f` was built for `linux/amd64`.
`verify_runtime_baseline.py` verified all 23 effective paths, image labels, the
embedded release manifest, and platform. A container smoke test in `hold` mode
reported a healthy heartbeat and closed order gate without broker credentials.

The image has not been pushed and EC2 has not been changed.

## Strategy-preserving observable candidate

Release ID:

```text
ec2-baseline-observable-20260924-015c4e1b1be0
```

This candidate keeps the four recovered strategy/runtime overrides byte-for-byte
and adds only the frozen runtime identity/activity writer, entrypoint integration,
and read-only dashboard. Its effective-source digest is:

```text
25d562a60092aa59d46b2ddec39344a733fdb64d29384ea9a7ae026368d1612e
```

`verify_observable_baseline.py` verified 25 effective source paths, the embedded
manifest, labels, and `linux/amd64` platform. A real container smoke test produced
a fresh healthy HOLD heartbeat, a closed order gate, the expected release ID,
and the `runtime_snapshot` then `runtime_transition` activity sequence. The
merged source a human should inspect is at:

```text
algotrade/runtime-baseline/observable-source/app
```

Image đã được push theo digest bất biến và cài lên EC2. Acceptance xác nhận hai
service active, container healthy/restart 0, REST phẳng/0 working order, FIX
login read-only thành công và Kafka historical smoke nhận dữ liệu.

## Operator commands

```bash
./algotrade/scripts/botctl status
./algotrade/scripts/botctl source
./algotrade/scripts/botctl compare
python3 algotrade/scripts/verify_runtime_baseline.py \
  --image algotrade-paper:baseline-74f9b42f
python3 algotrade/scripts/verify_observable_baseline.py \
  --image algotrade-paper:baseline-observable-015c4e1b
```

`status` shows code identity, source locations, process health, target,
positions, working orders, decision reason, feed freshness, and recent
execution. `source` prints the exact local snapshot corresponding to EC2.
`compare` separates production source from the local development workspace.

## Remaining activation boundary

Deployment remains in forced HOLD with `PAPERBROKER_ALLOW_ORDERS=false`.
Changing to alpha mode, enabling paper orders, or increasing quantity remains a
separate explicit authorization step.

## Sanitization note (2026-10-05)

Vendor branding was removed from the archived snapshot comment and image label key.
The snapshot file hashes and effective-source digests in this directory were recomputed
for the sanitized files. Release IDs were kept as lineage identifiers; they no longer
encode the updated digests. The live EC2 image captured on 2026-09-24 still contains
the original pre-sanitization bytes and label key.

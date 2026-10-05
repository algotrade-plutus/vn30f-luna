from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "botctl.py"
SPEC = importlib.util.spec_from_file_location("papertrade_botctl", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
botctl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = botctl
SPEC.loader.exec_module(botctl)


class BotctlIdentityTests(unittest.TestCase):
    def recovered_live(self) -> dict:
        manifest = botctl.load_json(
            botctl.BASELINE_ROOT / "production-source" / "source-manifest.json"
        )
        mounts = [
            {
                "source": item["source"],
                "destination": f"/app/{path}",
                "sha256": item["sha256"],
            }
            for path, item in manifest["files"].items()
            if item.get("origin") == "host_override"
        ]
        return {
            "code": {
                "repo_digests": [manifest["image"]],
                "code_mounts": mounts,
                "release_manifest": None,
            }
        }

    def test_recovered_snapshot_matches_exact_live_hashes(self) -> None:
        identity = botctl.recovered_baseline_match(self.recovered_live())
        self.assertEqual(identity["status"], "RECOVERED_MATCH")
        self.assertTrue(identity["image_matches"])
        self.assertTrue(identity["mounts_match"])

    def test_changed_hot_patch_is_a_mismatch(self) -> None:
        live = self.recovered_live()
        live["code"]["code_mounts"][0]["sha256"] = "0" * 64
        identity = botctl.recovered_baseline_match(live)
        self.assertEqual(identity["status"], "MISMATCH")
        self.assertFalse(identity["mounts_match"])

    def test_unexpected_code_mount_is_a_mismatch(self) -> None:
        live = self.recovered_live()
        live["code"]["code_mounts"].append(
            {
                "source": "/var/lib/algotrade/untracked.py",
                "destination": "/app/untracked.py",
                "sha256": "1" * 64,
            }
        )
        identity = botctl.recovered_baseline_match(live)
        self.assertEqual(identity["status"], "MISMATCH")
        self.assertEqual(
            identity["unexpected_code_mounts"],
            ["/var/lib/algotrade/untracked.py"],
        )

    def test_immutable_release_requires_no_code_mounts(self) -> None:
        release = botctl.load_json(botctl.BASELINE_ROOT / "release-manifest.json")
        image = f"repo/image@sha256:{'a' * 64}"
        live = {"code": {
            "release_manifest": release,
            "code_mounts": [],
            "configured_image": image,
            "repo_digests": [image],
        }}
        self.assertEqual(
            botctl.immutable_release_match(live)["status"],
            "IMMUTABLE_MATCH",
        )
        live["code"]["code_mounts"] = [{"source": "/tmp/hot.py"}]
        self.assertEqual(
            botctl.immutable_release_match(live)["status"],
            "MISMATCH",
        )

    def test_observable_immutable_release_maps_to_merged_source(self) -> None:
        release = botctl.load_json(
            botctl.BASELINE_ROOT / "observable-release-manifest.json"
        )
        image = f"repo/image@sha256:{'a' * 64}"
        live = {"code": {
            "release_manifest": release,
            "code_mounts": [],
            "configured_image": image,
            "repo_digests": [image],
        }}
        identity = botctl.immutable_release_match(live)
        self.assertEqual(identity["status"], "IMMUTABLE_MATCH")
        self.assertTrue(identity["local_source"].endswith("observable-source/app"))

    def test_immutable_release_rejects_mutable_image_tag(self) -> None:
        release = botctl.load_json(botctl.BASELINE_ROOT / "release-manifest.json")
        live = {"code": {
            "release_manifest": release,
            "code_mounts": [],
            "configured_image": "repo/image:latest",
            "repo_digests": [f"repo/image@sha256:{'a' * 64}"],
        }}
        identity = botctl.immutable_release_match(live)
        self.assertEqual(identity["status"], "MISMATCH")
        self.assertFalse(identity["image_is_pinned"])

    def test_gate_label_accepts_boolean_and_env_style_values(self) -> None:
        self.assertEqual(botctl.gate_label(True), "OPEN")
        self.assertEqual(botctl.gate_label("true"), "OPEN")
        self.assertEqual(botctl.gate_label(False), "CLOSED")
        self.assertEqual(botctl.gate_label("false"), "CLOSED")
        self.assertEqual(botctl.gate_label(None), "UNKNOWN")

    def test_hold_never_presents_stale_account_as_live_truth(self) -> None:
        live = self.recovered_live()
        live.update({
            "mode": "hold",
            "actual_positions": {"HNXDS:VN30F2610": 8},
            "working_orders": 1,
            "account_snapshot": {
                "live": False,
                "kind": "last_known",
                "age_s": 600,
            },
            "safety": {
                "status": "verified",
                "flat": True,
                "working_orders": 0,
                "age_s": 30,
            },
        })
        enriched = botctl.enrich(live)
        self.assertIsNone(enriched["actual_positions"])
        self.assertIsNone(enriched["working_orders"])
        rendered = botctl.format_status(enriched)
        self.assertIn("LAST_KNOWN", rendered)
        self.assertIn("FLAT, working=0", rendered)

    def test_human_status_contains_code_process_and_bot_state(self) -> None:
        live = self.recovered_live()
        live.update(
            {
                "source_identity": {"status": "RECOVERED_MATCH"},
                "service": {"active_state": "active", "container": "running / healthy"},
                "status": "running",
                "order_gate": True,
                "alpha": "HybridGatedSupervisor",
                "symbol": "HNXDS:VN30F2610",
                "target_qty": 0,
                "actual_positions": {},
                "working_orders": 0,
                "reasons": ["calendar_flat"],
                "activity": [
                    {
                        "timestamp": 1_700_000_000,
                        "type": "runtime_transition",
                        "payload": {
                            "changed": {
                                "desired_qty": {"before": 8, "after": 0},
                            }
                        },
                    }
                ],
            }
        )
        rendered = botctl.format_status(live)
        self.assertIn("CODE", rendered)
        self.assertIn("PROCESS", rendered)
        self.assertIn("BOT NOW", rendered)
        self.assertIn("RECENT ACTIVITY", rendered)
        self.assertIn("desired_qty: 8 -> 0", rendered)
        self.assertIn("RECENT EXECUTION", rendered)
        self.assertIn("calendar_flat", rendered)


if __name__ == "__main__":
    unittest.main()

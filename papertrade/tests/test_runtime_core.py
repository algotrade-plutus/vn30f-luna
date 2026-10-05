from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime_core.config import (  # noqa: E402
    ConfigError,
    RuntimePaths,
    load_master_unified_config,
)
from runtime_core.control import ControlGate, ControlState  # noqa: E402
from runtime_core.health import HealthWriter  # noqa: E402
from runtime_core.observability import ActivityRecorder  # noqa: E402
from runtime_core.reconcile import reconcile_account  # noqa: E402


class RuntimeConfigTests(unittest.TestCase):
    def paths(self, root: Path) -> RuntimePaths:
        return RuntimePaths(root / "state", root / "runtime", root / "logs")

    def test_config_is_typed_once_and_fingerprint_excludes_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            first = load_master_unified_config(
                "hybrid",
                {
                    "CALENDAR_QTY": "8",
                    "PAPER_PASSWORD": "first-secret",
                    "HYBRID_GATED_EVAL_INTERVAL_S": "2.5",
                },
                paths=paths,
            )
            second = load_master_unified_config(
                "hybrid",
                {
                    "CALENDAR_QTY": "8",
                    "PAPER_PASSWORD": "different-secret",
                    "HYBRID_GATED_EVAL_INTERVAL_S": "2.5",
                },
                paths=paths,
            )
        self.assertEqual(first.quantity, 8)
        self.assertEqual(first.eval_interval_s, 2.5)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertNotIn("PASSWORD", json.dumps(first.public_dict()).upper())

    def test_fixed_rollover_requires_and_returns_explicit_symbol(self) -> None:
        with self.assertRaisesRegex(ConfigError, "VN30F1M"):
            load_master_unified_config("hybrid", {"VN30F_ROLLOVER_MODE": "fixed"})
        config = load_master_unified_config(
            "hybrid",
            {"VN30F_ROLLOVER_MODE": "fixed", "VN30F1M": "HNXDS:VN30F2610"},
        )
        resolved = config.resolve_symbol(
            datetime(2026, 9, 24), lambda _: "HNXDS:SHOULD_NOT_BE_USED"
        )
        self.assertEqual(resolved, "HNXDS:VN30F2610")

    def test_quantity_above_hard_cap_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, r"\[1, 10\]"):
            load_master_unified_config("hybrid", {"CALENDAR_QTY": "11"})

    def test_removed_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "profile must be hybrid"):
            load_master_unified_config("genesis", {})


class ControlGateTests(unittest.TestCase):
    def write(self, root: Path, **overrides) -> Path:
        value = {
            "state": "ACTIVE",
            "generation": 4,
            "release_id": "release-1",
            "config_hash": "abc",
            "quantity": 8,
            "halt_latched": False,
            **overrides,
        }
        path = root / "desired.json"
        path.write_text(json.dumps(value))
        return path

    def gate(self, path: Path, *, static_gate: bool = True) -> ControlGate:
        return ControlGate(
            path,
            release_id="release-1",
            config_hash="abc",
            quantity=8,
            static_gate=static_gate,
        )

    def test_exact_active_authorization_allows_submit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gate = self.gate(self.write(Path(temp)))
            decision = gate.decision()
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, ControlState.ACTIVE)
        self.assertEqual(decision.generation, 4)

    def test_missing_malformed_or_mismatched_control_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertFalse(self.gate(root / "missing.json").decision().allowed)
            mismatch = self.gate(self.write(root, release_id="other")).decision()
            self.assertFalse(mismatch.allowed)
            self.assertEqual(mismatch.reason, "authorization_release_id_mismatch")
            halted = self.gate(self.write(root, halt_latched=True)).decision()
            self.assertFalse(halted.allowed)
            self.assertEqual(halted.state, ControlState.HALTED)
            self.assertFalse(self.gate(self.write(root), static_gate=False).decision().allowed)


class ReconcileTests(unittest.TestCase):
    def test_reconcile_normalizes_positions_and_finds_working_orders(self) -> None:
        snapshot = reconcile_account(
            [
                {"instrument": "VN30F2610", "openQuantity": "8"},
                {"instrument": "HNXDS:OTHER", "quantity": -1},
            ],
            [
                {"symbol": "VN30F2610", "status": "New", "leavesQty": 8},
                {"symbol": "VN30F2610", "status": "Order was fully filled"},
            ],
            managed_symbols=("HNXDS:VN30F2610",),
        )
        self.assertEqual(snapshot.positions["HNXDS:VN30F2610"], 8)
        self.assertEqual(snapshot.foreign_positions, ("HNXDS:OTHER",))
        self.assertEqual(len(snapshot.working_orders), 1)
        self.assertFalse(snapshot.flat)

    def test_malformed_rows_are_unknown_instead_of_empty(self) -> None:
        snapshot = reconcile_account([{}], ["bad"], managed_symbols=())
        self.assertFalse(snapshot.known)
        self.assertIsNone(snapshot.flat)


class HealthWriterTests(unittest.TestCase):
    def test_health_and_activity_share_runtime_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            activity = ActivityRecorder(
                root / "activity.jsonl",
                max_bytes=4096,
                runtime_instance_id="runtime-1",
                release={"release_id": "release-1"},
            )
            writer = HealthWriter(
                root / "health.json",
                release={"release_id": "release-1"},
                activity=activity,
                clock=lambda: 123.0,
            )
            payload = writer.write("running", mode="alpha", order_gate=True)
            stored = json.loads((root / "health.json").read_text())
            event = json.loads((root / "activity.jsonl").read_text())
        self.assertEqual(stored, payload)
        self.assertEqual(stored["runtime_instance_id"], "runtime-1")
        self.assertEqual(event["runtime_instance_id"], "runtime-1")
        self.assertEqual(event["release_id"], "release-1")


if __name__ == "__main__":
    unittest.main()

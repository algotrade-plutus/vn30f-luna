from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard import server  # noqa: E402


class DashboardTests(unittest.TestCase):
    def test_status_payload_reads_only_whitelisted_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            (data / "health.json").write_text(json.dumps({"healthy": True}))
            (data / "account.json").write_text(json.dumps({"account": {"total_balance": 1}}))
            (data / "activity.jsonl").write_text(
                json.dumps({"type": "runtime_snapshot", "payload": {"desired_qty": 0}})
                + "\n"
            )
            (data / "safety.json").write_text(json.dumps({
                "status": "verified",
                "updated_at": 1,
                "flat": True,
                "working_orders": 0,
                "account_id": "must-not-pass",
            }))
            (data / "secret.env").write_text("PASSWORD=not-readable-through-api")
            with patch.object(server, "DATA_DIR", data):
                payload = server.status_payload()
            self.assertTrue(payload["health"]["healthy"])
            self.assertEqual(payload["account"]["account"]["total_balance"], 1)
            self.assertEqual(payload["activity"][0]["type"], "runtime_snapshot")
            self.assertTrue(payload["safety"]["flat"])
            self.assertEqual(payload["freshness"]["account_kind"], "last_known")
            self.assertNotIn("secret", json.dumps(payload))
            self.assertNotIn("account_id", json.dumps(payload))

    def test_hold_marks_account_snapshot_as_last_known(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            now = 1_700_000_000
            (data / "health.json").write_text(json.dumps({
                "status": "healthy", "mode": "hold", "updated_at": now,
            }))
            (data / "account.json").write_text(json.dumps({
                "status": "healthy", "updated_at": now, "positions": [],
            }))
            with patch.object(server, "DATA_DIR", data), patch.object(
                server.time, "time", return_value=now + 1
            ):
                payload = server.status_payload()
            self.assertTrue(payload["freshness"]["account_fresh"])
            self.assertFalse(payload["freshness"]["account_live"])
            self.assertEqual(payload["freshness"]["account_kind"], "last_known")

    def test_invalid_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.json"
            path.write_text("not json")
            self.assertEqual(server.read_json(path), {"status": "unavailable"})

    def test_activity_skips_invalid_and_oversized_records(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "activity.jsonl"
            valid = {
                "type": "runtime_transition",
                "payload": {
                    "changed": {"desired_qty": {"before": 0, "after": 8}},
                    "secret": "must-not-pass",
                },
            }
            path.write_bytes(
                b"not-json\n"
                + (b"x" * (server.MAX_ACTIVITY_EVENT_BYTES + 1))
                + b"\n"
                + json.dumps(valid).encode()
                + b"\n"
            )
            result = server.read_activity(path)
            self.assertEqual(result[0]["type"], "runtime_transition")
            self.assertEqual(
                result[0]["payload"]["changed"]["desired_qty"],
                {"before": 0, "after": 8},
            )
            self.assertNotIn("secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()

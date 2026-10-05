from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algotrade_adapter.runtime_observability import (  # noqa: E402
    ActivityRecorder,
    load_release_identity,
)


class RuntimeObservabilityTests(unittest.TestCase):
    def test_release_identity_uses_only_public_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "release.json"
            path.write_text(
                json.dumps(
                    {
                        "release_id": "r1",
                        "git_commit": "abc",
                        "effective_source_sha256": "123",
                        "password": "must-not-leak",
                    }
                )
            )
            release = load_release_identity(path)
            self.assertEqual(release["release_id"], "r1")
            self.assertNotIn("password", release)

    def test_missing_or_invalid_release_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertIsNone(load_release_identity(root / "missing.json"))
            invalid = root / "invalid.json"
            invalid.write_text("{}")
            self.assertIsNone(load_release_identity(invalid))

    def test_activity_records_only_transitions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "activity.jsonl"
            recorder = ActivityRecorder(
                path,
                max_bytes=4096,
                runtime_instance_id="instance-1",
                release={"release_id": "r1"},
            )
            snapshot = {
                "status": "running",
                "desired_qty": 0,
                "positions": {},
                "updated_at": 1,
                "feed_age_s": 1,
            }
            self.assertTrue(recorder.observe(snapshot))
            self.assertFalse(recorder.observe({**snapshot, "updated_at": 2, "feed_age_s": 9}))
            self.assertTrue(recorder.observe({**snapshot, "desired_qty": 8}))

            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([event["type"] for event in events], [
                "runtime_snapshot",
                "runtime_transition",
            ])
            self.assertEqual(events[0]["release_id"], "r1")
            self.assertEqual(
                events[1]["payload"]["changed"]["desired_qty"],
                {"before": 0, "after": 8},
            )
            self.assertNotIn("feed_age_s", events[1]["payload"]["changed"])

    def test_activity_rotation_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "activity.jsonl"
            recorder = ActivityRecorder(path, max_bytes=1024, backups=1)
            for index in range(20):
                recorder.record("test", {"index": index, "message": "x" * 100})
            self.assertTrue(path.exists())
            self.assertLessEqual(path.stat().st_size, 1024)
            self.assertTrue(path.with_name("activity.jsonl.1").exists())

    def test_activity_redacts_sensitive_keys_and_text(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "activity.jsonl"
            recorder = ActivityRecorder(path, max_bytes=4096)
            recorder.record(
                "test",
                {
                    "password": "plaintext",
                    "last_error": "token=secret-value",
                    "url": "https://user:pass@example.invalid/path",
                },
            )
            content = path.read_text()
            self.assertNotIn("plaintext", content)
            self.assertNotIn("secret-value", content)
            self.assertNotIn("user:pass@", content)
            self.assertIn("[REDACTED]", content)


if __name__ == "__main__":
    unittest.main()

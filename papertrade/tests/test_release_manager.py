from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from argparse import Namespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "release_manager.py"
SPEC = importlib.util.spec_from_file_location("papertrade_release_manager", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
manager = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manager
SPEC.loader.exec_module(manager)


class ReleaseManagerTests(unittest.TestCase):
    def manifest(self) -> dict:
        return {
            "schema_version": 1,
            "release_id": "release-1",
            "source_kind": "test",
            "git_commit": None,
            "effective_source_sha256": "a" * 64,
            "platform": "linux/amd64",
            "behavior_policy": "hold_only",
            "host_bundle_sha256": "c" * 64,
            "host_bundle_files": {"deploy/aws/example": "d" * 64},
        }

    @staticmethod
    def bind_bundle(manifest: dict, bundle: Path) -> dict:
        files = manager.host_bundle_files(bundle)
        manifest["host_bundle_files"] = files
        manifest["host_bundle_sha256"] = manager.host_bundle_digest(files)
        return manifest

    def test_release_requires_immutable_image(self) -> None:
        with self.assertRaisesRegex(ValueError, "immutable"):
            manager.validate_release(self.manifest(), "repo/image:latest")
        manager.validate_release(
            self.manifest(), f"repo/image@sha256:{'b' * 64}"
        )

    def test_preflight_distinguishes_unknown_from_flat(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = manager.Paths(Path(temp))
            paths.runtime.mkdir(parents=True)
            (paths.runtime / "health.json").write_text(
                json.dumps({
                    "status": "running",
                    "updated_at": time.time(),
                    "order_gate": True,
                })
            )
            result = manager.preflight(paths)
            self.assertIsNone(result["flat"])
            self.assertIsNone(result["working_orders"])
            with self.assertRaisesRegex(RuntimeError, "account snapshot"):
                manager.assert_quiet(result)

    def test_preflight_accepts_only_flat_and_no_working_orders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = manager.Paths(Path(temp))
            paths.runtime.mkdir(parents=True)
            (paths.runtime / "account.json").write_text(
                json.dumps({
                    "updated_at": time.time(),
                    "status": "healthy",
                    "positions": [{"quantity": 0}],
                    "orders": [
                        {"status": "Order was fully filled"},
                        {"status": "Canceled"},
                        {"status": "Order was canceled successfully"},
                    ],
                })
            )
            (paths.runtime / "health.json").write_text(json.dumps({
                "status": "running", "updated_at": time.time(),
            }))
            result = manager.preflight(paths)
            self.assertTrue(result["flat"])
            self.assertEqual(result["working_orders"], 0)
            manager.assert_quiet(result)

    def test_release_env_always_forces_hold(self) -> None:
        value = manager.release_env("release-1", f"repo/image@sha256:{'b' * 64}")
        self.assertIn("ALGOTRADE_FORCE_HOLD=true", value)
        self.assertNotIn("PAPERBROKER_ALLOW_ORDERS=true", value)

    def test_stage_release_refuses_same_id_with_different_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = manager.Paths(root / "host")
            bundle = root / "bundle"
            (bundle / "deploy" / "aws").mkdir(parents=True)
            (bundle / "deploy" / "aws" / "placeholder").write_text("x")
            manifest_path = root / "release.json"
            manifest = self.bind_bundle(self.manifest(), bundle)
            manifest_path.write_text(json.dumps(manifest))
            first = f"repo/image@sha256:{'b' * 64}"
            second = f"repo/image@sha256:{'c' * 64}"
            manager.stage_release(paths, bundle, manifest_path, first)
            with self.assertRaisesRegex(RuntimeError, "image differs"):
                manager.stage_release(paths, bundle, manifest_path, second)

    def test_host_bundle_identity_includes_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            path = bundle / "deploy" / "aws" / "launcher.sh"
            path.parent.mkdir(parents=True)
            path.write_text("#!/bin/sh\n")
            path.chmod(0o644)
            before = manager.host_bundle_files(bundle)
            path.chmod(0o755)
            after = manager.host_bundle_files(bundle)
            self.assertNotEqual(before, after)

    def test_apply_transaction_rehearsal_switches_and_journals_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = manager.Paths(root / "host")
            paths.runtime.mkdir(parents=True)
            paths.state.mkdir(parents=True)
            (paths.runtime / "account.json").write_text(
                json.dumps({
                    "updated_at": time.time() - 1_000,
                    "status": "healthy",
                    "positions": [],
                    "orders": [],
                })
            )
            (paths.runtime / "health.json").write_text(json.dumps({
                "status": "running", "updated_at": time.time(),
                "mode": "hold", "order_gate": "false",
            }))
            (paths.state / "checkpoint.json").write_text("{}")

            bundle = root / "bundle"
            source = SCRIPT.parent
            (bundle / "deploy" / "aws").mkdir(parents=True)
            for name in (
                "algotrade-paper.service",
                "algotrade-dashboard.service",
                "run-container.sh",
                "run-dashboard.sh",
                "render-env.sh",
            ):
                (bundle / "deploy" / "aws" / name).write_bytes((source / name).read_bytes())
            manifest = self.bind_bundle(self.manifest(), bundle)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(manifest))
            image_ref = f"repo/image@sha256:{'b' * 64}"
            args = Namespace(
                manifest=manifest_path,
                image_ref=image_ref,
                bundle=bundle,
                timeout=1,
            )
            with (
                patch.object(manager, "run"),
                patch.object(manager, "stop_services"),
                patch.object(manager, "start_services"),
                patch.object(manager, "image_release", return_value=manifest),
                patch.object(
                    manager,
                    "verify_broker_flat",
                    return_value={"flat": True, "working_orders": 0},
                ),
                patch.object(
                    manager,
                    "wait_for_hold",
                    return_value={"mode": "hold", "order_gate": False},
                ),
            ):
                manager.command_apply(args, paths)

            self.assertEqual(paths.current.resolve().name, "release-1")
            env = manager.parse_release_env(paths.release_env)
            self.assertEqual(env["ALGOTRADE_IMAGE_REF"], image_ref)
            self.assertEqual(env["ALGOTRADE_FORCE_HOLD"], "true")
            safety = json.loads(paths.safety.read_text())
            self.assertEqual(safety["status"], "verified")
            self.assertTrue(safety["flat"])
            self.assertEqual(safety["working_orders"], 0)
            self.assertEqual(safety["release_id"], "release-1")
            self.assertEqual(safety["phase"], "stopped")
            self.assertTrue(any(paths.backups.iterdir()))
            states = [json.loads(line)["state"] for line in paths.journal.read_text().splitlines()]
            self.assertEqual(states, [
                "PREPARING", "BROKER_PREFLIGHT_VERIFIED", "QUIESCING",
                "STOPPED", "BROKER_VERIFIED", "SWITCHED", "VERIFYING",
                "INSTALLED_VERIFIED",
            ])

    def test_stale_or_partial_account_snapshot_blocks_deploy(self) -> None:
        stale = {
            "health_age_s": 1,
            "health_status": "running",
            "account_age_s": 121,
            "account_status": "healthy",
            "flat": True,
            "working_orders": 0,
        }
        with self.assertRaisesRegex(RuntimeError, "no older than 120"):
            manager.assert_quiet(stale)
        partial = {**stale, "account_age_s": 1, "account_status": "partial"}
        with self.assertRaisesRegex(RuntimeError, "complete healthy"):
            manager.assert_quiet(partial)

    def test_malformed_position_is_unknown(self) -> None:
        self.assertIsNone(manager.positions_are_flat({"positions": ["bad-row"]}))
        self.assertIsNone(manager.positions_are_flat({"positions": [{}]}))

    def test_partial_fill_is_still_a_working_order(self) -> None:
        self.assertEqual(
            manager.working_order_count({"orders": [{"status": "Partially filled"}]}),
            1,
        )

    def test_failed_apply_restores_legacy_units_and_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = manager.Paths(root / "host")
            paths.runtime.mkdir(parents=True)
            paths.state.mkdir(parents=True)
            (paths.runtime / "account.json").write_text(json.dumps({
                "updated_at": time.time() - 1_000,
                "status": "healthy",
                "positions": [],
                "orders": [],
            }))
            (paths.runtime / "health.json").write_text(json.dumps({
                "status": "healthy", "updated_at": time.time(),
                "mode": "hold", "order_gate": "false",
            }))
            systemd = paths.root / "etc/systemd/system"
            systemd.mkdir(parents=True)
            for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
                (systemd / name).write_text(f"legacy-{name}")
                dropins = systemd / f"{name}.d"
                dropins.mkdir()
                (dropins / "legacy.conf").write_text(f"override-{name}")

            legacy = paths.install / "legacy"
            (legacy / "deploy/aws").mkdir(parents=True)
            paths.install.mkdir(parents=True, exist_ok=True)
            paths.current.symlink_to(legacy)
            paths.config.mkdir(parents=True)
            paths.release_env.write_text("ALGOTRADE_RELEASE_ID=legacy\n")

            bundle = root / "bundle"
            source = SCRIPT.parent
            (bundle / "deploy" / "aws").mkdir(parents=True)
            for name in (
                "algotrade-paper.service", "algotrade-dashboard.service",
                "run-container.sh", "run-dashboard.sh", "render-env.sh",
            ):
                (bundle / "deploy" / "aws" / name).write_bytes((source / name).read_bytes())
            manifest = self.bind_bundle(self.manifest(), bundle)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(manifest))
            args = Namespace(
                manifest=manifest_path,
                image_ref=f"repo/image@sha256:{'b' * 64}",
                bundle=bundle,
                timeout=1,
            )
            with (
                patch.object(manager, "run"),
                patch.object(manager, "stop_services"),
                patch.object(manager, "start_services"),
                patch.object(manager, "image_release", return_value=manifest),
                patch.object(
                    manager,
                    "verify_broker_flat",
                    return_value={"flat": True, "working_orders": 0},
                ),
                patch.object(
                    manager,
                    "wait_for_hold",
                    side_effect=RuntimeError("candidate failed"),
                ),
                patch.object(manager, "wait_for_runtime", return_value={"status": "running"}),
            ):
                with self.assertRaisesRegex(RuntimeError, "candidate failed"):
                    manager.command_apply(args, paths)

            self.assertEqual(paths.current.resolve(), legacy.resolve())
            self.assertEqual(paths.release_env.read_text(), "ALGOTRADE_RELEASE_ID=legacy\n")
            for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
                self.assertEqual((systemd / name).read_text(), f"legacy-{name}")
                self.assertEqual(
                    (systemd / f"{name}.d" / "legacy.conf").read_text(),
                    f"override-{name}",
                )
            states = [json.loads(line)["state"] for line in paths.journal.read_text().splitlines()]
            self.assertEqual(states[-2:], ["FAILED", "ROLLED_BACK"])

    def test_install_units_removes_legacy_dropins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = manager.Paths(root / "host")
            systemd = paths.root / "etc/systemd/system"
            for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
                dropins = systemd / f"{name}.d"
                dropins.mkdir(parents=True, exist_ok=True)
                (dropins / "legacy.conf").write_text("[Service]\nExecStart=legacy\n")
            target = root / "target"
            source = SCRIPT.parent
            (target / "deploy/aws").mkdir(parents=True)
            for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
                (target / "deploy/aws" / name).write_bytes((source / name).read_bytes())
            with patch.object(manager, "run"):
                manager.install_units(paths, target)
            for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
                self.assertFalse((systemd / f"{name}.d").exists())

    def test_manual_rollback_switches_to_saved_release_in_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = manager.Paths(root / "host")
            paths.runtime.mkdir(parents=True)
            paths.state.mkdir(parents=True)
            (paths.runtime / "account.json").write_text(json.dumps({
                "updated_at": time.time() - 1_000,
                "status": "healthy",
                "positions": [],
                "orders": [],
            }))
            (paths.runtime / "health.json").write_text(json.dumps({
                "status": "healthy", "updated_at": time.time(),
                "mode": "hold", "order_gate": "false",
            }))
            target = paths.releases / "release-1"
            (target / "deploy/aws").mkdir(parents=True)
            source = SCRIPT.parent
            for name in ("algotrade-paper.service", "algotrade-dashboard.service"):
                (target / "deploy" / "aws" / name).write_bytes((source / name).read_bytes())
            manifest = self.manifest()
            (target / "release.json").write_text(json.dumps(manifest))
            image_ref = f"repo/image@sha256:{'b' * 64}"
            (target / "release.env").write_text(
                manager.release_env("release-1", image_ref)
            )
            current = paths.releases / "release-2"
            current.mkdir(parents=True)
            paths.install.mkdir(parents=True, exist_ok=True)
            paths.current.symlink_to(current)

            args = Namespace(release_id="release-1", timeout=1)
            with (
                patch.object(manager, "run"),
                patch.object(manager, "stop_services"),
                patch.object(manager, "start_services"),
                patch.object(
                    manager,
                    "verify_broker_flat",
                    return_value={"flat": True, "working_orders": 0},
                ),
                patch.object(
                    manager,
                    "wait_for_hold",
                    return_value={"mode": "hold", "order_gate": False},
                ),
            ):
                manager.command_rollback(args, paths)

            self.assertEqual(paths.current.resolve(), target.resolve())
            env = manager.parse_release_env(paths.release_env)
            self.assertEqual(env["ALGOTRADE_RELEASE_ID"], "release-1")
            self.assertEqual(env["ALGOTRADE_FORCE_HOLD"], "true")
            safety = json.loads(paths.safety.read_text())
            self.assertEqual(safety["release_id"], "release-1")
            self.assertEqual(safety["phase"], "stopped")
            states = [json.loads(line)["state"] for line in paths.journal.read_text().splitlines()]
            self.assertIn("BROKER_PREFLIGHT_VERIFIED", states)


if __name__ == "__main__":
    unittest.main()

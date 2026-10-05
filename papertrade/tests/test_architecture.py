from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


class ArchitectureDependencyTests(unittest.TestCase):
    def test_pure_strategy_does_not_import_runtime_or_infrastructure(self) -> None:
        pure_files = [
            ROOT / "alphas/master_unified/bar_aggregator.py",
            ROOT / "alphas/master_unified/hybrid_engine.py",
            ROOT / "alphas/master_unified/schedule.py",
            ROOT / "alphas/master_unified/signal_composer.py",
            *sorted((ROOT / "luna_core").glob("*.py")),
        ]
        forbidden = {
            "algotrade_adapter",
            "asyncio",
            "docker",
            "kafka",
            "os",
            "paperbroker",
            "requests",
            "runtime_core",
            "socket",
            "subprocess",
        }
        violations = {
            str(path.relative_to(ROOT)): sorted(imported_roots(path) & forbidden)
            for path in pure_files
            if imported_roots(path) & forbidden
        }
        self.assertEqual(violations, {})

    def test_runtime_core_is_sdk_independent(self) -> None:
        forbidden = {"algotrade_adapter", "alphas", "paperbroker"}
        violations = {
            path.name: sorted(imported_roots(path) & forbidden)
            for path in sorted((ROOT / "runtime_core").glob("*.py"))
            if imported_roots(path) & forbidden
        }
        self.assertEqual(violations, {})

    def test_adapter_does_not_depend_on_strategy_packages(self) -> None:
        # market_schedule.py is an explicit compatibility facade while callers
        # migrate to alphas.market_schedule; it contains no implementation.
        violations = {
            path.name: sorted(imported_roots(path) & {"alphas", "luna_core"})
            for path in sorted((ROOT / "algotrade_adapter").glob("*.py"))
            if path.name != "market_schedule.py"
            if imported_roots(path) & {"alphas", "luna_core"}
        }
        self.assertEqual(violations, {})


if __name__ == "__main__":
    unittest.main()

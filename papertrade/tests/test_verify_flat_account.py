from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_flat_account.py"
SPEC = importlib.util.spec_from_file_location("papertrade_verify_flat", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class VerifyFlatAccountTests(unittest.TestCase):
    def test_flat_and_terminal_orders_are_verified(self) -> None:
        portfolio = {"success": True, "items": [{"quantity": 0}]}
        orders = {
            "success": True,
            "items": [
                {"ordStatus": "2"},
                {"statusText": "Order was fully filled"},
                {"status": "CANCELED"},
                {"status": "Order was canceled successfully"},
            ],
        }
        self.assertEqual(probe.verified_counts(portfolio, orders), (0, 0))

    def test_nonflat_and_working_orders_are_counted(self) -> None:
        portfolio = {"success": True, "items": [{"quantity": -2}]}
        orders = {"success": True, "items": [{"ordStatus": "0"}]}
        self.assertEqual(probe.verified_counts(portfolio, orders), (1, 1))

    def test_unknown_broker_response_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "portfolio_unavailable"):
            probe.verified_counts({}, {"success": True, "items": []})
        with self.assertRaisesRegex(RuntimeError, "position_quantity_unknown"):
            probe.verified_counts(
                {"success": True, "items": [{}]},
                {"success": True, "items": []},
            )


if __name__ == "__main__":
    unittest.main()

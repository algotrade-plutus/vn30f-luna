from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algotrade_adapter.account_snapshot import AccountSnapshotExporter  # noqa: E402


class FakeReader:
    def get_cash_balance(self):
        return {"fixAccountID": "do-not-export", "remainCash": 499_340_000}

    def get_account_balance(self):
        return {"subAccountID": "main", "totalBalance": 499_340_000}

    def get_portfolio_by_sub(self):
        return {
            "success": True,
            "derivativeMargin": 0.25,
            "equityMargin": 1,
            "password": "do-not-export",
            "items": [{
                "instrument": "HNXDS:VN30F2609",
                "quantity": 7,
                "avgPrice": 1940.1,
                "currentPrice": 1942.0,
                "pnl": 1_330_000,
                "secret": "do-not-export",
            }],
        }

    def get_orders(self, start, end):
        return {"success": True, "items": [{
            "orderId": "order-1",
            "clOrdId": "client-1",
            "symbol": "VN30F2609",
            "side": "1",
            "orderQty": 7,
            "cumQty": 7,
            "avgPx": 1940.1,
            "statusText": "Filled",
            "token": "do-not-export",
        }]}

    def get_transactions_by_date(self, start, end):
        return {"success": True, "items": [{
            "orderId": "order-1",
            "symbol": "VN30F2609",
            "type": "BUY",
            "quantity": 7,
            "price": 1940.1,
            "totalFee": 140_000,
        }]}

    def get_max_placeable(self, symbol, price, side):
        return {
            "success": True,
            "maxQty": 3,
            "perUnitCost": 48_502_500,
            "remainCash": 159_822_500,
            "fixAccountID": "do-not-export",
        }


class AccountSnapshotTests(unittest.TestCase):
    def test_export_is_atomic_and_strictly_whitelisted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "account.json"
            snapshot = AccountSnapshotExporter(FakeReader(), path).collect(
                symbol="HNXDS:VN30F2609",
                latest_price=1942.0,
                target_qty=7,
            )
            self.assertEqual(snapshot["status"], "healthy")
            self.assertEqual(snapshot["account"]["derivative_margin_ratio"], 0.25)
            self.assertEqual(snapshot["positions"][0]["quantity"], 7)
            self.assertEqual(snapshot["orders"][0]["side"], "BUY")
            self.assertEqual(snapshot["risk"]["max_buy_qty"], 3)
            self.assertEqual(json.loads(path.read_text()), snapshot)
            serialized = path.read_text()
            self.assertNotIn("do-not-export", serialized)
            self.assertNotIn("password", serialized)
            self.assertNotIn("token", serialized)
            self.assertNotIn("fixAccountID", serialized)

    def test_partial_snapshot_does_not_expose_exception_text(self):
        class BrokenReader(FakeReader):
            def get_orders(self, start, end):
                raise RuntimeError("credential-like internal detail")

        with tempfile.TemporaryDirectory() as temp:
            snapshot = AccountSnapshotExporter(
                BrokenReader(), Path(temp) / "account.json"
            ).collect(symbol="HNXDS:VN30F2609", latest_price=None, target_qty=7)
            self.assertEqual(snapshot["status"], "partial")
            self.assertIn("orders_unavailable", snapshot["errors"])
            self.assertNotIn("credential-like", json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()

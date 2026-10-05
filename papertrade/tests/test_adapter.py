from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algotrade_adapter.client import (  # noqa: E402
    OrderBlockedError,
    ValidatedPaperClient,
    _patch_fix_logon_injection,
)


class FakeRaw:
    def place_order(self, **kwargs):
        return kwargs


class AdapterValidationTests(unittest.TestCase):
    def test_order_gate_is_closed_by_default(self):
        client = ValidatedPaperClient(FakeRaw())
        with self.assertRaises(OrderBlockedError):
            client.place_order("HNXDS:VN30F2609", "BUY", 1, 1000.0)

    def test_runtime_authorizer_is_checked_for_every_order(self):
        allowed = [True]
        client = ValidatedPaperClient(
            FakeRaw(), allow_orders=True, submit_authorizer=lambda: allowed[0]
        )
        client.place_order("HNXDS:VN30F2609", "BUY", 1, 1000.0)
        allowed[0] = False
        with self.assertRaises(OrderBlockedError):
            client.place_order("HNXDS:VN30F2609", "BUY", 1, 1000.0)

    def test_unknown_order_type_is_rejected_before_upstream_silent_market_map(self):
        client = ValidatedPaperClient(FakeRaw(), allow_orders=True)
        with self.assertRaises(ValueError):
            client.place_order("HNXDS:VN30F2609", "BUY", 1, 1000.0, ord_type="LO")

    def test_market_still_requires_numeric_reference_price(self):
        client = ValidatedPaperClient(FakeRaw(), allow_orders=True)
        with self.assertRaises(ValueError):
            client.place_order("HNXDS:VN30F2609", "SELL", 1, None, ord_type="MARKET")

    def test_limit_price_is_rounded_to_tick_half_up(self):
        client = ValidatedPaperClient(FakeRaw(), allow_orders=True)
        result = client.place_order("HNXDS:VN30F2609", "BUY", 1, 1000.05)
        self.assertEqual(result["price"], 1000.1)
        self.assertEqual(result["tif"], "DAY")


class FixLogonPatchTests(unittest.TestCase):
    def test_logon_contains_password_tag_without_exposing_value(self):
        try:
            import quickfix as fix
        except ImportError:
            self.skipTest("QuickFIX is not installed")

        class Sub:
            def current(self):
                return "main"

        class Logger:
            def debug(self, *args, **kwargs):
                pass

        class Engine:
            _password = "test-only-password"
            _username = "test-user"
            _sub_provider = Sub()
            logger = Logger()

        class Raw:
            _engine = Engine()

        raw = Raw()
        _patch_fix_logon_injection(raw)
        message = fix.Message()
        message.getHeader().setField(fix.BeginString("FIX.4.4"))
        message.getHeader().setField(fix.MsgType(fix.MsgType_Logon))
        raw._engine._inject_admin_credentials(message, None)
        self.assertTrue(message.isSetField(554))
        self.assertTrue(message.isSetField(553))
        self.assertTrue(message.isSetField(1))


if __name__ == "__main__":
    unittest.main()

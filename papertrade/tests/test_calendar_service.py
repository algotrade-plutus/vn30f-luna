from __future__ import annotations

import os
import sys
import tempfile
import unittest
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paperbroker.alpha import AccountState, AlphaConfig, AlphaContext  # noqa: E402

from alphas.calendar.service import CalendarPaperAlpha, _calendar_qty  # noqa: E402

SYMBOL = "HNXDS:VN30F2609"


class FakeClient:
    def __init__(self, *, allow_orders: bool, positions=None, max_qty=10):
        self.allow_orders = allow_orders
        self.positions = positions or []
        self.max_qty = max_qty
        self.canceled = []
        self.recovered = []
        self.done = set()
        self.cleaned = []

    def get_portfolio_by_sub(self):
        return {"success": True, "items": list(self.positions)}

    def cancel_order(self, cl_ord_id, timeout=3.0):
        self.canceled.append(cl_ord_id)
        return True, "Canceled"

    def is_logged_on(self):
        return True

    def get_max_placeable(self, symbol, price, side):
        return {"success": True, "maxQty": self.max_qty, "unlimited": False}

    def recover_pending_orders(self):
        return list(self.recovered)

    def request_order_status(self, cl_ord_id):
        return True

    def wait_for(self, cl_ord_id, statuses, timeout=3.0):
        return cl_ord_id in self.done

    def is_order_done(self, cl_ord_id):
        return cl_ord_id in self.done

    def cleanup_order(self, cl_ord_id):
        self.cleaned.append(cl_ord_id)


class FakeMarketData:
    pass


def make_context(*, quantity=None):
    positions = {}
    if quantity is not None:
        positions[SYMBOL] = SimpleNamespace(quantity=quantity)
    quote = SimpleNamespace(
        ask_price_1=1948.1,
        bid_price_1=1948.0,
        latest_matched_price=1948.0,
        ceiling_price=2100.0,
        floor_price=1700.0,
    )
    return AlphaContext(
        bars={SYMBOL: deque()},
        quotes={SYMBOL: quote},
        positions=positions,
        open_orders={},
        signals={},
        account=AccountState(),
        now=datetime(2026, 8, 24, 7, 24, tzinfo=timezone.utc),
        triggered_by=[SYMBOL],
    )


class CalendarServiceTests(unittest.TestCase):
    def build_alpha(self, *, allow_orders=True, positions=None, qty=1):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        client = FakeClient(allow_orders=allow_orders, positions=positions)
        config = AlphaConfig.single(
            instrument=SYMBOL,
            sub_account="main",
            timeframe="30m",
            qty=qty,
            params={"cross_points": 0.1, "cancel_after_s": 8, "eval_interval_s": 2},
            state_path=str(Path(temp.name) / "calendar.json"),
        )
        return CalendarPaperAlpha(client=client, market_data=FakeMarketData(), config=config)

    def test_monday_decision_buys_one_for_tuesday(self):
        alpha = self.build_alpha(allow_orders=True)
        ctx = make_context()
        indicators = alpha.get_indicators(ctx)
        signals = alpha.get_signals(indicators, ctx)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].side, "BUY")
        self.assertEqual(signals[0].metadata["qty"], 1)
        self.assertAlmostEqual(alpha.get_entry_price(signals[0], ctx), 1948.2)
        orders = alpha.plan_orders(signals[0], ctx)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].ord_type, "LIMIT")

    def test_monday_decision_can_buy_ten_when_capacity_allows(self):
        alpha = self.build_alpha(allow_orders=True, qty=10)
        ctx = make_context()
        signals = alpha.get_signals(alpha.get_indicators(ctx), ctx)
        self.assertEqual(signals[0].metadata["qty"], 10)
        orders = alpha.plan_orders(signals[0], ctx)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].qty, 10)

    def test_shadow_mode_records_but_does_not_emit(self):
        alpha = self.build_alpha(allow_orders=False)
        ctx = make_context()
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(alpha.get_signals(indicators, ctx), [])
        self.assertIsNotNone(alpha.state_store.get("last_shadow_decision"))

    def test_remote_position_prevents_duplicate_entry_after_restart(self):
        alpha = self.build_alpha(
            allow_orders=True,
            positions=[{"instrument": SYMBOL, "quantity": 1}],
        )
        ctx = make_context()
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(alpha.get_signals(indicators, ctx), [])

    def test_local_remote_drift_blocks_another_order(self):
        alpha = self.build_alpha(allow_orders=True)
        ctx = make_context(quantity=1)
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(alpha.get_signals(indicators, ctx), [])
        self.assertIn("position drift", alpha.health_snapshot()["last_error"])

    def test_foreign_position_blocks_signal(self):
        alpha = self.build_alpha(
            allow_orders=True,
            positions=[{"instrument": "HNXDS:VN30F2610", "quantity": 1}],
        )
        ctx = make_context()
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(alpha.get_signals(indicators, ctx), [])
        self.assertIn("foreign positions", alpha.health_snapshot()["last_error"])

    def test_capacity_check_blocks_order_above_max_placeable(self):
        alpha = self.build_alpha(allow_orders=True)
        alpha.client.max_qty = 0
        ctx = make_context()
        signals = alpha.get_signals(alpha.get_indicators(ctx), ctx)
        self.assertEqual(alpha.plan_orders(signals[0], ctx), [])
        self.assertIn("max placeable", alpha.health_snapshot()["last_error"])

    def test_restart_recovery_cancels_and_cleans_working_order(self):
        alpha = self.build_alpha(allow_orders=True)
        alpha.client.recovered = [{"cl_ord_id": "old-order"}]
        alpha._recover_orders()
        self.assertEqual(alpha.client.canceled, ["old-order"])
        self.assertEqual(alpha.client.cleaned, ["old-order"])

    def test_calendar_qty_accepts_ten_and_rejects_eleven(self):
        with patch.dict(os.environ, {"CALENDAR_QTY": "10"}):
            self.assertEqual(_calendar_qty(), 10)
        with patch.dict(os.environ, {"CALENDAR_QTY": "11"}):
            with self.assertRaises(ValueError):
                _calendar_qty()

    def test_monday_morning_short_when_gap_is_negative(self):
        alpha = self.build_alpha(allow_orders=True, qty=8)
        # 02:20 UTC = 09:20 ICT Monday
        quote = SimpleNamespace(
            reference_price=1950.0,
            open_price=1948.0,
            latest_matched_price=1948.0,
            ask_price_1=1948.1,
            bid_price_1=1948.0,
            ceiling_price=2100.0,
            floor_price=1700.0,
        )
        ctx = AlphaContext(
            bars={SYMBOL: deque()},
            quotes={SYMBOL: quote},
            positions={},
            open_orders={},
            signals={},
            account=AccountState(),
            now=datetime(2026, 8, 24, 2, 20, tzinfo=timezone.utc),
            triggered_by=[SYMBOL],
        )
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(indicators["desired_qty"], -8)
        self.assertEqual(indicators["reasons"], ("monday_short",))
        signals = alpha.get_signals(indicators, ctx)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].side, "SELL")
        self.assertEqual(signals[0].metadata["qty"], 8)

    def test_reversal_from_short_to_long_on_monday_afternoon(self):
        alpha = self.build_alpha(allow_orders=True, qty=8, positions=[{"instrument": SYMBOL, "quantity": -8}])
        # 07:24 UTC = 14:24 ICT Monday afternoon
        ctx = make_context(quantity=-8)
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(indicators["desired_qty"], 8)
        signals = alpha.get_signals(indicators, ctx)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].side, "BUY")
        # delta = 8 - (-8) = 16
        self.assertEqual(signals[0].metadata["qty"], 16)

    def test_negative_position_within_limit_allowed_and_beyond_blocked(self):
        alpha = self.build_alpha(allow_orders=True, qty=8, positions=[{"instrument": SYMBOL, "quantity": -9}])
        ctx = make_context(quantity=-9)
        signals = alpha.get_signals(alpha.get_indicators(ctx), ctx)
        self.assertEqual(signals, [])
        self.assertIn("unexpected", alpha.health_snapshot()["last_error"])


if __name__ == "__main__":
    unittest.main()

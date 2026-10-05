"""Tests for the replacement HybridGated PaperTrade runtime."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paperbroker.alpha import AccountState, AlphaConfig, AlphaContext

from alphas.master_unified.hybrid_engine import Bar30m, HybridSignalEngine
from alphas.master_unified.service import (
    HybridGatedPaperAlpha,
    _hybrid_qty,
    _rest_order_is_terminal,
)

SYMBOL = "HNXDS:VN30F2609"


class FakeClient:
    def __init__(self, *, allow_orders=True, positions=None, max_qty=20):
        self.allow_orders = allow_orders
        self.positions = positions or []
        self.max_qty = max_qty
        self.canceled = []
        self.recovered = []
        self.done = set()
        self.cleaned = []

    def get_portfolio_by_sub(self):
        return {"success": True, "items": list(self.positions)}

    def get_orders(self, start, end):
        return {"success": True, "items": []}

    def cancel_order(self, cl_ord_id, timeout=3.0):
        self.canceled.append(cl_ord_id)
        return True, "Canceled"

    def is_logged_on(self):
        return True

    def connect(self):
        pass

    def wait_until_logged_on(self, timeout=15.0):
        return True

    def last_logon_error(self):
        return ""

    def on(self, event, handler):
        pass

    def off(self, event, handler):
        pass

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
    async def stop(self):
        return None

    async def subscribe(self, symbol, callback):
        return None


def make_context(
    stamp: str,
    *,
    ref=1000.0,
    open_px=1000.0,
    latest=1000.0,
    tracked_quantity=None,
    working=None,
) -> AlphaContext:
    quote = SimpleNamespace(
        reference_price=ref,
        open_price=open_px,
        latest_matched_price=latest,
        bid_price_1=latest - 0.1,
        ask_price_1=latest + 0.1,
        floor_price=800.0,
        ceiling_price=1200.0,
    )
    positions = {}
    if tracked_quantity is not None:
        positions[SYMBOL] = SimpleNamespace(quantity=tracked_quantity)
    return AlphaContext(
        bars={SYMBOL: deque()},
        quotes={SYMBOL: quote},
        positions=positions,
        open_orders={SYMBOL: list(working or [])} if working else {},
        signals={},
        account=AccountState(),
        now=datetime.fromisoformat(stamp),
        triggered_by=[SYMBOL],
    )


def flat_bars(count: int, price: float = 1000.0) -> list[Bar30m]:
    start = datetime(2025, 1, 1, 9, 0)
    return [
        Bar30m(
            (start + timedelta(minutes=30 * i)).isoformat(sep=" "),
            price,
            price,
            price,
            price,
        )
        for i in range(count)
    ]


class HybridSignalEngineTests(unittest.TestCase):
    def test_rest_expired_order_uses_canonical_ord_status(self):
        item = {
            "statusText": "Order expired (IOC/FOK/MTL)",
            "ordStatus": "C",
            "leavesQty": 10,
        }
        self.assertTrue(_rest_order_is_terminal(item))

    def test_t2_lookbacks_and_long_transition(self):
        engine = HybridSignalEngine()
        engine.load(flat_bars(200))
        engine.add_completed_bar(Bar30m("2026-08-24 09:00:00", 1015, 1015, 1015, 1015))
        self.assertAlmostEqual(engine.metrics()["ret_2d"], 0.015)
        self.assertAlmostEqual(engine.metrics()["ret_5d"], 0.015)
        self.assertEqual(engine.t2_state, 1)

    def test_short_requires_200_bar_macro_return(self):
        engine = HybridSignalEngine()
        engine.load(flat_bars(199))
        engine.add_completed_bar(Bar30m("2026-08-24 09:00:00", 980, 980, 980, 980))
        self.assertIsNone(engine.metrics()["ret_20d"])
        self.assertEqual(engine.t2_state, 0)

    def test_gatekeeper_low_dist_ret5_branch(self):
        engine = HybridSignalEngine()
        volatile = [
            Bar30m(bar.datetime, 1000, 1005, 995, 1000)
            for bar in flat_bars(120)
        ]
        engine.load(volatile)
        metrics = engine.metrics(Bar30m("2026-08-24 14:00:00", 1000, 1012, 1000, 1012))
        self.assertLessEqual(metrics["dist_ma120"], 4.77)
        self.assertTrue(metrics["is_fomo"])

    def test_gatekeeper_high_dist_ret2_branch(self):
        engine = HybridSignalEngine()
        engine.load(flat_bars(120))
        metrics = engine.metrics(Bar30m("2026-08-24 14:00:00", 1000, 1001, 1000, 1020))
        self.assertGreater(metrics["dist_ma120"], 4.77)
        self.assertGreater(metrics["ret_2bar"], 0.010)
        self.assertTrue(metrics["is_fomo"])

    def test_completed_bar_is_idempotent(self):
        engine = HybridSignalEngine()
        bar = Bar30m("2026-08-24 09:00:00", 1000, 1001, 999, 1000)
        self.assertTrue(engine.add_completed_bar(bar))
        self.assertFalse(engine.add_completed_bar(bar))


class HybridGatedPaperAlphaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.warmup = self.root / "warmup.json"
        self.warmup.write_text("[]", encoding="utf-8")

    def build_alpha(self, *, allow_orders=True, positions=None, qty=8):
        client = FakeClient(allow_orders=allow_orders, positions=positions)
        config = AlphaConfig.single(
            instrument=SYMBOL,
            sub_account="main",
            timeframe="30m",
            qty=qty,
            params={
                "cancel_after_s": 8.0,
                "cross_points": 0.1,
                "eval_interval_s": 0.0,
                "long_dows": (1, 2),
                "use_month_start": True,
                "use_preholiday": True,
                "use_monday_short": True,
                "use_expiry_thursday": True,
                "monday_max_gap": 0.0,
                "use_fomo_gatekeeper": True,
                "max_ret_5bar": 0.011,
                "max_ret_2bar": 0.010,
                "ma120_threshold": 4.77,
                "gate_ma_window": 120,
                "gate_atr_window": 20,
                "use_t2_momentum": True,
                "t2_fast_bars": 20,
                "t2_slow_bars": 50,
                "t2_macro_bars": 120,
                "t2_macro_trend_bars": 200,
                "t2_long_thresh": 0.008,
                "t2_short_thresh": -0.010,
            },
            state_path=str(self.root / f"state-{id(client)}.json"),
        )
        return HybridGatedPaperAlpha(
            client=client,
            market_data=FakeMarketData(),
            config=config,
            warmup_path=self.warmup,
            seed_warmup_path=self.warmup,
        )

    def test_calendar_target_persists_intraday(self):
        alpha = self.build_alpha()
        first = alpha.get_indicators(make_context("2026-08-25T10:00:00+07:00"))
        second = alpha.get_indicators(make_context("2026-08-25T13:30:00+07:00"))
        self.assertEqual(first["desired_units"], 1)
        self.assertEqual(second["desired_units"], 1)

    def test_regular_monday_short_uses_previous_close(self):
        alpha = self.build_alpha()
        alpha.signal_engine.load([Bar30m("2026-08-21 14:30:00", 1002, 1002, 1002, 1002)])
        ctx = make_context("2026-08-24T09:20:00+07:00", ref=999, open_px=1000)
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(indicators["calendar_target"], -1)
        signals = alpha.get_signals(indicators, ctx)
        self.assertEqual((signals[0].side, signals[0].metadata["qty"]), ("SELL", 8))

    def test_regular_monday_short_vetoed_by_opening_move_surge(self):
        alpha = self.build_alpha()
        alpha.signal_engine.load([Bar30m("2026-08-21 14:30:00", 1002, 1002, 1002, 1002)])
        # ref=1000, open_px=1000 (gap=0), but latest=1002.0 (opening move = +2.0 > 1.5 pts threshold)
        ctx = make_context("2026-08-24T09:20:00+07:00", ref=1000, open_px=1000, latest=1002.0)
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(indicators["calendar_target"], 0)
        self.assertIn("monday_flat_opening_surge", indicators["reasons"])
        signals = alpha.get_signals(indicators, ctx)
        self.assertEqual(len(signals), 0)

    def test_monday_short_vetoed_on_som3(self):
        # 2022-12-05 is Monday, session 2 of Dec (Session #3 of month -> SOM3, must be vetoed)
        alpha = self.build_alpha()
        alpha.signal_engine.load([Bar30m("2022-12-02 14:30:00", 1002, 1002, 1002, 1002)])
        ctx = make_context("2022-12-05T09:20:00+07:00", ref=1000, open_px=1000, latest=1000.0)
        indicators = alpha.get_indicators(ctx)
        self.assertEqual(indicators["calendar_target"], 0)
        self.assertIn("calendar_flat", indicators["reasons"])

    def test_expiry_long_starts_in_morning(self):
        alpha = self.build_alpha()
        indicators = alpha.get_indicators(make_context("2026-09-17T09:20:00+07:00"))
        self.assertEqual(indicators["calendar_target"], 1)
        self.assertIn("expiry_thursday", indicators["reasons"])

    def test_fomo_hard_veto_prevents_t2_refill(self):
        alpha = self.build_alpha()
        alpha.signal_engine.load(flat_bars(200))
        alpha.signal_engine.t2_state = 1
        start = datetime.fromisoformat("2026-08-24T14:00:00+07:00")
        alpha._start_bar(start, 1000, start)
        alpha._update_live_bar(1020, datetime.fromisoformat("2026-08-24T14:24:00+07:00"))
        indicators = alpha.get_indicators(make_context("2026-08-24T14:25:00+07:00", latest=1020))
        self.assertTrue(indicators["calendar_hard_flat"])
        self.assertEqual(indicators["t2_target"], 1)
        self.assertEqual(indicators["desired_units"], 0)
        self.assertIn("gatekeeper_fomo_blocked", indicators["reasons"])

    def test_incomplete_1400_bar_fails_closed(self):
        alpha = self.build_alpha()
        alpha.signal_engine.load(flat_bars(200))
        indicators = alpha.get_indicators(make_context("2026-08-24T14:25:00+07:00"))
        self.assertTrue(indicators["calendar_hard_flat"])
        self.assertIn("gatekeeper_incomplete_1400_bar", indicators["reasons"])

    def test_next_session_skips_exchange_holiday(self):
        alpha = self.build_alpha()
        alpha.signal_engine.load(flat_bars(200))
        start = datetime.fromisoformat("2026-08-28T14:00:00+07:00")
        alpha._start_bar(start, 1000, start)
        indicators = alpha.get_indicators(make_context("2026-08-28T14:25:00+07:00"))
        self.assertEqual(indicators["signal_day"].isoformat(), "2026-09-03")
        self.assertEqual(indicators["calendar_target"], 1)
        self.assertIn("som2", indicators["reasons"])

    def test_working_order_prevents_duplicate(self):
        alpha = self.build_alpha()
        ctx = make_context(
            "2026-08-25T10:00:00+07:00",
            working=[SimpleNamespace(
                placed_at=datetime.fromisoformat("2026-08-25T09:59:59+07:00"),
                cl_ord_id="working",
            )],
        )
        self.assertEqual(alpha.get_signals(alpha.get_indicators(ctx), ctx), [])

    def test_remote_position_prevents_duplicate(self):
        alpha = self.build_alpha(positions=[{"instrument": SYMBOL, "quantity": 8}])
        ctx = make_context("2026-08-25T10:00:00+07:00")
        self.assertEqual(alpha.get_signals(alpha.get_indicators(ctx), ctx), [])

    def test_reversal_flattens_before_opening_opposite_side(self):
        alpha = self.build_alpha(positions=[{"instrument": SYMBOL, "quantity": -8}])
        indicators = {
            "local_now": datetime.fromisoformat("2026-09-07T14:24:00+07:00"),
            "desired_qty": 8,
            "signal_day": datetime.fromisoformat("2026-09-08T00:00:00+07:00").date(),
            "reasons": ("tue_wed",),
            "positions": {SYMBOL: -8},
        }
        close_signal = alpha.get_signals(
            indicators,
            make_context("2026-09-07T14:24:00+07:00", tracked_quantity=-8),
        )[0]
        self.assertEqual((close_signal.side, close_signal.metadata["qty"]), ("BUY", 8))
        self.assertEqual(close_signal.tag, "hybrid_reversal_close")

        indicators["positions"] = {}
        open_signal = alpha.get_signals(
            indicators,
            make_context("2026-09-07T14:25:00+07:00", tracked_quantity=0),
        )[0]
        self.assertEqual((open_signal.side, open_signal.metadata["qty"]), ("BUY", 8))

    def test_capacity_error_remains_visible_until_convergence(self):
        alpha = self.build_alpha()
        alpha._risk_block("max placeable below request")
        alpha._remote_positions = {SYMBOL: -8}
        alpha._desired_qty = 8
        ctx = make_context("2026-09-07T14:24:00+07:00")
        alpha.get_indicators(ctx)
        self.assertEqual(alpha._last_error, "max placeable below request")

    def test_drift_foreign_shadow_and_capacity_fail_closed(self):
        drift = self.build_alpha()
        ctx = make_context("2026-08-25T10:00:00+07:00", tracked_quantity=8)
        self.assertEqual(drift.get_signals(drift.get_indicators(ctx), ctx), [])
        self.assertIn("position drift", drift._last_error)

        foreign = self.build_alpha(positions=[{"instrument": "HNXDS:VN30F2610", "quantity": 1}])
        fctx = make_context("2026-08-25T10:00:00+07:00")
        self.assertEqual(foreign.get_signals(foreign.get_indicators(fctx), fctx), [])
        self.assertIn("foreign positions", foreign._last_error)

        shadow = self.build_alpha(allow_orders=False)
        sctx = make_context("2026-08-25T10:00:00+07:00")
        self.assertEqual(shadow.get_signals(shadow.get_indicators(sctx), sctx), [])
        self.assertIsNotNone(shadow.state_store.get("last_shadow_decision"))

        capacity = self.build_alpha()
        capacity.client.max_qty = 0
        cctx = make_context("2026-08-25T10:00:00+07:00")
        signal = capacity.get_signals(capacity.get_indicators(cctx), cctx)[0]
        self.assertEqual(capacity.plan_orders(signal, cctx), [])
        self.assertIn("max placeable", capacity._last_error)

    def test_quantity_cap(self):
        with patch.dict(os.environ, {"HYBRID_GATED_QTY": "10"}):
            self.assertEqual(_hybrid_qty(), 10)
        with patch.dict(os.environ, {"HYBRID_GATED_QTY": "11"}):
            with self.assertRaises(ValueError):
                _hybrid_qty()

    def test_overnight_position_seeded_on_startup(self):
        alpha = self.build_alpha(positions=[{"instrument": SYMBOL, "quantity": 8}])
        import asyncio
        asyncio.run(alpha.start())
        self.assertIsNotNone(alpha._position_tracker)
        pos = alpha._position_tracker.get(SYMBOL)
        self.assertEqual(pos.quantity, 8.0)

    def test_reversal_reconciles_without_drift_block(self):
        alpha = self.build_alpha(positions=[])
        from paperbroker.execution.position_tracker import PositionTracker
        alpha._position_tracker = PositionTracker()
        alpha._position_tracker.update(SYMBOL, -8.0, 1000.0)
        self.assertEqual(alpha._position_tracker.get(SYMBOL).quantity, -8.0)

        ctx = make_context("2026-08-24T09:20:00+07:00", tracked_quantity=-8.0)
        indicators = {
            "local_now": datetime.fromisoformat("2026-08-24T09:20:00+07:00"),
            "desired_qty": -8,
            "signal_day": datetime.fromisoformat("2026-08-24T00:00:00+07:00").date(),
            "reasons": ("monday_short",),
            "positions": {},
        }
        signals = alpha.get_signals(indicators, ctx)
        self.assertEqual(len(signals), 1)
        self.assertEqual((signals[0].side, signals[0].metadata["qty"]), ("SELL", 8))
        self.assertIsNone(alpha._last_error)
        self.assertEqual(alpha._position_tracker.get(SYMBOL).quantity, 0.0)

    def test_gatekeeper_does_not_block_next_day(self):
        alpha = self.build_alpha()
        alpha.composer.calendar_target = 1
        alpha.composer.use_fomo_gatekeeper = True
        alpha.composer.last_afternoon_decision_day = None

        now = datetime.fromisoformat("2026-09-08T14:24:00+07:00")
        alpha.composer.apply_afternoon_decision(now, alpha.bar_aggregator, SYMBOL)

        self.assertEqual(alpha.composer.calendar_target, 0)
        self.assertTrue(alpha.composer.calendar_hard_flat)
        self.assertEqual(alpha.composer.calendar_reasons, ("gatekeeper_incomplete_1400_bar",))

        next_day = datetime.fromisoformat("2026-09-09T00:00:00+07:00").date()
        self.assertNotEqual(alpha.composer.blocked_execution_day, next_day)
        self.assertIsNone(alpha.composer.blocked_execution_day)

    def test_drift_blocks_when_orders_are_working(self):
        alpha = self.build_alpha(positions=[])
        from paperbroker.execution.position_tracker import PositionTracker
        alpha._position_tracker = PositionTracker()
        alpha._position_tracker.update(SYMBOL, -8.0, 1000.0)

        ctx = make_context(
            "2026-08-24T09:20:00+07:00",
            tracked_quantity=-8.0,
            working=[SimpleNamespace(placed_at=datetime.now(timezone.utc))],
        )
        indicators = {
            "local_now": datetime.fromisoformat("2026-08-24T09:20:00+07:00"),
            "desired_qty": -8,
            "signal_day": datetime.fromisoformat("2026-08-24T00:00:00+07:00").date(),
            "reasons": ("monday_short",),
            "positions": {},
        }
        # While orders are working in-flight, it must not emit new signals or reconcile
        signals = alpha.get_signals(indicators, ctx)
        self.assertEqual(signals, [])
        # Tracker remains unchanged until orders settle
        self.assertEqual(alpha._position_tracker.get(SYMBOL).quantity, -8.0)


if __name__ == "__main__":
    unittest.main()

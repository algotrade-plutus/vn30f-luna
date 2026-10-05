from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alphas.calendar.schedule import (  # noqa: E402
    contract_expiry,
    decision_target,
    front_month_symbol,
    in_decision_window,
    in_monday_decision_window,
    is_pre_holiday,
    is_regular_monday,
    monday_short_target,
    next_decision_plan,
    target_reasons,
    third_thursday,
)

HCM = ZoneInfo("Asia/Ho_Chi_Minh")


class CalendarScheduleTests(unittest.TestCase):
    def test_runtime_schedule_known_2026_sessions(self):
        self.assertEqual(target_reasons(date(2026, 8, 25)), ("tue_wed",))
        self.assertIn("pre_holiday", target_reasons(date(2026, 4, 29)))
        self.assertEqual(target_reasons(date(2026, 9, 2)), ())
        self.assertTrue(is_pre_holiday(date(2026, 4, 29)))

    def test_first_two_weekdays_match_original_calendar_semantics(self):
        self.assertIn("som2", target_reasons(date(2025, 1, 2)))
        self.assertNotIn("som2", target_reasons(date(2025, 1, 3)))

    def test_front_month_rolls_after_expiry_session(self):
        before = datetime(2026, 9, 17, 14, 59, tzinfo=HCM)
        after = datetime(2026, 9, 17, 15, 0, tzinfo=HCM)
        self.assertEqual(third_thursday(2026, 9), date(2026, 9, 17))
        self.assertEqual(front_month_symbol(before), "HNXDS:VN30F2609")
        self.assertEqual(front_month_symbol(after), "HNXDS:VN30F2610")
        self.assertEqual(contract_expiry("HNXDS:VN30F2609"), date(2026, 9, 17))

    def test_year_boundary_rollover(self):
        now = datetime(2026, 12, 18, 10, 0, tzinfo=HCM)
        self.assertEqual(front_month_symbol(now), "HNXDS:VN30F2701")

    def test_expiry_decision_forces_flat(self):
        now = datetime(2026, 9, 17, 14, 24, tzinfo=HCM)
        qty, signal_day, reasons = decision_target(now, "HNXDS:VN30F2609")
        self.assertEqual(qty, 0)
        self.assertEqual(signal_day, date(2026, 9, 18))
        self.assertEqual(reasons, ("expiry_flatten",))

    def test_decision_window_is_narrow_and_pre_atc(self):
        self.assertTrue(in_decision_window(datetime(2026, 8, 24, 14, 24, tzinfo=HCM)))
        self.assertFalse(in_decision_window(datetime(2026, 8, 24, 14, 30, tzinfo=HCM)))

    def test_next_decision_plan_describes_monday_entry(self):
        decision_at, qty, signal_day, reasons = next_decision_plan(
            datetime(2026, 8, 24, 10, 0, tzinfo=HCM),
            "HNXDS:VN30F2609",
        )
        self.assertEqual(decision_at, datetime(2026, 8, 24, 14, 24, tzinfo=HCM))
        self.assertEqual(qty, 1)
        self.assertEqual(signal_day, date(2026, 8, 25))
        self.assertEqual(reasons, ("tue_wed",))

    def test_next_decision_plan_skips_to_next_trading_session(self):
        decision_at, _, _, _ = next_decision_plan(
            datetime(2026, 8, 28, 15, 0, tzinfo=HCM),
            "HNXDS:VN30F2608",
        )
        self.assertEqual(decision_at, datetime(2026, 9, 3, 14, 24, tzinfo=HCM))

    def test_expiry_thursday_long_signal_on_wednesday(self):
        # Wednesday before third Thursday (e.g. 2026-09-16)
        reasons = target_reasons(date(2026, 9, 17))
        self.assertIn("expiry_thursday", reasons)

    def test_regular_monday_logic(self):
        # 2026-08-24 is 4th Monday of August -> regular Monday
        self.assertTrue(is_regular_monday(date(2026, 8, 24)))
        # 2026-08-03 is 1st Monday -> SOM2, not regular Monday
        self.assertFalse(is_regular_monday(date(2026, 8, 3)))
        # Tuesday is not Monday
        self.assertFalse(is_regular_monday(date(2026, 8, 25)))

    def test_monday_decision_window(self):
        self.assertTrue(in_monday_decision_window(datetime(2026, 8, 24, 9, 20, tzinfo=HCM)))
        self.assertFalse(in_monday_decision_window(datetime(2026, 8, 24, 9, 10, tzinfo=HCM)))
        self.assertFalse(in_monday_decision_window(datetime(2026, 8, 24, 9, 35, tzinfo=HCM)))
        # Not Monday
        self.assertFalse(in_monday_decision_window(datetime(2026, 8, 25, 9, 20, tzinfo=HCM)))

    def test_monday_short_target(self):
        self.assertEqual(monday_short_target(-0.5), -1)
        self.assertEqual(monday_short_target(0.0), -1)
        self.assertEqual(monday_short_target(0.1), 0)


if __name__ == "__main__":
    unittest.main()

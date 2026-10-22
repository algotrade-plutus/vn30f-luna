from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd

from src.adapters.strategies.calendar_mtw_signal_source import (
    CalendarMtwParams,
    add_ib_low,
    calendar_mtw_stream,
    drop_atc,
    midweek_legs,
    monday_legs,
)
from src.lab.backtest import validate_position_stream

# Fri 8 Mar - Thu 14 Mar 2019: no holidays.
FRI, MON, TUE, WED, THU = date(2019, 3, 8), date(2019, 3, 11), date(2019, 3, 12), date(2019, 3, 13), date(2019, 3, 14)
SLOTS = [
    (datetime.combine(date.min, start) + timedelta(minutes=10 * i)).time()
    for start, count in ((time(9, 0), 15), (time(13, 0), 9))
    for i in range(count)
]


def ts(day: date, hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {hhmm}")


def make_bars(days=(FRI, MON, TUE, WED, THU), close: float = 1000.0) -> pd.DataFrame:
    rows = [
        {"Datetime": datetime.combine(d, t), "Open": close, "High": close + 1, "Low": close - 1,
         "Close": close, "Volume": 100.0}
        for d in days for t in SLOTS
    ]
    return pd.DataFrame(rows)


def set_close(bars: pd.DataFrame, stamp: pd.Timestamp, close: float) -> None:
    row = bars["Datetime"] == stamp
    bars.loc[row, ["Open", "Close"]] = close
    bars.loc[row, "High"] = close + 1
    bars.loc[row, "Low"] = close - 1


def drop(bars: pd.DataFrame, *stamps: pd.Timestamp) -> pd.DataFrame:
    return bars[~bars["Datetime"].isin(stamps)].reset_index(drop=True)


def monday_of(bars: pd.DataFrame, params: CalendarMtwParams = CalendarMtwParams()):
    return monday_legs(add_ib_low(bars, params), params)


def midweek_of(bars: pd.DataFrame, params: CalendarMtwParams = CalendarMtwParams()):
    return midweek_legs(add_ib_low(bars, params), params)


def test_monday_shorts_first_close_below_ib_low_regardless_of_gap():
    bars = make_bars()
    bars.loc[bars["Datetime"] == ts(MON, "09:00"), ["Open", "High"]] = 1000.5
    set_close(bars, ts(MON, "10:00"), 998.0)
    set_close(bars, ts(MON, "11:00"), 990.0)
    legs, _ = monday_of(bars)
    assert [(leg.side, leg.entry, leg.exit_target) for leg in legs] == [(-1, ts(MON, "10:00"), ts(MON, "14:20"))]


def test_monday_window_ends_at_1300():
    bars = make_bars()
    set_close(bars, ts(MON, "13:10"), 990.0)
    assert monday_of(bars)[0] == []
    legs, _ = monday_of(bars, CalendarMtwParams(monday_window_end=time(13, 30)))
    assert [leg.entry for leg in legs] == [ts(MON, "13:10")]


def test_ib_bars_set_ib_and_window_start():
    bars = make_bars()
    set_close(bars, ts(MON, "09:30"), 990.0)
    assert [leg.entry for leg in monday_of(bars)[0]] == [ts(MON, "09:30")]
    params = CalendarMtwParams(ib_bars=4)
    assert monday_of(bars, params)[0] == []
    set_close(bars, ts(MON, "09:40"), 980.0)
    assert [leg.entry for leg in monday_of(bars, params)[0]] == [ts(MON, "09:40")]


def test_monday_skipped_when_an_ib_bar_is_missing():
    bars = drop(make_bars(), ts(MON, "09:10"))
    set_close(bars, ts(MON, "10:00"), 990.0)
    legs, skips = monday_of(bars)
    assert legs == [] and skips[0].reason == "IB bars missing"


def test_midweek_long_from_monday_1420_to_thursday_1000():
    legs, _ = midweek_of(make_bars())
    assert [(leg.side, leg.entry, leg.exit_target) for leg in legs] == [(1, ts(MON, "14:20"), ts(THU, "10:00"))]


def test_midweek_enters_friday_when_monday_is_a_holiday():
    days = (date(2019, 8, 30), date(2019, 9, 3), date(2019, 9, 4), date(2019, 9, 5))
    legs, _ = midweek_of(make_bars(days))
    assert [(leg.entry, leg.exit_target) for leg in legs] == [(ts(days[0], "14:20"), ts(days[3], "10:00"))]


def test_midweek_skipped_when_wednesday_is_a_holiday():
    days = (date(2020, 8, 31), date(2020, 9, 1), date(2020, 9, 3))
    legs, skips = midweek_of(make_bars(days))
    assert legs == [] and skips[0].reason == "Wednesday is a holiday"


def test_missing_exit_bar_moves_exit_to_next_bar():
    bars = drop(make_bars(), ts(THU, "10:00"))
    _, table, _ = calendar_mtw_stream(bars)
    assert table.loc[0, "Exit"] == ts(THU, "10:10")


def test_long_entered_while_short_open_nets_to_flat():
    bars = make_bars()
    set_close(bars, ts(MON, "10:00"), 990.0)
    stream, table, _ = calendar_mtw_stream(bars, CalendarMtwParams(w0_entry=time(13, 30)))
    position = stream.set_index("Datetime")["Position"]
    assert position[ts(MON, "13:20")] == -1.0
    assert position[ts(MON, "13:30")] == 0.0
    assert position[ts(MON, "14:20")] == 1.0
    assert list(table["Leg"]) == ["M3", "W0X1"]
    validate_position_stream(stream)


def test_overlapping_longs_hold_one_contract():
    # 30/04 and 01/05/2020 are holidays, so the week-1 exit lands on Monday 04/05.
    days = [date(2020, 4, d) for d in (27, 28, 29)] + [date(2020, 5, d) for d in (4, 5, 6, 7)]
    params = CalendarMtwParams(w0_entry=time(13, 0), x1_exit=time(13, 10))
    stream, table, _ = calendar_mtw_stream(make_bars(days), params)
    assert len(table) == 2 and stream["Position"].max() == 1.0
    held = stream.set_index("Datetime")["Position"]
    assert held[ts(date(2020, 5, 4), "13:00")] == 1.0 and held[ts(date(2020, 5, 4), "13:10")] == 1.0
    validate_position_stream(stream)


def test_drop_atc_removes_the_1445_bar():
    bars = make_bars(days=(MON,))
    atc = bars.iloc[[-1]].assign(Datetime=ts(MON, "14:45"))
    kept = drop_atc(pd.concat([bars, atc], ignore_index=True))
    assert kept["Datetime"].max() == ts(MON, "14:20") and len(kept) == len(bars)

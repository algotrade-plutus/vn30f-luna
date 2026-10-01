"""Unit and integration tests for Clean Architecture components.
Verifies pure domain separation, entity invariants, calendar rules, FOMO veto, and risk monitor.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import subprocess
import sys

import pytest

from src.domain.entities.bar import Bar
from src.domain.entities.fill import Fill
from src.domain.entities.margin import MarginAccount, MarginCallStatus
from src.domain.entities.order import Order, OrderStatus, OrderType, Side
from src.domain.entities.position import Position
from src.domain.strategy.calendar_rules import (
    business_day_index_in_month,
    is_calendar_long_day,
    is_expiry_thursday,
    is_pre_holiday,
    is_regular_monday,
    is_start_of_month,
    is_trading_day,
    next_trading_day,
)
from src.domain.strategy.fomo_gatekeeper import FomoGatekeeper
from src.domain.strategy.luna_strategy import LunaParameters, LunaStrategy
from src.domain.strategy.t2_momentum import T2MomentumEngine
from src.application.ports.broker_port import IBrokerGateway
from src.application.use_cases.risk_monitor import RiskMonitorUseCase
from src.application.use_cases.trading_cycle import TradingCycleUseCase


def test_domain_layer_has_zero_external_dependencies():
    """Verify that importing domain layer does not load pandas, numpy, psycopg2, or socket."""
    code = """
import sys
import src.domain.entities
import src.domain.strategy

forbidden = {'pandas', 'numpy', 'scipy', 'psycopg2', 'quickfix', 'socket', 'requests'}
loaded = set(sys.modules.keys()) & forbidden
assert not loaded, f"Forbidden external libraries imported in domain layer: {loaded}"
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_position_apply_fill_pnl():
    """Verify position PnL calculations for open, add, close, and reversal."""
    pos = Position(symbol="VN30F2608")
    assert pos.is_flat

    # 1. Buy 2 contracts @ 1900.0
    fill1 = Fill(
        order_id="o1",
        symbol="VN30F2608",
        side=Side.BUY,
        quantity=2,
        price=Decimal("1900.0"),
        timestamp=datetime(2026, 8, 3, 9, 30),
    )
    closed, pnl = pos.apply_fill(fill1)
    assert closed == 0
    assert pnl == 0
    assert pos.net_quantity == 2
    assert pos.average_price == Decimal("1900.0")

    # 2. Sell 1 contract @ 1920.0 (+20 points gain on 1 contract = +2,000,000 VND)
    fill2 = Fill(
        order_id="o2",
        symbol="VN30F2608",
        side=Side.SELL,
        quantity=1,
        price=Decimal("1920.0"),
        timestamp=datetime(2026, 8, 3, 11, 0),
    )
    closed, pnl = pos.apply_fill(fill2)
    assert closed == 1
    assert pnl == Decimal("2000000.0")
    assert pos.net_quantity == 1
    assert pos.average_price == Decimal("1900.0")
    assert pos.realized_pnl == Decimal("2000000.0")

    # 3. Sell 2 contracts @ 1910.0 (Closes 1 long @ +10 pts, reverses to 1 short @ 1910.0)
    fill3 = Fill(
        order_id="o3",
        symbol="VN30F2608",
        side=Side.SELL,
        quantity=2,
        price=Decimal("1910.0"),
        timestamp=datetime(2026, 8, 3, 14, 0),
    )
    closed, pnl = pos.apply_fill(fill3)
    assert closed == 1
    assert pnl == Decimal("1000000.0")
    assert pos.net_quantity == -1
    assert pos.average_price == Decimal("1910.0")
    assert pos.realized_pnl == Decimal("3000000.0")


def test_margin_account_status_transitions():
    """Verify margin utilisation triggers Warning (80%), Call (90%), and Forced (100%)."""
    account = MarginAccount.create(initial_capital=Decimal("100000000"), im_rate=Decimal("0.17"))
    settlement_price = Decimal("1900.0")
    multiplier = Decimal("100000")

    # 1 contract: notional = 190,000,000 -> IM = 32,300,000 -> ratio = 32.3% (NORMAL)
    snap1 = account.calculate_status(net_quantity=1, settlement_price=settlement_price)
    assert snap1.status == MarginCallStatus.NORMAL
    assert snap1.utilisation_ratio < Decimal("0.50")

    # 2 contracts: IM = 64,600,000 -> ratio = 64.6% (NORMAL)
    snap2 = account.calculate_status(net_quantity=2, settlement_price=settlement_price)
    assert snap2.status == MarginCallStatus.NORMAL

    # Large adverse variation margin loss (-25,000,000 VND) on 2 contracts
    # available collateral = 100M - 25M = 75M -> ratio = 64.6M / 75M = ~86.1% (WARNING)
    snap3 = account.calculate_status(
        net_quantity=2,
        settlement_price=settlement_price,
        daily_variation_margin=Decimal("-25000000"),
    )
    assert snap3.status == MarginCallStatus.WARNING

    # Adverse variation margin loss (-30,000,000 VND)
    # available collateral = 70M -> ratio = 64.6M / 70M = ~92.3% (CALL)
    snap4 = account.calculate_status(
        net_quantity=2,
        settlement_price=settlement_price,
        daily_variation_margin=Decimal("-30000000"),
    )
    assert snap4.status == MarginCallStatus.CALL

    # Extreme variation margin loss (-40,000,000 VND)
    # available collateral = 60M -> ratio = 64.6M / 60M = ~107.7% (FORCED)
    snap5 = account.calculate_status(
        net_quantity=2,
        settlement_price=settlement_price,
        daily_variation_margin=Decimal("-40000000"),
    )
    assert snap5.status == MarginCallStatus.FORCED


def test_calendar_rules_august_2026():
    """Verify specific calendar dates in August 2026."""
    # 2026-08-03 is Monday (First trading day of month -> SOM2 Day 0)
    d_aug3 = date(2026, 8, 3)
    assert is_trading_day(d_aug3)
    assert is_start_of_month(d_aug3)
    assert not is_regular_monday(d_aug3)  # Blocked by SOM2!
    assert is_calendar_long_day(d_aug3)

    # 2026-08-04 is Tuesday (Tue/Wed Long + SOM2 Day 1)
    d_aug4 = date(2026, 8, 4)
    assert is_start_of_month(d_aug4)
    assert is_calendar_long_day(d_aug4)

    # 2026-08-10 is regular Monday (dow=0, not SOM2, not holiday)
    d_aug10 = date(2026, 8, 10)
    assert is_regular_monday(d_aug10)

    # 2026-08-20 is 3rd Thursday (Expiry Thursday of VN30F2608)
    d_aug20 = date(2026, 8, 20)
    assert is_expiry_thursday(d_aug20)

    # 2026-08-28 is Friday before National Day holidays (Pre-holiday!)
    # 2026-08-31, 09-01, 09-02 are holidays
    d_aug28 = date(2026, 8, 28)
    assert is_pre_holiday(d_aug28)
    assert is_calendar_long_day(d_aug28)


def test_expiry_day_is_not_an_alpha_signal_by_default():
    strategy = LunaStrategy()
    strategy.t2_engine.update = lambda bar: 0
    bar = Bar(
        symbol="VN30F2608",
        timestamp=datetime(2026, 8, 20, 10, 0),
        open=Decimal("1900"),
        high=Decimal("1901"),
        low=Decimal("1899"),
        close=Decimal("1900"),
        volume=100,
    )

    target, reason = strategy.on_bar(bar)

    assert target == 0
    assert reason == "neutral_flat"


def test_fomo_gatekeeper_veto():
    """Verify FOMO gatekeeper detects overbought pumps."""
    gate = FomoGatekeeper()
    # Feed 125 flat bars @ 100.0
    for i in range(125):
        dt = datetime(2026, 8, 3, 9, 30)
        bar = Bar(symbol="VN30F", timestamp=dt, open=Decimal("100"), high=Decimal("100.5"), low=Decimal("99.5"), close=Decimal("100"), volume=10)
        is_fomo = gate.update(bar)
        assert not is_fomo

    # Rapid pump +3.0 points (> 2% return) in 1 bar
    pump_bar = Bar(symbol="VN30F", timestamp=datetime(2026, 8, 3, 14, 0), open=Decimal("100"), high=Decimal("103.5"), low=Decimal("100"), close=Decimal("103.0"), volume=50)
    is_fomo = gate.update(pump_bar)
    assert is_fomo


def test_fomo_veto_cannot_fall_through_to_t2_long():
    strategy = LunaStrategy()
    blocked_day = date(2026, 8, 4)
    strategy.blocked_execution_dates.add(blocked_day)
    strategy.t2_engine.update = lambda bar: 1
    bar = Bar(
        symbol="VN30F2608",
        timestamp=datetime(2026, 8, 4, 10, 0),
        open=Decimal("1900"),
        high=Decimal("1901"),
        low=Decimal("1899"),
        close=Decimal("1900"),
        volume=100,
    )

    target, reason = strategy.on_bar(bar)

    assert target == 0
    assert reason == "calendar_long_blocked_by_fomo"


def test_risk_monitor_use_case_blocks_when_call():
    """Mock broker returning a Margin Call and assert RiskMonitorUseCase rejects new trades."""
    class MockBroker(IBrokerGateway):
        def submit_order(self, order): return True, "ACCEPTED"
        def cancel_order(self, order_id): return True
        def get_position(self, symbol): return Position(symbol=symbol)
        def get_fills(self): return []
        def advance_to(self, ts): return []
        def get_margin(self):
            return MarginAccount.create(Decimal("100000000")).calculate_status(
                net_quantity=3,
                settlement_price=Decimal("1900.0"),
                daily_variation_margin=Decimal("-20000000"),
            )

    broker = MockBroker()
    monitor = RiskMonitorUseCase(broker=broker, max_allowed_utilisation=0.80)
    verdict = monitor.evaluate()
    assert not verdict.can_trade
    assert "exceeds safety threshold" in verdict.message or verdict.status != MarginCallStatus.NORMAL


@pytest.mark.parametrize(
    "state,fast,slow,macro,price,expected,reason",
    [
        (0, 0.009, 0.01, None, 101, 1, "t2_momentum_long_entry"),
        (0, -0.011, -0.01, -0.01, 99, -1, "t2_momentum_short_entry"),
        (0, 0.008, 0.01, 0.01, 101, 0, ""),
        (0, -0.010, -0.01, -0.01, 99, 0, ""),
        (0, -0.011, -0.01, None, 99, 0, ""),
        (1, -0.1, -0.1, -0.1, 90, 0, "t2_long_momentum_exhausted"),
        (-1, 0.1, 0.1, 0.1, 110, 0, "t2_short_momentum_exhausted"),
        (1, 0, 0, 0, 100, 1, "t2_hold_long"),
        (-1, 0, 0, 0, 100, -1, "t2_hold_short"),
    ],
)
def test_t2_momentum_functional_transitions(state, fast, slow, macro, price, expected, reason):
    from src.domain.strategy.t2_momentum import advance_t2_state
    new_state, new_reason = advance_t2_state(
        state, fast=fast, slow=slow, macro=macro, close=price, average=100
    )
    assert new_state == expected
    assert new_reason == reason


@pytest.mark.parametrize(
    "distance,r2,r5,expected",
    [
        (4.77, 0.5, 0.011, False),
        (4.77, 0, 0.011001, True),
        (4.770001, 0.010, 0.5, False),
        (4.770001, 0.010001, 0, True),
        (4, 0, None, False),
        (5, None, 0.5, False),
    ],
)
def test_fomo_functional_boundaries(distance, r2, r5, expected):
    from src.domain.strategy.fomo_gatekeeper import fomo_predicate
    assert fomo_predicate(distance, r2, r5) is expected

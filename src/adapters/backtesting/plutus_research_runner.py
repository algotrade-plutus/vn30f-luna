"""A causal Luna replay against the real Plutus exchange session.

The strategy observes a completed, left-labelled 30-minute bar.  Its target is
submitted at the start of the next available bar and is evaluated by Plutus
against that next bar.  Plutus, rather than this module, owns admission,
fills, fees, PIT, VSDC cash variation margin, expiry, and margin status.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
import math
from pathlib import Path
from typing import Any, Mapping

from plutus.core.order import OrderType as PlutusOrderType, Side as PlutusSide
from plutus.market.adapters.depth import SideAvailability
from plutus.market.protocol import Order as PlutusOrder
from plutus.market.session import (
    Accepted,
    EventKind,
    ExchangeSession,
    MarginStatus,
    Rejected,
    VnTradingCalendar,
    VsdcSettlementCalendar,
)

from src.adapters.data.plutus_bar_source import PlutusBarSource
from src.domain.entities.fill import Fill as DomainFill
from src.domain.entities.order import Side as DomainSide
from src.domain.entities.position import Position as DomainPosition
from src.domain.strategy.calendar_rules import VN_CLOSED_DAYS
from src.domain.strategy.hypothesis import FalsificationCriteria
from src.domain.strategy.luna_strategy import LunaParameters, LunaStrategy


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class ResearchRunResult:
    """JSON-safe headline metrics plus the evidence needed to audit them."""

    summary: dict[str, Any]
    daily_equity: tuple[dict[str, Any], ...]
    fills: tuple[dict[str, Any], ...]
    charges: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]
    ignorance: dict[str, Any]

    def to_dict(self, *, include_series: bool = True) -> dict[str, Any]:
        payload = dict(self.summary)
        payload["provenance"] = self.provenance
        payload["ignorance"] = self.ignorance
        if include_series:
            payload["daily_equity"] = list(self.daily_equity)
            payload["fills"] = list(self.fills)
            payload["charges"] = list(self.charges)
        return payload


class PlutusResearchRunner:
    """Run one parameter set through :class:`plutus.market.ExchangeSession`."""

    def __init__(
        self,
        futures_path: Path | str | PlutusBarSource,
        index_path: Path | str | None = None,
        *,
        initial_deposit: Decimal = Decimal("100000000"),
        max_participation: Decimal = Decimal("0.10"),
        margin_profile_firm: str = "SSI",
        target_multiplier: int = 1,
        execution_model: str = "soft",
        book_queue: str = "optimistic",
        book_max_staleness_seconds: float = 15.0,
        crossing_offset: Decimal = Decimal("0.1"),
    ) -> None:
        self.source = (
            futures_path
            if isinstance(futures_path, PlutusBarSource)
            else PlutusBarSource(futures_path, index_path)
        )
        self.initial_deposit = initial_deposit
        self.max_participation = max_participation
        self.margin_profile_firm = margin_profile_firm
        if execution_model not in {"soft", "book_walk"}:
            raise ValueError("execution_model must be 'soft' or 'book_walk'")
        if book_queue not in {"optimistic", "conservative", "probabilistic"}:
            raise ValueError("Unsupported book queue")
        if book_max_staleness_seconds < 0:
            raise ValueError("book_max_staleness_seconds must be non-negative")
        if crossing_offset < 0:
            raise ValueError("crossing_offset must be non-negative")
        self.execution_model = execution_model
        self.book_queue = book_queue
        self.book_max_staleness_seconds = book_max_staleness_seconds
        self.crossing_offset = crossing_offset
        if (
            isinstance(target_multiplier, bool)
            or not isinstance(target_multiplier, int)
            or target_multiplier < 1
        ):
            raise ValueError("target_multiplier must be a positive integer")
        self.target_multiplier = target_multiplier

    @staticmethod
    def _calendars() -> tuple[VnTradingCalendar, VsdcSettlementCalendar]:
        coverage = (date(2020, 1, 1), date(2027, 12, 31))
        holidays = frozenset(
            day for day in VN_CLOSED_DAYS if coverage[0] <= day <= coverage[1]
        )
        trading = VnTradingCalendar(
            holidays,
            coverage,
            calendar_id="vn-exchange-closures-2020-2027",
            source="src/domain/strategy/calendar_rules.py (documented exchange closures)",
        )
        # The repository does not contain the original VSDC notices.  Use the
        # exchange closures as an explicit proxy and say so in provenance.
        settlement = VsdcSettlementCalendar(
            holidays,
            coverage,
            calendar_id="exchange-closure-proxy-NOT-OFFICIAL-VSDC",
            source=None,
            trading=trading,
        )
        return trading, settlement

    def _session(self, start: date, end: date) -> ExchangeSession:
        config = {
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "resolution": "tick",
            "exchange_rules": {
                "venues": ["HNXDS"],
                "rulebook": "vn-2020-2026",
            },
            # No invented broker commission.  The dated rulebook still levies
            # statutory HNX, VSDC and PIT charges.
            # A named profile is required for the post-KRX overnight margin
            # grid.  SSI is the chosen research broker because this corpus
            # contains its dated VSDC parameter mirror; commission remains
            # explicitly zero until a broker fee schedule is supplied.
            "broker_profile": {
                "firm": self.margin_profile_firm,
                "commission": [],
                "warn": False,
            },
            "accounts": {
                "securities": {"initial_cash": 0},
                "derivatives": {"initial_deposit": str(self.initial_deposit)},
            },
            "fill_policy": (
                {
                    "kind": "soft",
                    "max_participation": str(self.max_participation),
                }
                if self.execution_model == "soft"
                else {
                    "kind": "book_walk",
                    "queue": self.book_queue,
                    "max_staleness": self.book_max_staleness_seconds,
                    # Visible depth, not interval volume, is the primary size
                    # constraint for the EC2 crossing-limit reconstruction.
                    "max_participation": None,
                }
            ),
            "data": {"adapter": "project-plutus-30m", "root": self.source.origin},
        }
        trading, settlement = self._calendars()
        return ExchangeSession.from_mapping(
            config,
            source=self.source,
            trading=trading,
            settlement=settlement,
        )

    def _crossing_limit(
        self,
        ticker: str,
        ts: datetime,
        side: PlutusSide,
    ) -> tuple[Decimal, dict[str, Any]]:
        """Price the EC2-style marketable limit from the as-of depth touch."""

        book = self.source.book_at(
            ticker,
            ts,
            max_age=timedelta(seconds=self.book_max_staleness_seconds),
        )
        crossing = book.ask if side is PlutusSide.BUY else book.bid
        state = self.source.state_at(ticker, ts)
        touch = None if crossing.best is None else crossing.best.price
        if touch is None:
            if state is None or state.last is None:
                raise ValueError(f"No touch or last price for {ticker} at {ts.isoformat()}")
            limit = state.last
        elif side is PlutusSide.BUY:
            limit = touch + self.crossing_offset
        else:
            limit = touch - self.crossing_offset
        if state is not None:
            if side is PlutusSide.BUY and state.ceiling is not None:
                limit = min(limit, state.ceiling)
            elif side is PlutusSide.SELL and state.floor is not None:
                limit = max(limit, state.floor)
        return limit, {
            "two_sided": book.is_two_sided,
            "crossed": book.is_crossed,
            "touching": book.is_touching,
            "crossing_side": crossing.availability.value,
            "crossing_truncation": crossing.truncation.value,
            "touch": None if touch is None else str(touch),
            "cross_side_skew_seconds": (
                None
                if book.cross_side_skew is None
                else book.cross_side_skew.total_seconds()
            ),
        }

    @staticmethod
    def _metrics(equity: list[Decimal], initial: Decimal) -> dict[str, float]:
        if not equity:
            raise ValueError("No complete 14:30/14:45 sessions in requested window")
        levels = [initial, *equity]
        returns = [float(levels[i] / levels[i - 1] - 1) for i in range(1, len(levels))]
        mean = sum(returns) / len(returns)
        if len(returns) > 1:
            variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
            std = math.sqrt(variance)
        else:
            std = 0.0
        sharpe = mean / std * math.sqrt(252) if std > 0 else 0.0
        peak = levels[0]
        max_drawdown = Decimal("0")
        for level in levels:
            peak = max(peak, level)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - level) / peak)
        final = equity[-1]
        total_return = final / initial - 1
        annualized = (
            float((final / initial) ** (Decimal(252) / Decimal(len(equity))) - 1)
            if final > 0
            else -1.0
        )
        return {
            "final_capital": float(final),
            "net_pnl": float(final - initial),
            "return_pct": float(total_return * 100),
            "annualized_return_pct": annualized * 100,
            "sharpe": sharpe,
            "mdd_pct": float(max_drawdown * 100),
        }

    @staticmethod
    def _closed_leg_pnl(orders: tuple[Any, ...]) -> tuple[Decimal, Decimal]:
        """Return positive and negative realised PnL after linked fill charges."""

        positions: dict[str, DomainPosition] = {}
        entry_costs: dict[str, Decimal] = {}
        wins = Decimal("0")
        losses = Decimal("0")
        for record in orders:
            for fill in record.fills:
                position = positions.setdefault(
                    fill.ticker,
                    DomainPosition(symbol=fill.ticker, multiplier=100_000),
                )
                domain_fill = DomainFill(
                    order_id=str(fill.order_id),
                    symbol=fill.ticker,
                    side=(DomainSide.BUY if fill.side is PlutusSide.BUY else DomainSide.SELL),
                    quantity=fill.quantity,
                    price=fill.price,
                    timestamp=fill.ts,
                    fee=sum((charge.total for charge in fill.charges), Decimal("0")),
                )
                before_quantity = position.net_quantity
                before_abs = abs(before_quantity)
                closed, realised = position.apply_fill(domain_fill)
                if closed:
                    allocated_entry_cost = (
                        entry_costs.get(fill.ticker, Decimal("0"))
                        * closed
                        / Decimal(before_abs)
                    )
                    closing_cost = domain_fill.fee * closed / Decimal(fill.quantity)
                    net = realised - allocated_entry_cost - closing_cost
                    if net > 0:
                        wins += net
                    elif net < 0:
                        losses += -net
                    remaining_entry_cost = (
                        entry_costs.get(fill.ticker, Decimal("0")) - allocated_entry_cost
                    )
                    reversal_quantity = max(fill.quantity - int(closed), 0)
                    reversal_cost = domain_fill.fee - closing_cost
                    entry_costs[fill.ticker] = (
                        reversal_cost if reversal_quantity else remaining_entry_cost
                    )
                else:
                    entry_costs[fill.ticker] = (
                        entry_costs.get(fill.ticker, Decimal("0")) + domain_fill.fee
                    )
        return wins, losses

    def run(
        self,
        start: date,
        end: date,
        params: LunaParameters | None = None,
        *,
        sample: str,
        target_by_start: Mapping[datetime, int] | None = None,
        signal_name: str = "luna",
        warmup_start: date | None = None,
    ) -> ResearchRunResult:
        rows = self.source.replay_bars(start, end)
        if not rows:
            raise ValueError(f"No futures bars in {start.isoformat()}..{end.isoformat()}")

        session = self._session(start, end)
        strategy = None if target_by_start is not None else LunaStrategy(params)
        pending_target = 0
        pending_reason = "initial_flat"
        previous_contract: str | None = None
        rejection_details: list[str] = []
        event_counts = {kind.value: 0 for kind in EventKind}
        daily: list[dict[str, Any]] = []
        incomplete_days: set[str] = set()
        peak_utilisation = Decimal("0")
        cancellation_rejections: list[str] = []
        book_checks = {
            "orders_priced": 0,
            "missing_crossing_side": 0,
            "crossed_books": 0,
            "touching_books": 0,
            "cross_side_skew_seconds": [],
        }

        if warmup_start is not None:
            if strategy is None:
                raise ValueError("warmup_start is only valid for strategy-generated targets")
            if warmup_start >= start:
                raise ValueError("warmup_start must be before the replay start date")
            for row in self.source.replay_bars(warmup_start, start - timedelta(days=1)):
                if previous_contract is not None and row.contract != previous_contract:
                    strategy.reset_market_history()
                previous_contract = row.contract
                target, pending_reason = strategy.on_bar(row.bar)
                pending_target = target * self.target_multiplier

        for row in rows:
            if session.now() < row.start:
                for event in session.advance_to(row.start):
                    event_counts[event.kind.value] += 1

            if (
                strategy is not None
                and previous_contract is not None
                and row.contract != previous_contract
            ):
                strategy.reset_market_history()
            previous_contract = row.contract

            if target_by_start is not None:
                requested = target_by_start.get(row.start)
                if requested is not None:
                    if isinstance(requested, bool) or not isinstance(requested, int):
                        raise TypeError(
                            f"Target at {row.start.isoformat()} must be an int, "
                            f"got {requested!r}"
                        )
                    target_changed = requested != pending_target
                    pending_target = requested
                    pending_reason = f"{signal_name}_precomputed_target"
                    if target_changed and self.execution_model == "book_walk":
                        # A stale/partial LIMIT can survive into the next bar.
                        # The live EC2 loop replaces intent; it does not stack
                        # another full order on top of an old one.
                        for live in tuple(
                            record
                            for record in session.orders()
                            if record.is_live and record.order.ticker == row.contract
                        ):
                            cancelled = session.cancel(live.order_id)
                            if isinstance(cancelled, Rejected):
                                cancellation_rejections.append(
                                    f"{row.start.isoformat()} {row.contract} "
                                    f"{cancelled.rule.value}: {cancelled.detail}"
                                )

            position = session.positions().get(row.contract)
            current = 0 if position is None else position.net_quantity
            live_delta = sum(
                (
                    record.remaining_quantity
                    if record.order.side is PlutusSide.BUY
                    else -record.remaining_quantity
                )
                for record in session.orders()
                if record.is_live and record.order.ticker == row.contract
            )
            delta = pending_target - (current + live_delta)
            # 11:30 is a boundary print inside the noon shutdown.  Carry the
            # target to 13:00 rather than submitting an order the venue forbids.
            has_current_contract_mark = (
                self.source.state_at(row.contract, row.start) is not None
            )
            if (
                delta
                and has_current_contract_mark
                and not (row.start.hour == 11 and row.start.minute == 30)
            ):
                side = PlutusSide.BUY if delta > 0 else PlutusSide.SELL
                limit_price = None
                if self.execution_model == "book_walk":
                    order_type = PlutusOrderType.LIMIT
                    limit_price, evidence = self._crossing_limit(
                        row.contract, row.start, side
                    )
                    book_checks["orders_priced"] += 1
                    if evidence["crossing_side"] != SideAvailability.OBSERVED.value:
                        book_checks["missing_crossing_side"] += 1
                    if evidence["crossed"]:
                        book_checks["crossed_books"] += 1
                    if evidence["touching"]:
                        book_checks["touching_books"] += 1
                    if evidence["cross_side_skew_seconds"] is not None:
                        book_checks["cross_side_skew_seconds"].append(
                            evidence["cross_side_skew_seconds"]
                        )
                else:
                    order_type = (
                        PlutusOrderType.AT_THE_CLOSE
                        if row.start.hour == 14 and row.start.minute == 30
                        else PlutusOrderType.MARKET_FILL_OR_KILL
                    )
                verdict = session.submit(
                    PlutusOrder(
                        ticker=row.contract,
                        side=side,
                        quantity=abs(delta),
                        order_type=order_type,
                        limit_price=limit_price,
                    )
                )
                if isinstance(verdict, Rejected):
                    rejection_details.append(
                        f"{row.start.isoformat()} {row.contract} {verdict.rule.value}: {verdict.detail}"
                    )
                elif not isinstance(verdict, Accepted):
                    rejection_details.append(
                        f"{row.start.isoformat()} unexpected verdict {verdict!r}"
                    )

            for event in session.advance_to(row.end):
                event_counts[event.kind.value] += 1

            if strategy is not None:
                target, pending_reason = strategy.on_bar(row.bar)
                pending_target = target * self.target_multiplier
            margin = session.margin()
            if margin.utilisation is not None:
                peak_utilisation = max(peak_utilisation, margin.utilisation)

            if row.is_last_of_day:
                if row.start.hour == 14 and row.start.minute == 30:
                    daily.append(
                        {
                            "date": row.start.date().isoformat(),
                            "equity": float(margin.deposit_balance),
                            "deposit_balance": float(margin.deposit_balance),
                            "margin_status": margin.status.value,
                            "utilisation_pct": (
                                None
                                if margin.utilisation is None
                                else float(margin.utilisation * 100)
                            ),
                            "positions": {
                                code: held.net_quantity
                                for code, held in sorted(session.positions().items())
                            },
                            "last_signal": pending_reason,
                        }
                    )
                else:
                    incomplete_days.add(row.start.date().isoformat())

        orders = session.orders()
        fills = tuple(fill for record in orders for fill in record.fills)
        charges = session.charges()
        metrics = self._metrics(
            [Decimal(str(item["equity"])) for item in daily], self.initial_deposit
        )
        wins, losses = self._closed_leg_pnl(orders)
        profit_factor = float(wins / losses) if losses > 0 else None
        ignorance_obj = session.indeterminate_report()
        ignorance = _json_value(asdict(ignorance_obj))
        provenance = _json_value(asdict(session.provenance()))

        criteria = FalsificationCriteria()
        failures: list[str] = []
        minimum_sharpe = (
            criteria.min_sharpe_out_of_sample
            if sample == "out_of_sample"
            else criteria.min_sharpe_in_sample
        )
        if Decimal(str(metrics["sharpe"])) < minimum_sharpe:
            failures.append(f"Sharpe {metrics['sharpe']:.3f} < {minimum_sharpe}")
        if Decimal(str(metrics["mdd_pct"])) > criteria.max_drawdown_pct:
            failures.append(f"MDD {metrics['mdd_pct']:.3f}% > {criteria.max_drawdown_pct}%")
        if peak_utilisation >= criteria.max_peak_margin_utilisation:
            failures.append(
                f"Peak margin utilisation {peak_utilisation * 100:.3f}% >= "
                f"{criteria.max_peak_margin_utilisation * 100}%"
            )
        if event_counts[EventKind.MARGIN_CALL.value] > criteria.max_margin_calls:
            failures.append(f"Margin calls: {event_counts[EventKind.MARGIN_CALL.value]}")
        if len(rejection_details) > criteria.max_exchange_rejects:
            failures.append(f"Exchange submission rejects: {len(rejection_details)}")
        if profit_factor is not None and Decimal(str(profit_factor)) < criteria.min_profit_factor:
            failures.append(f"Profit factor {profit_factor:.3f} < {criteria.min_profit_factor}")
        if ignorance_obj.indeterminate:
            failures.append(
                "Plutus reported indeterminate evaluations; see ignorance evidence"
            )

        total_charges = sum((charge.total for charge in charges), Decimal("0"))
        summary = {
            "status": "PASSED" if not failures else "FAILED",
            "engine": "plutus.market.session.ExchangeSession",
            "sample": sample,
            "signal": signal_name,
            "target_multiplier": self.target_multiplier,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "observed_data_start": rows[0].start.isoformat(),
            "observed_data_end": rows[-1].end.isoformat(),
            "data_source": self.source.origin,
            "complete_sessions": len(daily),
            "incomplete_session_dates_excluded_from_metrics": sorted(incomplete_days),
            "initial_capital": float(self.initial_deposit),
            **metrics,
            "orders": len(orders),
            "fills": len(fills),
            "order_states": {
                state: sum(1 for record in orders if record.state.value == state)
                for state in sorted({record.state.value for record in orders})
            },
            "fully_filled_orders": sum(
                1 for record in orders if record.filled_quantity == record.original_quantity
            ),
            "partially_filled_orders": sum(
                1
                for record in orders
                if 0 < record.filled_quantity < record.original_quantity
            ),
            "unfilled_orders": sum(1 for record in orders if not record.fills),
            "profit_factor_realised_after_linked_fill_charges": profit_factor,
            "profit_factor_note": (
                "undefined because no realised losing leg"
                if profit_factor is None
                else "realised closed legs after proportional entry/exit fill charges"
            ),
            "gross_realised_wins_after_linked_charges": float(wins),
            "gross_realised_losses_after_linked_charges": float(losses),
            "total_charges": float(total_charges),
            "peak_margin_utilisation_pct": float(peak_utilisation * 100),
            "margin_warnings_80": event_counts[EventKind.MARGIN_WARNING.value],
            "margin_calls_90": event_counts[EventKind.MARGIN_CALL.value],
            "forced_liquidations_100": event_counts[EventKind.FORCED_LIQUIDATION.value],
            "expiry_settlements": event_counts[EventKind.EXPIRY_SETTLED.value],
            "exchange_rejects": len(rejection_details),
            "rejection_details": rejection_details,
            "cancellation_rejections": cancellation_rejections,
            "event_counts": event_counts,
            "open_positions_at_end": {
                code: held.net_quantity for code, held in sorted(session.positions().items())
            },
            "failures": failures,
            "execution_evidence": (
                "DEPTH_BACKED_RECONSTRUCTED_BOOK"
                if self.execution_model == "book_walk"
                else "MODELLED_SOFT_NO_BOOK_DEPTH"
            ),
            "book_execution_diagnostics": {
                **{key: value for key, value in book_checks.items() if key != "cross_side_skew_seconds"},
                "median_cross_side_skew_seconds": (
                    None
                    if not book_checks["cross_side_skew_seconds"]
                    else sorted(book_checks["cross_side_skew_seconds"])[
                        len(book_checks["cross_side_skew_seconds"]) // 2
                    ]
                ),
                "provider": getattr(
                    getattr(self.source, "book_provider", None),
                    "diagnostics",
                    {},
                ),
            },
            "assumptions": [
                (
                    f"{self.source.bar_minutes}-minute OHLCV bars are left-labelled and "
                    "served to Plutus only after completion."
                ),
                (
                    "Signals execute on the next available bar; no same-close fills."
                    if target_by_start is None
                    else "Pre-shifted causal targets are submitted at their stamped execution interval."
                ),
                (
                    f"Published bands used on {self.source.band_source_counts['published']} futures bars; "
                    f"{self.source.band_source_counts['reconstructed']} bars were reconstructed from the previous observed close."
                ),
                "VSDC settlement notices are absent; exchange closures are an explicitly named proxy.",
                (
                    "Indicators reset at contract roll because no overlap exists for back-adjustment."
                    if target_by_start is None
                    else "The external signal generator owns indicator continuity across contract rolls."
                ),
                "Broker commission is zero; Plutus still applies dated statutory HNX/VSDC/PIT charges.",
                (
                    "Depth-backed execution reconstructs each of three levels independently as-of the order timestamp; no level 4+ is invented."
                    if self.execution_model == "book_walk"
                    else "Soft fills assume market-family size exists at the observed price; the interval carries no order-book depth."
                ),
                (
                    f"Book queue={self.book_queue}; maximum level age={self.book_max_staleness_seconds:g}s; crossing limit offset={self.crossing_offset} point."
                    if self.execution_model == "book_walk"
                    else f"Soft-fill participation cap={self.max_participation}."
                ),
            ],
        }

        fill_rows = tuple(
            {
                "fill_id": str(fill.fill_id),
                "order_id": str(fill.order_id),
                "ticker": fill.ticker,
                "side": fill.side.value,
                "quantity": fill.quantity,
                "price": str(fill.price),
                "timestamp": fill.ts.isoformat(),
                "evidence": fill.evidence.value,
                "confidence": str(fill.confidence),
                "is_maker": fill.is_maker,
                "charges": str(sum((charge.total for charge in fill.charges), Decimal("0"))),
            }
            for fill in fills
        )
        charge_rows = tuple(_json_value(asdict(charge)) for charge in charges)
        return ResearchRunResult(
            summary=summary,
            daily_equity=tuple(daily),
            fills=fill_rows,
            charges=charge_rows,
            provenance=provenance,
            ignorance=ignorance,
        )

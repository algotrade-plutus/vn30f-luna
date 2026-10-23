"""Order-path smoke test on the paper account: one cancel and one 1-contract round trip.

Run only while trading is continuous, on a flat account with no working orders:

1. BUY 1 far below the bid, wait for New, cancel, expect Canceled.
2. BUY 1 through the ask, wait up to 8 s (cancel if needed), read REST.
3. SELL whatever REST shows through the bid, read REST: the account must end flat.

Prints order ids, statuses, prices and REST positions only.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from papertrade.calibrum.broker import Broker
from papertrade.calibrum.execution import Order, order_price, phase, tick
from papertrade.calibrum.quotes import KafkaQuotes
from papertrade.calibrum.runner import now_ict
from src.domain.strategy.calendar_rules import front_month_contract


def show(label: str, broker: Broker) -> int:
    account = broker.account()
    print(f"{now_ict():%H:%M:%S} {label}: position={account.position} working={account.working_orders} "
          f"remain_cash={account.remain_cash / 1e6:.1f}M", flush=True)
    return account.position


def run(broker: Broker, quotes: KafkaQuotes, order: Order, wait_s: float = 8.0) -> None:
    cl_ord_id = broker.place(order)
    status = broker.wait(cl_ord_id, wait_s)
    if status not in {"Filled", "Canceled", "Rejected", "Expired"}:
        terminal, status = broker.cancel(cl_ord_id)
        print(f"  cancel after {wait_s:.0f}s: terminal={terminal} status={status}")
    print(f"  {order.side} {order.qty} @ {order.price} ({order.reason}) id={cl_ord_id} status={status} "
          f"filled={broker.filled(cl_ord_id)} text={broker.reject_text(cl_ord_id)}", flush=True)
    time.sleep(3.0)


def main() -> int:
    if phase(now_ict()) != "continuous":
        print("refusing: trading is not continuous now")
        return 2
    symbol = f"HNXDS:{front_month_contract(now_ict().date())}"
    broker = Broker.from_env(symbol, allow_orders=True, state_dir=Path(os.getenv("CALIBRUM_STATE_DIR", "/state")))
    if not broker.connect():
        print("refusing: FIX logon failed")
        return 3
    quotes = KafkaQuotes()
    try:
        if show("start", broker) != 0 or broker.working_orders():
            print("refusing: account is not flat with no working orders")
            return 2
        quotes.follow(symbol)
        for _ in range(30):
            quote = quotes.quote(symbol)
            if quote is not None:
                break
            time.sleep(1.0)
        else:
            print("refusing: no Kafka quote")
            return 4
        print(f"quote {symbol}: bid {quote.bid} ask {quote.ask} band {quote.floor}-{quote.ceiling}")

        print("1) cancel test")
        far = Order("BUY", 1, tick(max(quote.floor, quote.bid - 5.0)), "smoke-cancel")
        cl_ord_id = broker.place(far)
        status = broker.wait(cl_ord_id, 5.0, statuses={"New", "Rejected"})
        terminal, status = broker.cancel(cl_ord_id)
        print(f"  BUY 1 @ {far.price} id={cl_ord_id} -> cancel terminal={terminal} status={status}")
        time.sleep(2.0)
        show("after cancel", broker)

        print("2) open 1")
        quote = quotes.quote(symbol)
        run(broker, quotes, Order("BUY", 1, order_price("BUY", quote, "continuous", 0.3), "smoke-open"))
        held = show("after open", broker)

        print("3) close")
        if held:
            side = "SELL" if held > 0 else "BUY"
            quote = quotes.quote(symbol)
            run(broker, quotes, Order(side, abs(held), order_price(side, quote, "continuous", 0.3), "smoke-close"))
        final = show("end", broker)
        return 0 if final == 0 and not broker.working_orders() else 1
    finally:
        quotes.stop()
        broker.disconnect()


if __name__ == "__main__":
    sys.exit(main())

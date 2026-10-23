"""Close the position in the managed contract, during continuous trading, and check the account ends flat.

Run with the runner stopped (the execution lock keeps two clients apart). Refuses
when there are working orders. Sells or buys back what REST shows with a LIMIT
through the book, reading REST again before each of at most three attempts.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from papertrade.calibrum.broker import Broker
from papertrade.calibrum.execution import Order, order_price, phase
from papertrade.calibrum.quotes import KafkaQuotes
from papertrade.calibrum.runner import now_ict
from papertrade.calibrum.smoke import show
from src.domain.strategy.calendar_rules import front_month_contract


def main() -> int:
    window = phase(now_ict())
    if window == "closed":
        print("refusing: no order window now")
        return 2
    symbol = f"HNXDS:{front_month_contract(now_ict().date())}"
    broker = Broker.from_env(symbol, allow_orders=True, state_dir=Path(os.getenv("CALIBRUM_STATE_DIR", "/state")))
    if not broker.connect():
        print("refusing: FIX logon failed")
        return 3
    quotes = KafkaQuotes()
    try:
        if broker.working_orders():
            print("refusing: working orders on the account")
            return 2
        quotes.follow(symbol)
        for attempt in range(1, 4):
            held = show(f"attempt {attempt}", broker)
            if held == 0:
                break
            quote = None
            for _ in range(30):
                quote = quotes.quote(symbol)
                if quote is not None:
                    break
                time.sleep(1.0)
            if quote is None:
                print("refusing: no Kafka quote")
                return 4
            side = "SELL" if held > 0 else "BUY"
            order = Order(side, abs(held), order_price(side, quote, window, 0.3), "flatten")
            cl_ord_id = broker.place(order)
            status = broker.wait(cl_ord_id, 8.0)
            if status not in {"Filled", "Canceled", "Rejected", "Expired"}:
                broker.cancel(cl_ord_id)
            print(f"  {side} {order.qty} @ {order.price} id={cl_ord_id} status={status} filled={broker.filled(cl_ord_id)}")
            time.sleep(3.0)
        final = show("end", broker)
        return 0 if final == 0 and not broker.working_orders() else 1
    finally:
        quotes.stop()
        broker.disconnect()


if __name__ == "__main__":
    sys.exit(main())

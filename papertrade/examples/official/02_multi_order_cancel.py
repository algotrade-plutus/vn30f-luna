"""
Example 02 - Multi Order Placement and Cancellation

Demonstrates:
- Place multiple buy/sell orders sequentially
- Track all orders with proper status handling
- Handle rejected orders (don't cancel them)
- Wait 15 seconds
- Cancel only active orders (skip those already rejected/filled)
- Tuple return from ``cancel_order`` (v0.2.6+): ``(is_terminal, status)``

Usage:
    python examples/02_multi_order_cancel.py
"""

import os
import sys
import time
import logging
from pathlib import Path
from threading import Event as ThreadEvent
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paperbroker.client import PaperBrokerClient

# Load environment variables
load_dotenv()

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class OrderTracker:
    """Track multiple orders with proper status management."""
    def __init__(self):
        self.orders = {}  # order_id -> {"status": str, "side": str, "qty": int, "price": float}
        self.accepted_events = {}  # order_id -> Event
        self.canceled_events = {}  # order_id -> Event
        self.rejected_events = {}  # order_id -> Event

    def add_order(self, order_id, side, qty, price):
        self.orders[order_id] = {
            "status": "PENDING",
            "side": side,
            "qty": qty,
            "price": price,
            "reject_reason": None
        }
        self.accepted_events[order_id] = ThreadEvent()
        self.canceled_events[order_id] = ThreadEvent()
        self.rejected_events[order_id] = ThreadEvent()

    def mark_accepted(self, order_id, status):
        if order_id in self.orders:
            self.orders[order_id]["status"] = status
            self.accepted_events[order_id].set()

    def mark_canceled(self, order_id, status):
        if order_id in self.orders:
            self.orders[order_id]["status"] = status
            self.canceled_events[order_id].set()

    def mark_rejected(self, order_id, reason):
        if order_id in self.orders:
            self.orders[order_id]["status"] = "REJECTED"
            self.orders[order_id]["reject_reason"] = reason
            self.rejected_events[order_id].set()
            # Also set accepted event to unblock waiting
            self.accepted_events[order_id].set()
            # Also set canceled event (no need to cancel rejected orders)
            self.canceled_events[order_id].set()

    def is_active(self, order_id):
        """Check if order is active (can be canceled)."""
        if order_id not in self.orders:
            return False
        status = self.orders[order_id]["status"]
        return status in ("NEW", "PENDING_NEW", "PARTIALLY_FILLED")

    def is_rejected(self, order_id):
        """Check if order was rejected."""
        if order_id not in self.orders:
            return False
        return self.orders[order_id]["status"] == "REJECTED"

    def get_active_orders(self, order_ids):
        """Get list of active order IDs that can be canceled."""
        return [oid for oid in order_ids if self.is_active(oid)]


def on_order_accepted(tracker, cl_ord_id, status, **kwargs):
    """Event handler for order accepted."""
    if cl_ord_id in tracker.orders:
        tracker.mark_accepted(cl_ord_id, status)
        side = tracker.orders[cl_ord_id]["side"]
        logger.info(f"✅ Order accepted: {cl_ord_id[:8]}... ({side}, Status: {status})")


def on_order_canceled(tracker, orig_cl_ord_id, status, **kwargs):
    """Event handler for order canceled."""
    if orig_cl_ord_id in tracker.orders:
        tracker.mark_canceled(orig_cl_ord_id, status)
        logger.info(f"✅ Order canceled: {orig_cl_ord_id[:8]}... (Status: {status})")


def on_order_rejected(tracker, cl_ord_id, reason, **kwargs):
    """Event handler for order rejected."""
    if cl_ord_id in tracker.orders:
        tracker.mark_rejected(cl_ord_id, reason)
        side = tracker.orders[cl_ord_id]["side"]
        logger.error(f"❌ Order rejected: {cl_ord_id[:8]}... ({side}) - {reason}")


def main():
    """Multi order placement and cancellation demonstration."""

    # Configuration
    symbol = os.getenv("VN30F1M", "HNXDS:VN30F2604")
    account = os.getenv("PAPER_ACCOUNT_ID", "main")
    
    # Orders to place: (side, qty, price)
    # side: "BUY" or "SELL"
    orders_to_place = [
        # ("SELL", 4, 1000.0),
        ("BUY", 10, 1900.0),
        ("SELL", 4, 1000.0),
        ("SELL", 4, 1000.0),
    ]
    delay_seconds = 15

    logger.info("=" * 70)
    logger.info("MULTI ORDER PLACEMENT & CANCELLATION EXAMPLE")
    logger.info("=" * 70)
    logger.info(f"Symbol: {symbol}")
    logger.info(f"Account: {account}")
    logger.info(f"Orders: {len(orders_to_place)} orders")
    for i, (side, qty, price) in enumerate(orders_to_place, 1):
        logger.info(f"  {i}. {side} {qty} @ {price:,.0f}")
    logger.info(f"Strategy: Place all → Wait {delay_seconds}s → Cancel active orders")
    logger.info("=" * 70)

    tracker = OrderTracker()

    # Create client
    client = PaperBrokerClient(
        default_sub_account=account,
        username=os.getenv("PAPER_USERNAME", "BL01"),
        password=os.getenv("PAPER_PASSWORD", "123"),
        rest_base_url=os.getenv("PAPER_REST_BASE_URL", "http://localhost:9090"),
        socket_connect_host=os.getenv("SOCKET_HOST", "localhost"),
        socket_connect_port=int(os.getenv("SOCKET_PORT", "5001")),
        sender_comp_id=os.getenv("SENDER_COMP_ID", "LOCAL_FIX"),
        target_comp_id=os.getenv("TARGET_COMP_ID", "SERVER"),
        console=True,
        order_store_path="orders.db",
    )

    # Subscribe to events
    client.on("fix:order:accepted", lambda **kw: on_order_accepted(tracker, **kw))
    client.on("fix:order:canceled", lambda **kw: on_order_canceled(tracker, **kw))
    client.on("fix:order:rejected", lambda **kw: on_order_rejected(tracker, **kw))

    # Connect
    logger.info("\n🔌 Connecting to PaperBroker...")
    client.connect()

    try:
        # Wait for logon
        if not client.wait_until_logged_on(timeout=10):
            error = client.last_logon_error()
            logger.error(f"❌ Logon failed: {error}")
            return

        logger.info("✅ Successfully logged on!")

        # Check balance
        cash = client.get_cash_balance()
        logger.info(f"💰 Available cash: {cash.get('remainCash', 0):,.0f} VND\n")

        # Step 1: Place all orders sequentially
        logger.info("=" * 70)
        logger.info("STEP 1: PLACE ORDERS (SEQUENTIALLY)")
        logger.info("=" * 70)

        placed_order_ids = []
        for i, (side, qty, price) in enumerate(orders_to_place, 1):
            logger.info(f"\n📝 Placing order {i}/{len(orders_to_place)}: {side} {qty} @ {price:,.0f}")
            
            order_id = client.place_order(
                full_symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                ord_type="LIMIT"
            )
            
            tracker.add_order(order_id, side, qty, price)
            placed_order_ids.append(order_id)
            logger.info(f"   Order ID: {order_id[:16]}...")

            # Wait for order acceptance or rejection before placing next
            if not tracker.accepted_events[order_id].wait(timeout=10):
                logger.warning(f"⚠️ Timeout waiting for order {i} response")
            elif tracker.is_rejected(order_id):
                logger.info(f"   ⚠️ Order {i} was rejected, continuing...")

            # Delay between orders
            if i < len(orders_to_place):
                logger.info(f"   ⏳ Waiting 1s before next order...")
                time.sleep(1)
            
        # Count results
        accepted_count = len(tracker.get_active_orders(placed_order_ids))
        rejected_count = sum(1 for oid in placed_order_ids if tracker.is_rejected(oid))
        
        logger.info(f"\n📊 Placement results: {accepted_count} accepted, {rejected_count} rejected")

        if accepted_count == 0:
            logger.info("\n⚠️ No active orders to cancel. Exiting...")
        else:
            # Step 2: Wait before canceling
            logger.info(f"\n⏳ Waiting {delay_seconds} seconds before canceling...")
            time.sleep(delay_seconds)

            # Step 3: Cancel only active orders
            active_orders = tracker.get_active_orders(placed_order_ids)
            
            logger.info("\n" + "=" * 70)
            logger.info(f"STEP 2: CANCEL ACTIVE ORDERS ({len(active_orders)} orders)")
            logger.info("=" * 70)

            for i, order_id in enumerate(active_orders, 1):
                order_info = tracker.orders[order_id]
                logger.info(f"\n❌ Canceling order {i}/{len(active_orders)}: {order_id[:16]}... ({order_info['side']})")
                is_terminal, final_status = client.cancel_order(order_id, timeout=5.0)
                logger.info(
                    f"  cancel returned is_terminal={is_terminal}, status={final_status}"
                )

            # Wait for all cancellations
            if active_orders:
                logger.info("\n⏳ Waiting for cancellation confirmations...")
                for order_id in active_orders:
                    if not tracker.canceled_events[order_id].wait(timeout=10):
                        logger.warning(f"⚠️ Timeout waiting for cancellation: {order_id[:16]}...")

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("📊 SUMMARY")
        logger.info("=" * 70)
        for i, order_id in enumerate(placed_order_ids, 1):
            order_info = tracker.orders[order_id]
            side = order_info["side"]
            qty = order_info["qty"]
            price = order_info["price"]
            status = order_info["status"]
            reject_reason = order_info.get("reject_reason")
            
            status_str = status
            if reject_reason:
                status_str = f"{status} ({reject_reason})"
            
            logger.info(f"  {i}. {side} {qty} @ {price:,.0f} - {status_str}")
        logger.info("=" * 70)

        logger.info("\n✅ Example completed!")

    finally:
        os._exit(0)


if __name__ == "__main__":
    main()

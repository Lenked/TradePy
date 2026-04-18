"""
Demo script to show the 90-minute auto-close functionality
"""

import time
from datetime import datetime, timedelta
from unittest.mock import Mock

from core.trading.auto_close_scheduler import AutoCloseScheduler
from core.models import OrderResult
from core.exchange.broker import Broker


def demo_auto_close_functionality():
    print("=== TradePy 90-Minute Auto-Close Demo ===\n")
    
    # Create a mock exchange for demonstration
    # In real usage, this would be MT5Executor or Broker
    mock_exchange = Mock()
    
    # Mock the positions method to return a position
    mock_position = {
        "ticket": "123456",
        "symbol": "EURUSD",
        "side": "BUY",
        "volume": 0.1
    }
    mock_exchange.positions.return_value = [mock_position]
    
    # Mock the close_position method to return success
    mock_exchange.close_position.return_value = OrderResult(
        success=True,
        order_id="123456",
        message="position_closed",
        comment="Auto-closed after 90 minutes"
    )
    
    # Initialize the auto-close scheduler with 1 minute timeout for demo purposes
    scheduler = AutoCloseScheduler(mock_exchange, timeout_minutes=1)
    
    print("1. Initializing AutoCloseScheduler with 1-minute timeout...")
    print(f"   Timeout set to: {scheduler.timeout_minutes} minutes")
    print(f"   Active trades: {len(scheduler.open_trades)}\n")
    
    # Register a trade that was opened 2 minutes ago (already expired)
    ticket = "123456"
    expired_time = datetime.now() - timedelta(minutes=2)  # 2 minutes ago
    scheduler.register_trade(ticket, expired_time)
    
    print("2. Registering trade that expired 2 minutes ago...")
    print(f"   Trade ticket: {ticket}")
    print(f"   Open time: {expired_time}")
    print(f"   Current time: {datetime.now()}")
    print(f"   Active trades after registration: {len(scheduler.open_trades)}\n")
    
    # Check and close expired trades
    print("3. Checking for expired trades...")
    results = scheduler.check_and_close_expired_trades()
    
    print(f"   Found {len(results)} expired trades")
    if results:
        result = results[0]
        print(f"   Close result: Success={result.success}")
        print(f"   Message: {result.message}")
        print(f"   Comment: {result.comment}")
    
    print(f"   Active trades after cleanup: {len(scheduler.open_trades)}\n")
    
    # Register another trade that's still valid
    valid_ticket = "789012"
    valid_time = datetime.now() - timedelta(seconds=30)  # 30 seconds ago
    scheduler.register_trade(valid_ticket, valid_time)
    
    print("4. Registering trade that's still valid (30 seconds old)...")
    print(f"   Trade ticket: {valid_ticket}")
    print(f"   Open time: {valid_time}")
    print(f"   Active trades: {len(scheduler.open_trades)}\n")
    
    # Check for expired trades again (should find none)
    print("5. Checking for expired trades again...")
    results = scheduler.check_and_close_expired_trades()
    
    print(f"   Found {len(results)} expired trades")
    print(f"   Active trades remain: {len(scheduler.open_trades)}\n")
    
    # Show active trades info
    active_info = scheduler.get_active_trades()
    print("6. Active trades information:")
    for ticket, info in active_info.items():
        print(f"   Ticket: {ticket}")
        print(f"   Elapsed: {info['elapsed']}")
        print(f"   Remaining: {info['remaining']}")
        print(f"   Expired: {info['expired']}")
    
    print("\n=== Demo completed successfully! ===")
    print("\nThe auto-close scheduler will automatically close trades after 90 minutes")
    print("to prevent long sessions that could expose the bot to changing trends.")


if __name__ == "__main__":
    demo_auto_close_functionality()
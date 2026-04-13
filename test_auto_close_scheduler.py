"""
Test for the auto-close scheduler functionality
"""

import time
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock

from core.trading.auto_close_scheduler import AutoCloseScheduler
from core.models import OrderResult


def test_auto_close_scheduler_initialization():
    """Test that the auto-close scheduler initializes properly"""
    mock_exchange = Mock()
    scheduler = AutoCloseScheduler(mock_exchange, timeout_minutes=90)
    
    assert scheduler.timeout_minutes == 90
    assert scheduler.exchange == mock_exchange
    assert scheduler.open_trades == {}
    print("PASS: Auto-close scheduler initialization test passed")


def test_register_and_unregister_trade():
    """Test registering and unregistering trades"""
    mock_exchange = Mock()
    scheduler = AutoCloseScheduler(mock_exchange, timeout_minutes=90)
    
    # Register a trade
    ticket = "123456"
    open_time = datetime.now()
    scheduler.register_trade(ticket, open_time)
    
    assert ticket in scheduler.open_trades
    assert scheduler.open_trades[ticket] == open_time
    
    # Unregister the trade
    scheduler.unregister_trade(ticket)
    
    assert ticket not in scheduler.open_trades
    print("PASS: Register and unregister trade test passed")


def test_get_active_trades():
    """Test getting information about active trades"""
    mock_exchange = Mock()
    scheduler = AutoCloseScheduler(mock_exchange, timeout_minutes=90)
    
    # Register a trade
    ticket = "123456"
    past_time = datetime.now() - timedelta(minutes=30)  # 30 minutes ago
    scheduler.register_trade(ticket, past_time)
    
    active_trades = scheduler.get_active_trades()
    
    assert ticket in active_trades
    assert active_trades[ticket]["elapsed"].total_seconds() >= 30 * 60  # At least 30 minutes
    assert active_trades[ticket]["remaining"].total_seconds() <= 60 * 60  # Less than 60 minutes left
    assert not active_trades[ticket]["expired"]  # Should not be expired yet
    
    print("PASS: Get active trades test passed")


def test_check_and_close_expired_trades():
    """Test checking and closing expired trades"""
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
    
    scheduler = AutoCloseScheduler(mock_exchange, timeout_minutes=1)  # 1 minute for testing
    
    # Register a trade that expired 30 minutes ago
    ticket = "123456"
    expired_time = datetime.now() - timedelta(minutes=2)  # 2 minutes ago (more than 1 min timeout)
    scheduler.register_trade(ticket, expired_time)
    
    # Check and close expired trades
    results = scheduler.check_and_close_expired_trades()
    
    # Verify that the trade was closed
    assert len(results) == 1
    assert results[0].success is True
    assert ticket not in scheduler.open_trades  # Should be unregistered
    
    # Verify that close_position was called
    mock_exchange.close_position.assert_called_once_with(
        ticket=ticket,
        symbol="EURUSD",
        volume=0.1,
        side="BUY",
        comment="TradePy Auto-Close: 1min timeout"
    )
    
    print("PASS: Check and close expired trades test passed")


def test_check_and_close_non_expired_trades():
    """Test that non-expired trades are not closed"""
    mock_exchange = Mock()
    scheduler = AutoCloseScheduler(mock_exchange, timeout_minutes=90)
    
    # Register a trade that's only 1 minute old
    ticket = "123456"
    recent_time = datetime.now() - timedelta(minutes=1)
    scheduler.register_trade(ticket, recent_time)
    
    # Check and close expired trades
    results = scheduler.check_and_close_expired_trades()
    
    # Verify that no trades were closed
    assert len(results) == 0
    assert ticket in scheduler.open_trades  # Should still be registered
    
    print("PASS: Check and close non-expired trades test passed")


def test_close_trade_with_missing_position():
    """Test closing a trade when position no longer exists"""
    mock_exchange = Mock()
    # Mock positions to return empty list (no positions)
    mock_exchange.positions.return_value = []
    
    scheduler = AutoCloseScheduler(mock_exchange, timeout_minutes=1)  # 1 minute for testing
    
    # Register a trade that expired
    ticket = "123456"
    expired_time = datetime.now() - timedelta(minutes=2)
    scheduler.register_trade(ticket, expired_time)
    
    # Try to close expired trades
    results = scheduler.check_and_close_expired_trades()
    
    # Should succeed because position was already closed elsewhere
    assert len(results) == 1
    assert results[0].success is True
    assert ticket not in scheduler.open_trades
    
    print("PASS: Close trade with missing position test passed")


if __name__ == "__main__":
    print("Running auto-close scheduler tests...")
    
    test_auto_close_scheduler_initialization()
    test_register_and_unregister_trade()
    test_get_active_trades()
    test_check_and_close_expired_trades()
    test_check_and_close_non_expired_trades()
    test_close_trade_with_missing_position()
    
    print("""
ALL TESTS PASSED! Auto-close scheduler functionality verified.""")
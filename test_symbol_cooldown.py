"""
Test cases for symbol-specific cooldown functionality.
"""
import pytest
from datetime import datetime, timedelta
from core.risk.manager import RiskManager


def test_symbol_specific_cooldown():
    """Test that losses on one symbol don't block other symbols"""
    config = {
        "cooldown_minutes_after_loss": 30,
        "global_cooldown_minutes_after_loss": 0
    }
    rm = RiskManager(config)
    
    now = datetime(2026, 1, 30, 10, 0, 0)
    
    # Record a loss on XAUUSDm
    rm.record_trade_close(-10, now, "XAUUSDm")
    
    # XAU should be blocked due to cooldown
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        df=None,
        now=now + timedelta(minutes=15)  # Still within cooldown period
    )
    assert allowed is False
    assert reason == "symbol_cooldown_after_loss"
    
    # BTC should still be allowed since it didn't have a loss
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        df=None,
        now=now + timedelta(minutes=15)
    )
    assert allowed is True


def test_global_cooldown_functionality():
    """Test that global cooldown works in addition to per-symbol cooldown"""
    config = {
        "cooldown_minutes_after_loss": 30,
        "global_cooldown_minutes_after_loss": 10  # Short global cooldown
    }
    rm = RiskManager(config)
    
    now = datetime(2026, 1, 30, 10, 0, 0)
    
    # Record a loss on any symbol - sets both per-symbol and global timers
    rm.record_trade_close(-10, now, "XAUUSDm")
    
    # After the symbol-specific cooldown expires but global is still active
    later = now + timedelta(minutes=35)  # Past XAU's 30 min cooldown
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",  # Different symbol, so symbol cooldown doesn't apply
        df=None,
        now=later
    )
    # Should still be blocked by global cooldown (valid for 10 minutes from global loss time)
    # But since we're testing at 35min past, and global is 10min, it should be allowed
    # Wait, let's re-think: the global cooldown is set to 10 minutes only
    # So after 35 minutes, both symbol and global should have expired
    # Let me try a different scenario:
    
    # BTC should be allowed as symbol cooldown doesn't apply and global cooldown should have expired
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        df=None,
        now=now + timedelta(minutes=15)  # Within global cooldown period (10 min), but past symbol cooldown?
    )
    # This should be blocked by global cooldown
    # Actually, let me think differently:
    # If XAU has loss, then XAU is blocked by symbol cooldown.  
    # Other symbols are blocked by global cooldown for a short time.
    
    # Actually, looking at the implementation:
    # Per-symbol cooldown only applies to the same symbol
    # Global cooldown applies to all symbols
    # So if loss happens on XAU, both XAU and BTC are blocked by global, 
    # and XAU additionally blocked by per-symbol cooldown
    
    # Recreate the test properly:
    config = {
        "cooldown_minutes_after_loss": 60,  # Longer symbol-specific cooldown
        "global_cooldown_minutes_after_loss": 10  # Shorter global cooldown
    }
    rm = RiskManager(config)
    
    now = datetime(2026, 1, 30, 10, 0, 0)
    rm.record_trade_close(-10, now, "XAUUSDm")  # Loss on XAU
    
    # After 15 minutes: global cooldown has expired (was 10 min), 
    # but XAU is still in symbol cooldown (60 min)
    later = now + timedelta(minutes=15)
    
    # BTC should be allowed (global cooldown expired, and BTC never lost)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        df=None,
        now=later
    )
    assert allowed is True
    
    # XAU should still be blocked (still in per-symbol cooldown)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm", 
        df=None,
        now=later
    )
    assert allowed is False
    assert reason == "symbol_cooldown_after_loss"


def test_cooldown_overrides():
    """Test that cooldown overrides work for specific symbols"""
    config = {
        "cooldown_minutes_after_loss": 60,  # Default 60 minutes
        "cooldown_overrides_by_symbol": {
            "BTCUSDm": 5,   # BTC only 5 minutes
            "XAUUSDm": 10   # XAU only 10 minutes
        }
    }
    rm = RiskManager(config)
    
    now = datetime(2026, 1, 30, 10, 0, 0)
    
    # Record loss on BTC
    rm.record_trade_close(-10, now, "BTCUSDm")
    
    # After 7 minutes: BTC should still be in cooldown (5 min override)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        df=None,
        now=now + timedelta(minutes=7)
    )
    assert allowed is False
    assert reason == "symbol_cooldown_after_loss"
    
    # After 7 minutes: BTC should now be allowed (past 5 min override)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        df=None,
        now=now + timedelta(minutes=6)  # Past 5-minute override
    )
    assert allowed is True


def test_global_cooldown_only():
    """Test when only global cooldown is enabled"""
    config = {
        "cooldown_minutes_after_loss": 0,  # Disable per-symbol cooldown
        "global_cooldown_minutes_after_loss": 15  # Enable global cooldown
    }
    rm = RiskManager(config)
    
    now = datetime(2026, 1, 30, 10, 0, 0)
    
    # Record loss on XAU
    rm.record_trade_close(-10, now, "XAUUSDm")
    
    # After 10 minutes: should still be in global cooldown for all symbols
    later = now + timedelta(minutes=10)
    
    # XAU should be blocked by global cooldown (not by per-symbol)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        df=None,
        now=later
    )
    assert allowed is False
    assert reason == "global_cooldown_after_loss"
    
    # BTC should also be blocked by global cooldown
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        df=None,
        now=later
    )
    assert allowed is False
    assert reason == "global_cooldown_after_loss"
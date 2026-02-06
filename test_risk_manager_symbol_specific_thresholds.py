"""
Test symbol-specific spread/slippage thresholds in RiskManager
"""
import pytest
from datetime import datetime
from core.risk.manager import RiskManager


class MockExchange:
    """Mock exchange for testing"""
    
    def __init__(self, spread_points=None, slippage_points=None):
        self.spread_points = spread_points
        self.slippage_points = slippage_points
    
    def estimate_spread_points(self, symbol: str):
        return self.spread_points
    
    def estimate_slippage_points(self, symbol: str, reference_price, side):
        return self.slippage_points


def test_symbol_specific_spread_threshold():
    """Test that symbol-specific spread threshold is used"""
    config = {
        "max_spread_points_default": 10.0,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 5.0,
            "XAUUSDm": 3.0
        }
    }
    rm = RiskManager(config)
    
    # Test BTCUSDm using symbol-specific threshold
    exchange = MockExchange(spread_points=4.0)  # Below threshold
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is True  # Should be allowed as 4.0 < 5.0
    
    exchange = MockExchange(spread_points=6.0)  # Above threshold
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is False  # Should be blocked as 6.0 > 5.0
    assert reason == "max_spread_points"


def test_fallback_to_default_spread():
    """Test fallback to default when symbol not in by_symbol dict"""
    config = {
        "max_spread_points_default": 10.0,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 5.0,
        }
    }
    rm = RiskManager(config)
    
    # Test XAUUSDm using default threshold (not in by_symbol)
    exchange = MockExchange(spread_points=9.0)  # Below default
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is True  # Should be allowed as 9.0 < 10.0
    
    exchange = MockExchange(spread_points=11.0)  # Above default
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is False  # Should be blocked as 11.0 > 10.0
    assert reason == "max_spread_points"


def test_symbol_specific_slippage_threshold():
    """Test that symbol-specific slippage threshold is used"""
    config = {
        "max_slippage_points_default": 10.0,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 5.0,
            "XAUUSDm": 3.0
        }
    }
    rm = RiskManager(config)
    
    # Test BTCUSDm using symbol-specific threshold
    exchange = MockExchange(slippage_points=4.0)  # Below threshold
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is True  # Should be allowed as 4.0 < 5.0
    
    exchange = MockExchange(slippage_points=6.0)  # Above threshold
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is False  # Should be blocked as 6.0 > 5.0
    assert reason == "max_slippage_points"


def test_fallback_to_default_slippage():
    """Test fallback to default when symbol not in by_symbol dict"""
    config = {
        "max_slippage_points_default": 10.0,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 5.0,
        }
    }
    rm = RiskManager(config)
    
    # Test XAUUSDm using default threshold (not in by_symbol)
    exchange = MockExchange(slippage_points=9.0)  # Below default
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is True  # Should be allowed as 9.0 < 10.0
    
    exchange = MockExchange(slippage_points=11.0)  # Above default
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is False  # Should be blocked as 11.0 > 10.0
    assert reason == "max_slippage_points"


def test_no_threshold_configured():
    """Test behavior when no thresholds are configured"""
    config = {}
    rm = RiskManager(config)
    
    exchange = MockExchange(spread_points=20.0, slippage_points=20.0)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is True  # Should be allowed as no thresholds to enforce


def test_both_thresholds_applied():
    """Test that both spread and slippage thresholds are applied together"""
    config = {
        "max_spread_points_default": 10.0,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 5.0
        }
    }
    rm = RiskManager(config)
    
    # Test with spread OK but slippage too high
    exchange = MockExchange(spread_points=8.0, slippage_points=6.0)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is False  # Should be blocked by slippage (6.0 > 5.0)
    assert reason == "max_slippage_points"
    
    # Test with both OK
    exchange = MockExchange(spread_points=8.0, slippage_points=4.0)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=None
    )
    assert allowed is True  # Both thresholds OK
"""
Test symbol-specific risk management and volume multipliers for BTCUSDm and XAUUSDm
"""
import pytest
from datetime import datetime, timedelta
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


def test_btc_allowed_with_higher_spread():
    """Test that BTCUSDm is allowed with spread=70 (below its limit of 80)"""
    config = {
        "max_spread_points": 30,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        },
        "max_slippage_points": 20,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        }
    }
    rm = RiskManager(config)
    
    exchange = MockExchange(spread_points=70, slippage_points=15)  # BTC spread below its limit
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is True  # Should be allowed as 70 < 80 for BTC


def test_btc_blocked_with_very_high_spread():
    """Test that BTCUSDm is blocked with spread=120 (above its limit of 80)"""
    config = {
        "max_spread_points": 30,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        },
        "max_slippage_points": 20,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        }
    }
    rm = RiskManager(config)
    
    exchange = MockExchange(spread_points=120, slippage_points=15)  # BTC spread above its limit
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is False  # Should be blocked as 120 > 80 for BTC
    assert reason == "max_spread_points"


def test_eurusdm_still_blocked_beyond_30():
    """Test that EURUSDm is still blocked beyond the default limit of 30"""
    config = {
        "max_spread_points": 30,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        },
        "max_slippage_points": 20,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        }
    }
    rm = RiskManager(config)
    
    exchange = MockExchange(spread_points=35, slippage_points=15)  # EURUSD spread above default limit
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="EURUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is False  # Should be blocked as 35 > 30 default
    assert reason == "max_spread_points"


def test_xau_accepts_more_slippage_than_eurusdm():
    """Test that XAUUSDm accepts more slippage than EURUSDm"""
    config = {
        "max_spread_points": 30,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        },
        "max_slippage_points": 20,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        }
    }
    rm = RiskManager(config)
    
    # Test XAU with slippage of 40 - should be allowed (40 < 60 limit)
    exchange = MockExchange(spread_points=10, slippage_points=40)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is True  # Should be allowed as 40 < 60 for XAU
    
    # Test EURUSD with slippage of 40 - should be blocked (40 > 20 default)
    exchange = MockExchange(spread_points=10, slippage_points=40)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="EURUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is False  # Should be blocked as 40 > 20 for EURUSD default
    assert reason == "max_slippage_points"


def test_fallback_to_default_when_symbol_not_specified():
    """Test fallback to defaults when symbol is not in per-symbol configs"""
    config = {
        "max_spread_points": 30,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,
            # XAUUSDm not specified - should use default
        },
        "max_slippage_points": 20,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            # XAUUSDm not specified - should use default
        }
    }
    rm = RiskManager(config)
    
    # Test XAU with spread of 25 - should be allowed (25 < 30 default)
    exchange = MockExchange(spread_points=25, slippage_points=15)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is True  # Should be allowed as 25 < 30 default
    
    # Test XAU with spread of 35 - should be blocked (35 > 30 default)
    exchange = MockExchange(spread_points=35, slippage_points=15)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is False  # Should be blocked as 35 > 30 default
    assert reason == "max_spread_points"


def test_btc_xau_with_higher_slippage_allowed():
    """Test that BTC and XAU allow higher slippage than other symbols"""
    config = {
        "max_slippage_points": 20,
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        }
    }
    rm = RiskManager(config)
    
    # Test BTC with slippage of 50 - should be allowed (50 < 80)
    exchange = MockExchange(slippage_points=50)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="BTCUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is True  # Should be allowed as 50 < 80
    
    # Test XAU with slippage of 50 - should be allowed (50 < 60)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="XAUUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is True  # Should be allowed as 50 < 60
    
    # Test EURUSD with slippage of 50 - should be blocked (50 > 20)
    allowed, reason = rm.allow_trade(
        signal="BUY",
        sl=100.0,
        tp=200.0,
        account_snapshot={},
        symbol="EURUSDm",
        exchange=exchange,
        df=None,
        now=datetime.now()
    )
    assert allowed is False  # Should be blocked as 50 > 20
    assert reason == "max_slippage_points"


def test_position_sizing_config_storage():
    """Test that position sizing config is stored correctly in RiskManager"""
    config = {
        "position_sizing": {
            "defaults": {
                "base_lot": 0.01
            },
            "per_symbol": {
                "BTCUSDm": {
                    "multiplier": 1.5
                },
                "XAUUSDm": {
                    "multiplier": 1.3
                }
            }
        }
    }
    rm = RiskManager(config)
    
    # Check that the position sizing configuration is stored
    assert hasattr(rm, 'position_sizing_config')
    assert 'per_symbol' in rm.position_sizing_config
    assert 'BTCUSDm' in rm.position_sizing_config['per_symbol']
    assert rm.position_sizing_config['per_symbol']['BTCUSDm']['multiplier'] == 1.5
    assert rm.position_sizing_config['per_symbol']['XAUUSDm']['multiplier'] == 1.3


if __name__ == "__main__":
    pytest.main([__file__])
"""
Updated tests for risk management with per-symbol thresholds and volume multipliers
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


def test_btc_passes_with_higher_spread():
    """BTC/USD passes with spread=70 if seuil BTC=80"""
    config = {
        "max_spread_points": 35,  # Default
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,  # Higher tolerance for BTC
            "XAUUSDm": 60
        }
    }
    rm = RiskManager(config)
    
    # BTC with spread 70 should pass (less than BTC threshold of 80)
    exchange = MockExchange(spread_points=70)
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
    assert allowed is True


def test_eurusd_blocks_if_above_default():
    """EURUSD blocks if spread=70 and default=35"""
    config = {
        "max_spread_points": 35,  # Default
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        }
    }
    rm = RiskManager(config)
    
    # EURUSD with spread 70 should be blocked (higher than default threshold of 35)
    exchange = MockExchange(spread_points=70)
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
    assert allowed is False
    assert reason == "max_spread_points"


def test_xau_passes_with_higher_slippage():
    """XAU passes with slippage=50 if seuil XAU=60"""
    config = {
        "max_slippage_points": 35,  # Default
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60  # Higher tolerance for XAU
        }
    }
    rm = RiskManager(config)
    
    # XAU with slippage 50 should pass (less than XAU threshold of 60)
    exchange = MockExchange(slippage_points=50)
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
    assert allowed is True


def test_eurusd_blocks_slippage_above_default():
    """EURUSD blocks if slippage=50 and default=35"""
    config = {
        "max_slippage_points": 35,  # Default
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        }
    }
    rm = RiskManager(config)
    
    # EURUSD with slippage 50 should be blocked (higher than default threshold of 35)
    exchange = MockExchange(slippage_points=50)
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
    assert allowed is False
    assert reason == "max_slippage_points"


def test_config_loaded_correctly():
    """Check that config is loaded properly"""
    config = {
        "max_spread_points": 35,
        "max_slippage_points": 35,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        },
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,
            "XAUUSDm": 60
        },
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
            },
            "max_lot": 0.05
        }
    }
    rm = RiskManager(config)
    
    # Check that the configuration is properly stored
    assert rm.max_spread_points_by_symbol["BTCUSDm"] == 80
    assert rm.max_slippage_points_by_symbol["XAUUSDm"] == 60
    assert rm.position_sizing_config["max_lot"] == 0.05
    assert rm.position_sizing_config["per_symbol"]["BTCUSDm"]["multiplier"] == 1.5


def test_fallback_works():
    """Check that fallback to default works when symbol not in per-symbol config"""
    config = {
        "max_spread_points": 35,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,
            # EURUSD not specified, should use default
        }
    }
    rm = RiskManager(config)
    
    # EURUSD should use default threshold (35)
    exchange = MockExchange(spread_points=40)
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
    assert allowed is False  # 40 > 35 (default)
    assert reason == "max_spread_points"


if __name__ == "__main__":
    pytest.main([__file__])
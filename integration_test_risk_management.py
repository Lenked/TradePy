"""
Integration test to verify the main requirements for BTCUSDm and XAUUSDm risk management have been met
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


def test_main_requirements_met():
    """Test that main requirements are met: BTC/XAU can trade with higher thresholds"""
    config = {
        "max_spread_points": 30,  # Global default
        "max_slippage_points": 20,  # Global default
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80,  # Higher tolerance for crypto
            "XAUUSDm": 60   # Higher tolerance for metals
        },
        "max_slippage_points_by_symbol": {
            "BTCUSDm": 80,  # Higher tolerance for crypto
            "XAUUSDm": 60   # Higher tolerance for metals
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
            }
        }
    }
    
    rm = RiskManager(config)
    
    # Verify that the position sizing config is stored properly
    assert rm.position_sizing_config is not None
    assert "BTCUSDm" in rm.position_sizing_config.get("per_symbol", {})
    assert "XAUUSDm" in rm.position_sizing_config.get("per_symbol", {})
    assert rm.position_sizing_config["per_symbol"]["BTCUSDm"]["multiplier"] == 1.5
    
    # Test 1: BTC should be allowed with spread of 70 (higher than global default of 30)
    exchange = MockExchange(spread_points=70, slippage_points=15)
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
    assert allowed is True, f"BTC should be allowed with spread 70, got blocked by: {reason}"
    
    # Test 2: BTC should be blocked with spread of 120 (higher than its limit of 80)
    exchange = MockExchange(spread_points=120, slippage_points=15)
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
    assert allowed is False, "BTC should be blocked with spread 120"
    assert reason == "max_spread_points"
    
    # Test 3: EURUSD should still be blocked with spread of 40 (above global default of 30)
    exchange = MockExchange(spread_points=40, slippage_points=10)
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
    assert allowed is False, "EURUSD should be blocked with spread 40 > 30"
    assert reason == "max_spread_points"
    
    # Test 4: XAU should be allowed with slippage of 50 (below its limit of 60)
    exchange = MockExchange(spread_points=10, slippage_points=50)
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
    assert allowed is True, f"XAU should be allowed with slippage 50, got blocked by: {reason}"
    
    # Test 5: XAU should be blocked with slippage of 70 (above its limit of 60)
    exchange = MockExchange(spread_points=10, slippage_points=70)
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
    assert allowed is False, "XAU should be blocked with slippage 70"
    assert reason == "max_slippage_points"
    
    print("✓ All main requirements validated successfully!")


def test_risk_filter_logs():
    """Test that RISK_FILTER logs are properly generated"""
    import logging
    import io
    from unittest.mock import patch
    
    config = {
        "max_spread_points": 30,
        "max_spread_points_by_symbol": {
            "BTCUSDm": 80
        }
    }
    
    rm = RiskManager(config)
    
    # Capture log output
    log_capture_string = io.StringIO()
    ch = logging.StreamHandler(log_capture_string)
    logger = logging.getLogger('core.risk.manager')  # Using the module name
    logger.setLevel(logging.INFO)
    logger.addHandler(ch)
    
    try:
        # Test that BTC is blocked by high spread
        exchange = MockExchange(spread_points=120, slippage_points=10)
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
        
        log_contents = log_capture_string.getvalue()
        # Should contain a RISK_FILTER message
        assert "RISK_FILTER" in log_contents
        assert "BTCUSDm" in log_contents
        assert "spread=120" in log_contents
        assert "limit=80" in log_contents
        
    finally:
        logger.removeHandler(ch)


if __name__ == "__main__":
    test_main_requirements_met()
    test_risk_filter_logs()
    print("✓ Integration tests passed!")
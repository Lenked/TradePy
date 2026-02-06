#!/usr/bin/env python3
"""
Final verification that the implementation works correctly
"""
import tempfile
import os
from datetime import datetime
from core.risk.manager import RiskManager


class MockExchange:
    def __init__(self, spread_points=None, slippage_points=None):
        self.spread_points = spread_points
        self.slippage_points = slippage_points
    
    def estimate_spread_points(self, symbol: str):
        return self.spread_points
    
    def estimate_slippage_points(self, symbol: str, reference_price, side):
        return self.slippage_points


def test_implementation():
    print("Testing the updated RiskManager implementation...")
    
    # Create temporary state file to avoid conflicts
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
        tmp.write('{}')  # Empty JSON
        tmp_path = tmp.name

    try:
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
            },
            "state_path": tmp_path  # Use temporary state file
        }

        rm = RiskManager(config)
        
        # Test 1: BTC should be allowed with spread 70 (below BTC threshold of 80)
        exchange = MockExchange(spread_points=70, slippage_points=15)
        allowed, reason = rm.allow_trade(
            signal="BUY",
            sl=100.0,
            tp=200.0,
            account_snapshot={},
            symbol="BTCUSDm",
            exchange=exchange,
            df=None,
            now=datetime(2026, 1, 1, 12, 0, 0)  # Fixed time to avoid conflicts
        )
        print(f"Test 1 - BTC with spread 70: {allowed}, reason: {reason}")
        assert allowed is True, f"BTC should be allowed with spread 70, got blocked by: {reason}"

        # Test 2: EURUSD should be blocked with spread 70 (above default of 35)
        exchange = MockExchange(spread_points=70, slippage_points=15)
        allowed, reason = rm.allow_trade(
            signal="BUY",
            sl=100.0,
            tp=200.0,
            account_snapshot={},
            symbol="EURUSDm",
            exchange=exchange,
            df=None,
            now=datetime(2026, 1, 1, 12, 0, 0)
        )
        print(f"Test 2 - EURUSD with spread 70: {allowed}, reason: {reason}")
        assert allowed is False, f"EURUSD should be blocked with spread 70, got allowed"
        assert reason == "max_spread_points", f"Expected max_spread_points, got {reason}"

        # Test 3: XAU should be allowed with slippage 50 (below XAU threshold of 60)
        exchange = MockExchange(spread_points=10, slippage_points=50)
        allowed, reason = rm.allow_trade(
            signal="BUY",
            sl=100.0,
            tp=200.0,
            account_snapshot={},
            symbol="XAUUSDm",
            exchange=exchange,
            df=None,
            now=datetime(2026, 1, 1, 12, 0, 0)
        )
        print(f"Test 3 - XAU with slippage 50: {allowed}, reason: {reason}")
        assert allowed is True, f"XAU should be allowed with slippage 50, got blocked by: {reason}"

        # Test 4: Config values are loaded correctly
        assert rm.max_spread_points_by_symbol["BTCUSDm"] == 80
        assert rm.max_slippage_points_by_symbol["XAUUSDm"] == 60
        assert rm.position_sizing_config["max_lot"] == 0.05
        assert rm.position_sizing_config["per_symbol"]["BTCUSDm"]["multiplier"] == 1.5
        
        print("✓ All tests passed! Implementation is working correctly.")
        
        # Verify that logs contain the expected format
        print("\nConfig loaded correctly:")
        print(f"- Default spread: {rm.max_spread_points_default}")
        print(f"- BTC spread: {rm.max_spread_points_by_symbol.get('BTCUSDm')}")
        print(f"- EURUSD uses default: {rm.max_spread_points_default}")
        print(f"- Position sizing config: {rm.position_sizing_config}")

    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == "__main__":
    test_implementation()
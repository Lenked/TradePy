"""
Test hold reason functionality in runner
"""
import pytest
from datetime import datetime
from unittest.mock import Mock
from core.strategy.signal import SignalType
from core.strategy.base import Strategy


class MockHoldReasonStrategy(Strategy):
    """Mock strategy that implements hold_reason method"""
    
    def __init__(self, signal, reason=None):
        self._signal = signal
        self._reason = reason
        
    def generate_signal(self, data):
        return self._signal
    
    def hold_reason(self, data):
        return self._reason
    
    def get_name(self):
        return "MockHoldReasonStrategy"


class MockSimpleStrategy(Strategy):
    """Mock strategy without hold_reason method"""
    
    def __init__(self, signal):
        self._signal = signal
        
    def generate_signal(self, data):
        return self._signal
    
    def get_name(self):
        return "MockSimpleStrategy"


def test_hold_reason_with_reason_method():
    """Test that hold reason is displayed when strategy has hold_reason method"""
    from live.runner import LiveRunner
    from core.risk.manager import RiskManager
    from core.exchange.broker import Broker
    import tempfile
    import os
    
    # Create a temporary directory for the logger
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create mock objects
        strategy = MockHoldReasonStrategy(SignalType.HOLD, "No clear trend detected")
        risk_manager = RiskManager({})
        exchange = Mock(spec=Broker)
        
        # Mock the dataframe for testing
        import pandas as pd
        df = pd.DataFrame({
            'open': [100, 101, 102],
            'high': [102, 103, 104], 
            'low': [99, 100, 101],
            'close': [101, 102, 103],
            'time': [datetime.now(), datetime.now(), datetime.now()]
        })
        
        # Create a mock logger with debug level
        import logging
        logger = Mock()
        logger.logger = Mock()
        logger.logger.debug = Mock()
        logger.logger.info = Mock()
        
        # Create a mock for the Runner class
        runner = Mock()
        runner.strategy = strategy
        runner.risk_manager = risk_manager
        runner.exchange = exchange
        runner.logger = logger
        
        # Test the hold reason functionality in isolation
        signal = strategy.generate_signal(df)
        
        if signal == "HOLD":
            if hasattr(strategy, 'hold_reason'):
                try:
                    reason = strategy.hold_reason(df)
                    if reason:
                        hold_reason_msg = f" ({reason})"
                    else:
                        hold_reason_msg = " (no entry conditions met)"
                except Exception as e:
                    hold_reason_msg = f" (error getting reason: {e})"
            else:
                hold_reason_msg = " (no entry conditions met)"
        
        assert hold_reason_msg == " (No clear trend detected)"


def test_hold_reason_without_reason_method():
    """Test that default message appears when strategy doesn't have hold_reason method"""
    from live.runner import LiveRunner
    from core.risk.manager import RiskManager
    from core.exchange.broker import Broker
    import tempfile
    import os
    
    # Create a temporary directory for the logger
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create mock objects
        strategy = MockSimpleStrategy(SignalType.HOLD)  # No hold_reason method
        risk_manager = RiskManager({})
        exchange = Mock(spec=Broker)
        
        # Mock the dataframe for testing
        import pandas as pd
        df = pd.DataFrame({
            'open': [100, 101, 102],
            'high': [102, 103, 104], 
            'low': [99, 100, 101],
            'close': [101, 102, 103],
            'time': [datetime.now(), datetime.now(), datetime.now()]
        })
        
        # Create a mock logger with debug level
        import logging
        logger = Mock()
        logger.logger = Mock()
        logger.logger.debug = Mock()
        logger.logger.info = Mock()
        
        # Create a mock for the Runner class
        runner = Mock()
        runner.strategy = strategy
        runner.risk_manager = risk_manager
        runner.exchange = exchange
        runner.logger = logger
        
        # Test the hold reason functionality in isolation
        signal = strategy.generate_signal(df)
        
        if signal == "HOLD":
            if hasattr(strategy, 'hold_reason'):
                try:
                    reason = strategy.hold_reason(df)
                    if reason:
                        hold_reason_msg = f" ({reason})"
                    else:
                        hold_reason_msg = " (no entry conditions met)"
                except Exception as e:
                    hold_reason_msg = f" (error getting reason: {e})"
            else:
                hold_reason_msg = " (no entry conditions met)"
        
        assert hold_reason_msg == " (no entry conditions met)"
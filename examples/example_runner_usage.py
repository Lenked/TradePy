"""
Example of how to use the Live Runner
This is a basic example showing how to set up and run the live trading system
"""
import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live.runner import LiveRunner
from core.execution.mt5_executor import MT5Executor


def main():
    """Example of how to use the Live Runner"""
    print("Setting up Live Trading System...")
    
    # Initialize the MT5 executor
    executor = MT5Executor()
    
    # Note: In a real implementation, you would need to provide:
    # - A strategy object with generate_signal() and calculate_trade_parameters() methods
    # - A risk manager with check_risk_conditions() method  
    # - A kill switch with should_stop() method
    # 
    # For this example, we'll show the basic structure:
    
    # Example placeholder classes (these would need real implementations):
    class DummyStrategy:
        def generate_signal(self, df):
            # This would implement your trading strategy logic
            return "HOLD"  # Placeholder
        
        def calculate_trade_parameters(self, df, signal):
            # This would calculate trade parameters based on strategy
            return None  # Placeholder
    
    class DummyRiskManager:
        def check_risk_conditions(self, account_info, signal):
            # This would implement risk management logic
            return True  # Placeholder
    
    class DummyKillSwitch:
        def should_stop(self):
            # This would implement emergency stop logic
            return False  # Placeholder
    
    # Create dummy instances (replace with real implementations)
    strategy = DummyStrategy()
    risk_manager = DummyRiskManager()
    kill_switch = DummyKillSwitch()
    
    # Initialize the live runner
    runner = LiveRunner(
        strategy=strategy,
        executor=executor,
        risk_manager=risk_manager,
        kill_switch=kill_switch
    )
    
    # Run the live trading system
    # The runner will continuously:
    # 1. Sync account info (equity)
    # 2. Get market rates
    # 3. Generate signals on closed bars only
    # 4. Check risk conditions and kill switch
    # 5. Execute trades via the MT5 executor if conditions are met
    # 6. Log status information
    
    print("Starting live trading runner...")
    print("Press Ctrl+C to stop")
    
    try:
        runner.run(symbol="EURUSDm", check_interval=5)
    except KeyboardInterrupt:
        print("\nStopping live trading...")
    finally:
        executor.shutdown()


if __name__ == "__main__":
    main()
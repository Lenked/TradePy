"""
Example of how to use the Live Runner with auto-symbol selection and a simple strategy
"""
import sys
import os
import time
from datetime import datetime

# Add the project root to the path to ensure modules can be imported
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from live.runner import LiveRunner
from core.execution.mt5_executor import MT5Executor


def main():
    """Example of how to use the Live Runner with auto-symbol selection"""
    print("Setting up Live Trading System with auto-symbol selection...")

    # Initialize the MT5 executor
    exchange = MT5Executor()

    # Example placeholder classes (these would need real implementations):
    class EMATradingStrategy:
        def __init__(self, dry_run=True):
            self.dry_run = dry_run
            self.last_minute_logged = None

        def generate_signal(self, df):
            # Simple EMA crossover strategy using closed bars only
            if len(df) < 200:  # Need enough data
                return "HOLD"

            # Calculate EMAs
            df_copy = df.copy()
            df_copy['ema_fast'] = df_copy['close'].ewm(span=50).mean()
            df_copy['ema_slow'] = df_copy['close'].ewm(span=200).mean()

            # Use closed bars only (iloc[-2] is the last completed bar, iloc[-3] is the one before)
            if len(df_copy) < 3:
                return "HOLD"

            current_bar = df_copy.iloc[-2]  # Last completed bar
            prev_bar = df_copy.iloc[-3]    # Previous completed bar

            # Buy signal: EMA fast crosses above EMA slow on the current completed bar
            if (current_bar['ema_fast'] > current_bar['ema_slow'] and
                prev_bar['ema_fast'] <= prev_bar['ema_slow']):
                return "BUY"

            # Sell signal: EMA fast crosses below EMA slow on the current completed bar
            elif (current_bar['ema_fast'] < current_bar['ema_slow'] and
                  prev_bar['ema_fast'] >= prev_bar['ema_slow']):
                return "SELL"

            return "HOLD"

        def compute_sl_tp(self, df, signal):
            # Simple SL/TP based on ATR using closed bars
            if len(df) < 15:
                return 0.0, 0.0

            # Calculate ATR for stop loss and take profit
            df_copy = df.copy()
            high_low = df_copy['high'] - df_copy['low']
            high_close = abs(df_copy['high'] - df_copy['close'].shift())
            low_close = abs(df_copy['low'] - df_copy['close'].shift())
            true_range = high_low.combine(high_close, max).combine(low_close, max)
            atr = true_range.tail(14).mean()

            # Use the last completed bar for price
            current_price = df_copy.iloc[-2]['close']  # Use closed bar, not current incomplete bar

            if signal == "BUY":
                sl = current_price - (2 * atr)
                tp = current_price + (3 * atr)
            else:  # SELL
                sl = current_price + (2 * atr)
                tp = current_price - (3 * atr)

            return sl, tp

        def compute_volume(self, df, signal, equity):
            # Risk 0.5% of equity per trade
            risk_pct = 0.005
            risk_amount = equity * risk_pct

            # Simple volume calculation (adjust based on symbol characteristics)
            current_price = df.iloc[-2]['close']  # Use closed bar, not current incomplete bar
            # Approximate pip value and lot size calculation
            # This is a simplified version - adjust based on symbol
            return 0.01  # Minimum lot size as placeholder

        def log_status_every_minute(self):
            """Display active symbol and status every minute"""
            current_minute = datetime.now().minute
            if self.last_minute_logged != current_minute:
                self.last_minute_logged = current_minute
                if current_minute % 1 == 0:  # Every minute
                    print(f"[{datetime.now()}] Active Symbol Status Display")

    class DummyRiskManager:
        def allow_trade(self, signal, sl, tp, account_snapshot):
            # This would implement risk management logic
            return True, "ok"  # Placeholder

    class DummyKillSwitch:
        def evaluate(self, metrics):
            # This would implement emergency stop logic
            # Return a dictionary with a 'triggered' key
            return {"triggered": False}  # Placeholder

    # Create strategy instance with dry_run enabled
    strategy = EMATradingStrategy(dry_run=True)
    risk_manager = DummyRiskManager()
    kill_switch = DummyKillSwitch()

    # Import MetaTrader5 for the timeframe constant
    import MetaTrader5 as mt5

    # Initialize the live runner with AUTO symbol selection
    runner = LiveRunner(
        strategy=strategy,
        exchange=exchange,
        risk_manager=risk_manager,
        kill_switch=kill_switch,
        symbol="AUTO",  # Auto-select symbol based on day of week
        timeframe=mt5.TIMEFRAME_M15,  # 15-minute timeframe
        poll_seconds=5
    )

    # Run the live trading system
    # The runner will continuously:
    # 1. Sync account info (equity)
    # 2. Reset daily metrics if needed
    # 3. Select symbols based on day of week (Sat/Sun: BTCUSDm only, Mon-Fri: all symbols)
    # 4. Get market rates for each symbol in rotation
    # 5. Only act on new closed bars
    # 6. Check if any positions exist globally (max 1 trade constraint)
    # 7. Generate signals only on closed bars after startup grace period
    # 8. Check risk conditions and kill switch
    # 9. Execute trades if conditions are met
    # 10. Log status information with day, symbols_scanned, chosen_symbol, balance/equity/floating/dailyPnL

    print("Starting live trading runner with auto-symbol selection...")
    print("Symbols by day: Sat/Sun: [BTCUSDm], Mon-Fri: [BTCUSDm, XAUUSDm, EURUSDm, USOILm, NVDAm]")
    print("Press Ctrl+C to stop")

    try:
        runner.run()
    except KeyboardInterrupt:
        print("\nStopping live trading...")
    finally:
        exchange.shutdown()


if __name__ == "__main__":
    main()

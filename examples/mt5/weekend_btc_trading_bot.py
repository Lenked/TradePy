"""
Weekend Live Trading Bot for BTCUSDm
Specifically designed for weekend trading with strict risk management
"""
import os
import sys
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timedelta
import logging
import time
from typing import Dict, List, Tuple, Optional
import warnings
from dotenv import load_dotenv
warnings.filterwarnings('ignore')

# Load environment variables from .env file
load_dotenv()


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('weekend_btc_trading.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class WeekendBTCTradingBot:
    """
    Weekend BTC Trading Bot
    Trades BTCUSDm only on weekends with strict risk management
    """
    
    def __init__(self, login: int, password: str, server: str, initial_capital: float = 500):
        self.login = login
        self.password = password
        self.server = server
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.max_risk_per_trade = 0.005  # 0.5%
        self.max_daily_drawdown = 0.015  # 1.5%
        self.max_simultaneous_trades = 1
        self.atr_period = 14
        
        # Trading parameters
        self.asset = "BTCUSDm"
        self.timeframe = mt5.TIMEFRAME_M15
        self.ema_fast = 50
        self.ema_slow = 200
        
        # State tracking
        self.open_positions = []
        self.trade_history = []
        self.daily_pnl = 0.0
        self.daily_start_capital = initial_capital
        self.last_bar_time = None

        # Cooldown settings
        self.cooldown_bars = 4
        self.last_trade_bar_time = None

        # Connect to MT5
        self._connect_mt5()
        
    def _connect_mt5(self):
        """Connect to MT5 with provided credentials"""
        if not mt5.initialize():
            logger.error(f"Failed to initialize MT5: {mt5.last_error()}")
            raise ConnectionError(f"MT5 initialization failed: {mt5.last_error()}")

        authorized = mt5.login(
            login=self.login,
            password=self.password,
            server=self.server
        )

        if not authorized:
            logger.error(f"Failed to login to MT5: {mt5.last_error()}")
            mt5.shutdown()
            raise ConnectionError(f"MT5 login failed: {mt5.last_error()}")

        logger.info(f"Successfully connected to MT5 account {self.login}")

    def is_new_closed_bar(self, df: pd.DataFrame) -> bool:
        """Check if a new bar has closed since the last check"""
        if df.empty or len(df) < 2:
            return False

        # Get the second-to-last bar time (the most recently closed bar)
        closed_bar_time = df.index[-2]

        # Compare with the last processed bar time
        if self.last_bar_time is None:
            # First run, set the last bar time and return True to allow initial processing
            self.last_bar_time = closed_bar_time
            return True

        # Return True if the closed bar is newer than the last processed bar
        is_new = closed_bar_time > self.last_bar_time
        if is_new:
            self.last_bar_time = closed_bar_time
        return is_new
        
    def _is_weekend(self) -> bool:
        """Check if current day is weekend (Saturday=5, Sunday=6)"""
        current_day = datetime.now().weekday()
        return current_day >= 5  # Saturday (5) or Sunday (6)
    
    def get_current_data(self, count: int = 200) -> pd.DataFrame:
        """Get current market data for BTCUSDm"""
        rates = mt5.copy_rates_from_pos(self.asset, self.timeframe, 0, count)
        
        if rates is None or len(rates) == 0:
            logger.error(f"No current data received for {self.asset}")
            return pd.DataFrame()
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.sort_index(inplace=True)
        
        return df
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate EMA50, EMA200, ATR and other indicators"""
        df = df.copy()
        
        # Calculate EMAs
        df[f'EMA{self.ema_fast}'] = df['close'].ewm(span=self.ema_fast).mean()
        df[f'EMA{self.ema_slow}'] = df['close'].ewm(span=self.ema_slow).mean()
        
        # Calculate ATR for dynamic stop loss
        df['high_low'] = df['high'] - df['low']
        df['high_close'] = np.abs(df['high'] - df['close'].shift())
        df['low_close'] = np.abs(df['low'] - df['close'].shift())
        df['true_range'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
        df[f'ATR{self.atr_period}'] = df['true_range'].rolling(window=self.atr_period).mean()
        
        # Calculate signals
        df['bullish_cross'] = (df[f'EMA{self.ema_fast}'] > df[f'EMA{self.ema_slow}']) & \
                             (df[f'EMA{self.ema_fast}'].shift(1) <= df[f'EMA{self.ema_slow}'].shift(1))
        
        df['bearish_cross'] = (df[f'EMA{self.ema_fast}'] < df[f'EMA{self.ema_slow}']) & \
                             (df[f'EMA{self.ema_fast}'].shift(1) >= df[f'EMA{self.ema_slow}'].shift(1))
        
        # Additional signal conditions
        df['price_above_fast_ema'] = df['close'] > df[f'EMA{self.ema_fast}']
        df['price_below_fast_ema'] = df['close'] < df[f'EMA{self.ema_fast}']
        
        return df
    
    def generate_signal(self, df: pd.DataFrame) -> str:
        """Generate trading signal based on EMA crossover strategy using closed bar"""
        if df.empty or len(df) < max(self.ema_slow, self.atr_period) or len(df) < 2:
            return "HOLD"

        # Calculate indicators first
        df = self.calculate_indicators(df)

        # Use the closed bar (second to last row) for signal generation
        closed_bar = df.iloc[-2]

        # Check if we already have an open position in MT5
        if self.has_open_position_mt5():
            return "HOLD"

        # BUY signal: Bullish cross on closed bar AND price above EMA50 on closed bar
        if (closed_bar['bullish_cross'] and
            closed_bar['price_above_fast_ema']):
            return "BUY"

        # SELL signal: Bearish cross on closed bar AND price below EMA50 on closed bar
        elif (closed_bar['bearish_cross'] and
              closed_bar['price_below_fast_ema']):
            return "SELL"

        return "HOLD"
    
    def calculate_atr_based_sl_tp(self, df: pd.DataFrame, direction: str) -> Tuple[float, float]:
        """Calculate ATR-based stop loss and take profit levels"""
        # Calculate indicators first
        df = self.calculate_indicators(df)
        
        current_price = df.iloc[-1]['close']
        atr_value = df.iloc[-1][f'ATR{self.atr_period}']
        
        if pd.isna(atr_value) or atr_value == 0:
            # Fallback to 1% of price if ATR is not available
            atr_value = current_price * 0.01
        
        # Calculate stop loss based on ATR
        if direction == "BUY":
            sl_price = current_price - (2 * atr_value)  # 2x ATR for stop loss
            tp_price = current_price + (3 * atr_value)  # 3x ATR for take profit (1.5:1 ratio)
        else:  # SELL
            sl_price = current_price + (2 * atr_value)  # 2x ATR for stop loss
            tp_price = current_price - (3 * atr_value)  # 3x ATR for take profit (1.5:1 ratio)
        
        return sl_price, tp_price
    
    def calculate_position_size(self, risk_amount: float, sl_distance: float) -> float:
        """Calculate position size based on risk management for BTC"""
        # For BTC, assuming standard lot size and pip value
        # BTC pip value is typically $1 per 0.01 lot
        if sl_distance == 0:
            return 0.01  # Minimum lot size
        
        # Calculate lot size based on risk
        # For BTC: risk_amount / (sl_distance * 10) where 10 is pip value approximation
        lot_size = risk_amount / (sl_distance * 10)  # Adjust pip value as needed
        
        # Normalize lot size to MT5 requirements (0.01 minimum, 0.01 increment)
        lot_size = round(lot_size, 2)
        if lot_size < 0.01:
            lot_size = 0.01
            
        # Apply broker limits for BTC
        max_lot_size = 10.0  # Adjust based on broker's maximum
        return min(lot_size, max_lot_size)
    
    def check_risk_management(self, df: pd.DataFrame) -> bool:
        """Check if current conditions allow for new trades"""
        # Check if it's weekend
        if not self._is_weekend():
            logger.warning("Not weekend - stopping trading")
            return False

        # Check daily drawdown
        if self.daily_pnl < -(self.daily_start_capital * self.max_daily_drawdown):
            logger.error(f"Daily drawdown limit exceeded: {self.daily_pnl/self.daily_start_capital*100:.2f}% - STOPPING IMMEDIATELY")
            return False

        # Check maximum simultaneous trades
        if len(self.open_positions) >= self.max_simultaneous_trades:
            logger.debug("Maximum simultaneous trades reached")
            return False

        # Check cooldown period after last trade
        if self.last_trade_bar_time is not None and df.index[-2] is not None:
            # Count how many bars have passed since the last trade
            current_bar_time = df.index[-2]  # Use the closed bar time
            # Find the index difference between current bar and last trade bar
            if hasattr(df.index, 'get_loc'):
                try:
                    current_idx = df.index.get_loc(current_bar_time)
                    last_trade_idx = df.index.get_loc(self.last_trade_bar_time)
                    bars_since_last_trade = current_idx - last_trade_idx

                    if bars_since_last_trade < self.cooldown_bars:
                        logger.debug(f"Cooldown active: {bars_since_last_trade}/{self.cooldown_bars} bars passed since last trade")
                        return False
                except KeyError:
                    # If times are not exactly in the index, find the closest
                    time_diff = (current_bar_time - self.last_trade_bar_time).total_seconds()
                    # Assuming M15 timeframe (900 seconds), calculate approximate bars
                    approx_bars = int(time_diff / 900)
                    if approx_bars < self.cooldown_bars:
                        logger.debug(f"Cooldown active: ~{approx_bars}/{self.cooldown_bars} bars passed since last trade")
                        return False

        return True
    
    def has_open_position_mt5(self) -> bool:
        """Check if there are open positions in MT5 for the current asset"""
        positions = mt5.positions_get(symbol=self.asset)
        return positions is not None and len(positions) > 0

    def place_order(self, symbol: str, action: str, volume: float, sl: float, tp: float, price: float):
        """Place a market order for BTC with MT5-compliant comment"""
        # Create MT5-compliant comment: max 31 chars, no special characters
        timestamp = datetime.now().strftime('%d%b%H%M')  # e.g., "25Jan1430"
        comment = f"WKBTC-{action}-{timestamp}"[:31]  # Ensure max 31 characters

        if action == "BUY":
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": mt5.ORDER_TYPE_BUY,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": 234000,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
        else:  # SELL
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": mt5.ORDER_TYPE_SELL,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": 234000,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }

        result = mt5.order_send(request)
        if result is None:
            logger.error(f"Order failed: Result is None - MT5 Error: {mt5.last_error()}")
            return False
        elif result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed: {result.retcode} - {result.comment}")
            return False
        else:
            logger.info(f"Order placed successfully: {action} {volume} lots at {price}, SL: {sl}, TP: {tp}")
            return True
    
    def execute_trade(self, df: pd.DataFrame, signal: str):
        """Execute a trade based on signal and risk management"""
        if not self.check_risk_management(df):
            return

        current_price = df.iloc[-1]['close']

        # Calculate stop loss and take profit
        sl_price, tp_price = self.calculate_atr_based_sl_tp(df, signal)

        # Calculate position size based on risk
        risk_amount = self.current_capital * self.max_risk_per_trade
        sl_distance = abs(current_price - sl_price)
        lot_size = self.calculate_position_size(risk_amount, sl_distance)

        # Place the order
        success = self.place_order(
            symbol=self.asset,
            action=signal,
            volume=lot_size,
            sl=sl_price,
            tp=tp_price,
            price=current_price
        )

        if success:
            # Record the bar time when the trade was executed for cooldown purposes
            self.last_trade_bar_time = df.index[-2]  # Use the closed bar time

            # Create trade record
            trade = {
                'timestamp': datetime.now(),
                'symbol': self.asset,
                'action': signal,
                'entry_price': current_price,
                'stop_loss': sl_price,
                'take_profit': tp_price,
                'lot_size': lot_size,
                'capital_before': self.current_capital,
                'status': 'OPEN'
            }

            self.open_positions.append(trade)
            self.trade_history.append(trade)

            logger.info(f"NEW {signal} TRADE OPENED:")
            logger.info(f"  Asset: {self.asset}")
            logger.info(f"  Entry Price: {current_price:.5f}")
            logger.info(f"  Stop Loss: {sl_price:.5f}")
            logger.info(f"  Take Profit: {tp_price:.5f}")
            logger.info(f"  Position Size: {lot_size} lots")
            logger.info(f"  Capital Before: ${self.current_capital:.2f}")
        else:
            logger.error("Failed to execute trade")
    
    def monitor_positions(self):
        """Monitor open positions and check for closure conditions"""
        # Get current MT5 positions for the asset
        mt5_positions = mt5.positions_get(symbol=self.asset)

        if mt5_positions is None or len(mt5_positions) == 0:
            # No positions in MT5, clear our local tracking if needed
            if self.open_positions:
                logger.info("No positions in MT5, clearing local position tracking")
                self.open_positions = []
            return

        # Get current price
        tick = mt5.symbol_info_tick(self.asset)
        if tick is None:
            logger.error(f"Could not get current tick info for {self.asset}")
            return

        # Determine current price based on position type
        current_ask = tick.ask
        current_bid = tick.bid

        # Sync our local tracking with MT5 positions
        mt5_entry_prices = {pos.price_open for pos in mt5_positions}
        local_entry_prices = {pos['entry_price'] for pos in self.open_positions}

        # Find positions that exist in our local tracking but not in MT5 (they were closed externally)
        closed_positions = []
        for position in self.open_positions[:]:  # Copy to iterate safely
            # Check if this position still exists in MT5 by comparing entry price and volume
            position_exists_in_mt5 = False
            for mt5_pos in mt5_positions:
                # Compare entry price and volume to determine if it's the same position
                if (abs(mt5_pos.price_open - position['entry_price']) < 0.001 and
                    abs(mt5_pos.volume - position['lot_size']) < 0.001):
                    position_exists_in_mt5 = True
                    break

            if not position_exists_in_mt5:
                # Position was closed, calculate PnL based on current market price
                if position['action'] == 'BUY':
                    current_price = current_bid  # Use bid price when closing a long position
                else:  # SELL
                    current_price = current_ask  # Use ask price when closing a short position

                pnl = ((current_price - position['entry_price']) * position['lot_size'] * 10
                      if position['action'] == 'BUY'
                      else (position['entry_price'] - current_price) * position['lot_size'] * 10)

                self.current_capital += pnl
                self.daily_pnl += pnl
                position['exit_price'] = current_price
                position['pnl'] = pnl
                position['status'] = 'CLOSED'
                position['exit_timestamp'] = datetime.now()

                logger.info(f"{position['action']} POSITION CLOSED:")
                logger.info(f"  Asset: {self.asset}")
                logger.info(f"  Entry: {position['entry_price']:.5f}")
                logger.info(f"  Exit: {current_price:.5f}")
                logger.info(f"  PnL: ${pnl:.2f}")
                logger.info(f"  Capital After: ${self.current_capital:.2f}")

                closed_positions.append(position)

        # Remove closed positions from open positions
        for pos in closed_positions:
            if pos in self.open_positions:
                self.open_positions.remove(pos)
    
    def check_day_change_and_close_positions(self):
        """Check if day changed and close all positions if needed"""
        today = datetime.now().date()
        if self.last_bar_time is not None and self.last_bar_time.date() != today:
            if self.open_positions:
                logger.info("Day changed - closing all positions before switching assets")
                for position in self.open_positions[:]:
                    # In a real scenario, we would close the actual trade
                    # For now, we'll just log and remove from tracking
                    logger.info(f"Closing position due to day change: {position}")
                    self.open_positions.remove(position)
    
    def reset_daily_stats(self):
        """Reset daily statistics at the start of a new day"""
        today = datetime.now().date()
        if self.last_bar_time is None or self.last_bar_time.date() != today:
            self.daily_pnl = 0
            self.daily_start_capital = self.current_capital
            logger.info(f"Daily stats reset for {today}. Starting capital: ${self.current_capital:.2f}")
    
    def get_account_info(self):
        """Get current account information"""
        account_info = mt5.account_info()
        if account_info is not None:
            self.current_capital = account_info.balance
        else:
            logger.error("Could not get account info")
    
    def run_live_trading(self):
        """Run the live trading bot"""
        logger.info("="*60)
        logger.info("STARTING WEEKEND BTC TRADING BOT")
        logger.info("="*60)
        logger.info(f"Initial capital: ${self.initial_capital}")
        logger.info(f"Risk per trade: {self.max_risk_per_trade*100}%")
        logger.info(f"Max daily drawdown: {self.max_daily_drawdown*100}%")
        logger.info(f"Asset: {self.asset}")
        logger.info(f"Timeframe: M15")
        logger.info(f"Strategy: EMA50/EMA200 crossover")
        logger.info(f"Current day: {datetime.now().strftime('%A, %Y-%m-%d')}")
        logger.info("="*60)
        
        try:
            while True:
                # Check if it's still weekend
                if not self._is_weekend():
                    logger.info("Weekend ended - stopping trading for now")
                    break
                
                # Check for day change and close positions if needed
                self.check_day_change_and_close_positions()
                
                # Reset daily stats if new day
                self.reset_daily_stats()
                
                # Get current data
                df = self.get_current_data(count=200)
                if df.empty:
                    logger.warning(f"No data received for {self.asset}, waiting...")
                    time.sleep(30)
                    continue
                
                # Update last bar time
                self.last_bar_time = df.index[-1]
                
                # Monitor existing positions
                self.monitor_positions()
                
                # Check for new signals only if no position is open in MT5
                if not self.has_open_position_mt5():
                    # Only generate signal if a new bar has closed since last check
                    if self.is_new_closed_bar(df):
                        signal = self.generate_signal(df)
                        if signal != "HOLD":
                            # Check risk management with cooldown
                            if self.check_risk_management(df):
                                logger.info(f"Generated {signal} signal, executing trade...")
                                self.execute_trade(df, signal)
                
                # Log current status periodically
                if datetime.now().second % 30 == 0:  # Every 30 seconds
                    logger.info(f"STATUS: Capital=${self.current_capital:.2f}, "
                               f"Open positions={len(self.open_positions)}, "
                               f"Daily PnL=${self.daily_pnl:.2f}")
                
                # Update account info
                self.get_account_info()
                
                # Sleep for 5 seconds as specified
                time.sleep(5)
                
        except KeyboardInterrupt:
            logger.info("Trading interrupted by user")
        except Exception as e:
            logger.error(f"Error in live trading: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.generate_daily_report()
            self.cleanup()
    
    def generate_daily_report(self):
        """Generate daily performance report"""
        today = datetime.now().date()
        today_trades = [trade for trade in self.trade_history 
                       if trade['timestamp'].date() == today]
        
        total_pnl = sum(trade.get('pnl', 0) for trade in today_trades)
        winning_trades = [trade for trade in today_trades if trade.get('pnl', 0) > 0]
        losing_trades = [trade for trade in today_trades if trade.get('pnl', 0) < 0]
        
        win_rate = len(winning_trades) / len(today_trades) * 100 if today_trades else 0
        
        print(f"\n{'='*60}")
        print(f"WEEKEND BTC TRADING REPORT - {today}")
        print(f"{'='*60}")
        print(f"Asset traded: {self.asset}")
        print(f"Number of trades: {len(today_trades)}")
        print(f"Total PnL: ${total_pnl:.2f}")
        print(f"Capital remaining: ${self.current_capital:.2f}")
        print(f"Daily drawdown: {(self.daily_pnl/self.daily_start_capital)*100:.2f}%")
        print(f"Win rate: {win_rate:.2f}%")
        print(f"Winning trades: {len(winning_trades)}")
        print(f"Losing trades: {len(losing_trades)}")
        
        # Print details of today's trades
        if today_trades:
            print(f"\nTODAY'S TRADES:")
            print(f"{'#' :<3} {'Action':<6} {'Entry':<12} {'Exit':<12} {'PnL':<10} {'Status':<8}")
            print("-" * 60)
            for i, trade in enumerate(today_trades, 1):
                exit_price = trade.get('exit_price', 'N/A')
                pnl = trade.get('pnl', 0)
                print(f"{i:<3} {trade['action']:<6} {trade['entry_price']:<12.5f} "
                      f"{exit_price:<12} ${pnl:<9.2f} {trade['status']:<8}")
        
        print(f"{'='*60}")
    
    def cleanup(self):
        """Clean up MT5 connection"""
        mt5.shutdown()
        logger.info("MT5 connection closed")


def main():
    """Main function to run the Weekend BTC Trading Bot"""
    # MT5 credentials from environment variables or config
    import os
    from dotenv import load_dotenv

    # Load environment variables from .env file
    load_dotenv()

    # Get credentials from environment variables
    LOGIN = int(os.getenv('MT5_LOGIN', 0))
    PASSWORD = os.getenv('MT5_PASSWORD', '')
    SERVER = os.getenv('MT5_SERVER', '')

    # Validate credentials
    if not LOGIN or not PASSWORD or not SERVER:
        raise ValueError("MT5 credentials not properly set in environment variables or .env file")

    # Initialize bot
    bot = WeekendBTCTradingBot(
        login=LOGIN,
        password=PASSWORD,
        server=SERVER,
        initial_capital=500  # $500 as specified
    )
    
    try:
        # Run live trading
        bot.run_live_trading()
    
    except Exception as e:
        logger.error(f"Error during live trading: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean up
        bot.cleanup()


if __name__ == "__main__":
    main()
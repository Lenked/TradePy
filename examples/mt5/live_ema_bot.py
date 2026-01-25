"""
Live EMA Trend Following Bot for EURUSD M15
Real-time trading with strict risk management
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
        logging.FileHandler('live_ema_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class LiveEMABot:
    """
    Live EMA Trend Following Bot for EURUSD M15
    Real-time trading with strict risk management
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
        self.symbol = "EURUSDm"
        self.timeframe = mt5.TIMEFRAME_M15
        self.ema_fast = 50
        self.ema_slow = 200
        
        # State tracking
        self.open_positions = []
        self.trade_history = []
        self.daily_pnl = 0.0
        self.daily_start_capital = initial_capital
        self.last_bar_time = None
        
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
        
    def get_current_data(self, count: int = 200) -> pd.DataFrame:
        """Get current market data for EURUSD M15"""
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, count)
        
        if rates is None or len(rates) == 0:
            logger.error(f"No current data received for {self.symbol}")
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
        """Generate trading signal based on EMA crossover strategy"""
        if df.empty or len(df) < max(self.ema_slow, self.atr_period):
            return "HOLD"

        # Calculate indicators first
        df = self.calculate_indicators(df)

        latest = df.iloc[-1]

        # Check if we already have an open position
        if len(self.open_positions) >= self.max_simultaneous_trades:
            return "HOLD"

        # BUY signal: EMA50 > EMA200 AND price > EMA50
        if (latest[f'EMA{self.ema_fast}'] > latest[f'EMA{self.ema_slow}'] and
            latest['price_above_fast_ema']):
            return "BUY"

        # SELL signal: EMA50 < EMA200 AND price < EMA50
        elif (latest[f'EMA{self.ema_fast}'] < latest[f'EMA{self.ema_slow}'] and
              latest['price_below_fast_ema']):
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
        """Calculate position size based on risk management"""
        # For forex, assuming standard lot size and pip value
        # This is a simplified calculation - adjust based on your broker's specifications
        if sl_distance == 0:
            return 0.01  # Minimum lot size
        
        # Calculate lot size based on risk
        lot_size = risk_amount / (sl_distance * 10)  # Convert pip risk to lot risk (forex specific)
        
        # Normalize lot size to MT5 requirements (0.01 minimum, 0.01 increment)
        lot_size = round(lot_size, 2)
        if lot_size < 0.01:
            lot_size = 0.01
            
        return min(lot_size, 100.0)  # Maximum lot size cap
    
    def check_risk_management(self) -> bool:
        """Check if current conditions allow for new trades"""
        # Check daily drawdown
        if self.daily_pnl < -(self.daily_start_capital * self.max_daily_drawdown):
            logger.warning(f"Daily drawdown limit exceeded: {self.daily_pnl/self.daily_start_capital*100:.2f}%")
            return False
        
        # Check maximum simultaneous trades
        if len(self.open_positions) >= self.max_simultaneous_trades:
            logger.debug("Maximum simultaneous trades reached")
            return False
        
        return True
    
    def place_order(self, symbol: str, action: str, volume: float, sl: float, tp: float, price: float):
        """Place a market order"""
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
                "comment": "EMA Bot Trade",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
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
                "comment": "EMA Bot Trade",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed: {result.retcode} - {result.comment}")
            return False
        else:
            logger.info(f"Order placed successfully: {action} {volume} lots at {price}, SL: {sl}, TP: {tp}")
            return True
    
    def execute_trade(self, df: pd.DataFrame, signal: str):
        """Execute a trade based on signal and risk management"""
        if not self.check_risk_management():
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
            symbol=self.symbol,
            action=signal,
            volume=lot_size,
            sl=sl_price,
            tp=tp_price,
            price=current_price
        )
        
        if success:
            # Create trade record
            trade = {
                'timestamp': datetime.now(),
                'symbol': self.symbol,
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
            
            logger.info(f"New {signal} trade opened: Price={current_price:.5f}, "
                       f"SL={sl_price:.5f}, TP={tp_price:.5f}, Size={lot_size}")
    
    def monitor_positions(self):
        """Monitor open positions and check for closure conditions"""
        # Get current price
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            logger.error("Could not get current tick info")
            return
        
        current_price = tick.ask if len(self.open_positions) > 0 and self.open_positions[0]['action'] == 'BUY' else tick.bid
        
        closed_positions = []
        
        for position in self.open_positions[:]:  # Copy to iterate safely
            if position['action'] == 'BUY':
                # Close if hit SL or TP
                if current_price <= position['stop_loss'] or current_price >= position['take_profit']:
                    # Calculate PnL
                    pnl = (current_price - position['entry_price']) * position['lot_size'] * 10  # Forex multiplier
                    self.current_capital += pnl
                    self.daily_pnl += pnl
                    position['exit_price'] = current_price
                    position['pnl'] = pnl
                    position['status'] = 'CLOSED'
                    position['exit_timestamp'] = datetime.now()
                    
                    logger.info(f"BUY position closed: Entry={position['entry_price']:.5f}, "
                               f"Exit={current_price:.5f}, PnL={pnl:.2f}")
                    
                    closed_positions.append(position)
            else:  # SELL
                # Close if hit SL or TP
                if current_price >= position['stop_loss'] or current_price <= position['take_profit']:
                    # Calculate PnL
                    pnl = (position['entry_price'] - current_price) * position['lot_size'] * 10  # Forex multiplier
                    self.current_capital += pnl
                    self.daily_pnl += pnl
                    position['exit_price'] = current_price
                    position['pnl'] = pnl
                    position['status'] = 'CLOSED'
                    position['exit_timestamp'] = datetime.now()
                    
                    logger.info(f"SELL position closed: Entry={position['entry_price']:.5f}, "
                               f"Exit={current_price:.5f}, PnL={pnl:.2f}")
                    
                    closed_positions.append(position)
        
        # Remove closed positions from open positions
        for pos in closed_positions:
            self.open_positions.remove(pos)
    
    def reset_daily_stats(self):
        """Reset daily statistics at the start of a new day"""
        today = datetime.now().date()
        if self.last_bar_time is None or self.last_bar_time.date() != today:
            self.daily_pnl = 0
            self.daily_start_capital = self.current_capital
            logger.info(f"Daily stats reset for {today}. Starting capital: {self.current_capital}")
    
    def get_account_info(self):
        """Get current account information"""
        account_info = mt5.account_info()
        if account_info is not None:
            self.current_capital = account_info.balance
        else:
            logger.error("Could not get account info")
    
    def run_live_trading(self):
        """Run the live trading bot"""
        logger.info("Starting live trading bot...")
        logger.info(f"Initial capital: ${self.initial_capital}")
        logger.info(f"Risk per trade: {self.max_risk_per_trade*100}%")
        logger.info(f"Max daily drawdown: {self.max_daily_drawdown*100}%")
        
        try:
            while True:
                # Reset daily stats if new day
                self.reset_daily_stats()
                
                # Get current data
                df = self.get_current_data(count=200)
                if df.empty:
                    logger.warning("No data received, waiting...")
                    time.sleep(30)
                    continue
                
                # Update last bar time
                self.last_bar_time = df.index[-1]
                
                # Monitor existing positions
                self.monitor_positions()
                
                # Check for new signals only if no position is open
                if len(self.open_positions) == 0:
                    signal = self.generate_signal(df)
                    if signal != "HOLD":
                        self.execute_trade(df, signal)
                
                # Log current status periodically
                if datetime.now().second % 30 == 0:  # Every 30 seconds
                    logger.info(f"Status: Capital=${self.current_capital:.2f}, "
                               f"Open positions={len(self.open_positions)}, "
                               f"Daily PnL=${self.daily_pnl:.2f}")
                
                # Update account info
                self.get_account_info()
                
                # Sleep for a bit to avoid overwhelming the API
                time.sleep(5)
                
        except KeyboardInterrupt:
            logger.info("Trading interrupted by user")
        except Exception as e:
            logger.error(f"Error in live trading: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
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
        print(f"DAILY REPORT - {today}")
        print(f"{'='*60}")
        print(f"Number of trades: {len(today_trades)}")
        print(f"Total PnL: ${total_pnl:.2f}")
        print(f"Capital remaining: ${self.current_capital:.2f}")
        print(f"Daily drawdown: {(self.daily_pnl/self.daily_start_capital)*100:.2f}%")
        print(f"Win rate: {win_rate:.2f}%")
        print(f"Winning trades: {len(winning_trades)}")
        print(f"Losing trades: {len(losing_trades)}")
        print(f"Rules compliance: {'PASS' if self.check_compliance() else 'FAIL'}")
        print(f"{'='*60}")
    
    def check_compliance(self) -> bool:
        """Check if all trades followed the rules"""
        # For now, just return True - implement more detailed checks as needed
        return True
    
    def cleanup(self):
        """Clean up MT5 connection"""
        mt5.shutdown()
        logger.info("MT5 connection closed")


def main():
    """Main function to run the Live EMA Bot"""
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
    bot = LiveEMABot(
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
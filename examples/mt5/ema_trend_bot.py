"""
Trend Following EMA Bot for EURUSD M15
Testing simple strategy with strict risk management
"""
import os
import sys
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timedelta
import logging
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
        logging.FileHandler('ema_trend_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class EMATrendBot:
    """
    Trend Following EMA Bot for EURUSD M15
    Implements EMA50/EMA200 crossover strategy with strict risk management
    """
    
    def __init__(self, login: int, password: str, server: str, initial_capital: float = 10000):
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
        self.symbol = "EURUSDm"  # Using EURUSDm as specified
        self.timeframe = mt5.TIMEFRAME_M15
        self.ema_fast = 50
        self.ema_slow = 200
        
        # State tracking
        self.open_positions = []
        self.trade_history = []
        self.equity_curve = [initial_capital]
        self.daily_drawdown = 0.0
        self.start_date = None
        self.end_date = None
        
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
        
    def get_historical_data(self, days: int = 180) -> pd.DataFrame:
        """Get historical data for EURUSD M15"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        self.start_date = start_date
        self.end_date = end_date

        # Check if symbol exists
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            logger.error(f"Symbol {self.symbol} not found. Available symbols:")
            symbols = mt5.symbols_get()
            eurusd_symbols = [s.name for s in symbols if 'EURUSD' in s.name]
            logger.error(f"Available EURUSD symbols: {eurusd_symbols}")
            return pd.DataFrame()
        else:
            logger.info(f"Symbol {self.symbol} found: {symbol_info.name}")

        rates = mt5.copy_rates_range(self.symbol, self.timeframe, start_date, end_date)

        if rates is None or len(rates) == 0:
            logger.error(f"No historical data received for {self.symbol}")
            logger.error(f"MT5 Error: {mt5.last_error()}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)

        logger.info(f"Retrieved {len(df)} bars of historical data for {self.symbol}")
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
    
    def generate_signal(self, row: pd.Series) -> str:
        """Generate trading signal based on EMA crossover strategy"""
        # Check if we already have an open position
        if len(self.open_positions) >= self.max_simultaneous_trades:
            return "HOLD"
        
        # BUY signal: EMA50 > EMA200 AND price > EMA50
        if (row[f'EMA{self.ema_fast}'] > row[f'EMA{self.ema_slow}'] and 
            row['price_above_fast_ema']):
            return "BUY"
        
        # SELL signal: EMA50 < EMA200 AND price < EMA50
        elif (row[f'EMA{self.ema_fast}'] < row[f'EMA{self.ema_slow}'] and 
              row['price_below_fast_ema']):
            return "SELL"
        
        return "HOLD"
    
    def calculate_atr_based_sl_tp(self, df: pd.DataFrame, idx: int, direction: str) -> Tuple[float, float]:
        """Calculate ATR-based stop loss and take profit levels"""
        current_price = df.iloc[idx]['close']
        atr_value = df.iloc[idx][f'ATR{self.atr_period}']
        
        if pd.isna(atr_value):
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
    
    def calculate_position_size(self, sl_distance: float) -> float:
        """Calculate position size based on risk management"""
        risk_amount = self.current_capital * self.max_risk_per_trade
        price_movement_per_lot = sl_distance  # Simplified assumption
        
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
        if self.daily_drawdown >= self.max_daily_drawdown:
            logger.warning("Daily drawdown limit reached, no new trades allowed")
            return False
        
        # Check maximum simultaneous trades
        if len(self.open_positions) >= self.max_simultaneous_trades:
            logger.debug("Maximum simultaneous trades reached")
            return False
        
        return True
    
    def execute_trade(self, df: pd.DataFrame, idx: int, signal: str):
        """Execute a trade based on signal and risk management"""
        if not self.check_risk_management():
            return
        
        current_price = df.iloc[idx]['close']
        
        # Calculate stop loss and take profit
        sl_price, tp_price = self.calculate_atr_based_sl_tp(df, idx, signal)
        
        # Calculate position size based on risk
        sl_distance = abs(current_price - sl_price)
        lot_size = self.calculate_position_size(sl_distance)
        
        # Create trade record
        trade = {
            'timestamp': df.index[idx],
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
    
    def check_close_conditions(self, df: pd.DataFrame, idx: int):
        """Check if any open positions should be closed"""
        current_price = df.iloc[idx]['close']
        closed_positions = []
        
        for position in self.open_positions[:]:  # Copy to iterate safely
            if position['action'] == 'BUY':
                # Close if hit SL or TP
                if current_price <= position['stop_loss'] or current_price >= position['take_profit']:
                    # Calculate PnL
                    pnl = (current_price - position['entry_price']) * position['lot_size'] * 10  # Forex multiplier
                    self.current_capital += pnl
                    position['exit_price'] = current_price
                    position['pnl'] = pnl
                    position['status'] = 'CLOSED'
                    position['exit_timestamp'] = df.index[idx]
                    
                    logger.info(f"BUY position closed: Entry={position['entry_price']:.5f}, "
                               f"Exit={current_price:.5f}, PnL={pnl:.2f}")
                    
                    closed_positions.append(position)
            else:  # SELL
                # Close if hit SL or TP
                if current_price >= position['stop_loss'] or current_price <= position['take_profit']:
                    # Calculate PnL
                    pnl = (position['entry_price'] - current_price) * position['lot_size'] * 10  # Forex multiplier
                    self.current_capital += pnl
                    position['exit_price'] = current_price
                    position['pnl'] = pnl
                    position['status'] = 'CLOSED'
                    position['exit_timestamp'] = df.index[idx]
                    
                    logger.info(f"SELL position closed: Entry={position['entry_price']:.5f}, "
                               f"Exit={current_price:.5f}, PnL={pnl:.2f}")
                    
                    closed_positions.append(position)
        
        # Remove closed positions from open positions
        for pos in closed_positions:
            self.open_positions.remove(pos)
        
        # Update equity curve
        self.equity_curve.append(self.current_capital)
    
    def run_backtest(self, days: int = 180) -> Dict:
        """Run the backtest on historical data"""
        logger.info("Starting backtest...")
        
        # Get historical data
        df = self.get_historical_data(days)
        if df.empty:
            logger.error("No data available for backtest")
            return {}
        
        # Calculate indicators
        df = self.calculate_indicators(df)
        
        # Run the backtest loop
        for idx in range(max(self.ema_slow, self.atr_period), len(df)):
            # Check if any positions should be closed
            self.check_close_conditions(df, idx)
            
            # Generate signal and execute trade if conditions are met
            signal = self.generate_signal(df.iloc[idx])
            if signal != "HOLD":
                self.execute_trade(df, idx, signal)
        
        # Close any remaining open positions at the end
        if self.open_positions:
            logger.info(f"Closing {len(self.open_positions)} remaining positions at end of backtest")
            for position in self.open_positions:
                current_price = df.iloc[-1]['close']
                if position['action'] == 'BUY':
                    pnl = (current_price - position['entry_price']) * position['lot_size'] * 10
                else:
                    pnl = (position['entry_price'] - current_price) * position['lot_size'] * 10
                
                self.current_capital += pnl
                position['exit_price'] = current_price
                position['pnl'] = pnl
                position['status'] = 'CLOSED'
                position['exit_timestamp'] = df.index[-1]
        
        # Calculate final metrics
        results = self.calculate_metrics()
        
        logger.info("Backtest completed successfully")
        return results
    
    def calculate_metrics(self) -> Dict:
        """Calculate performance metrics"""
        closed_trades = [trade for trade in self.trade_history if trade.get('pnl') is not None]
        
        if not closed_trades:
            logger.warning("No closed trades to analyze")
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'max_drawdown': 0.0,
                'final_capital': self.current_capital,
                'profit_factor': 0.0,
                'closed_trades': [],
                'equity_curve': self.equity_curve
            }
        
        # Calculate basic metrics
        total_pnl = sum(trade['pnl'] for trade in closed_trades)
        winning_trades = [trade for trade in closed_trades if trade['pnl'] > 0]
        losing_trades = [trade for trade in closed_trades if trade['pnl'] < 0]
        
        win_rate = len(winning_trades) / len(closed_trades) if closed_trades else 0
        
        # Calculate max drawdown
        peak = self.initial_capital
        max_dd = 0
        current_equity = self.initial_capital
        
        for trade in closed_trades:
            current_equity += trade['pnl']
            if current_equity > peak:
                peak = current_equity
            dd = (peak - current_equity) / peak
            if dd > max_dd:
                max_dd = dd
        
        # Calculate profit factor
        gross_profit = sum(trade['pnl'] for trade in winning_trades)
        gross_loss = abs(sum(trade['pnl'] for trade in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')
        
        results = {
            'total_trades': len(closed_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'max_drawdown': max_dd,
            'final_capital': self.current_capital,
            'profit_factor': profit_factor,
            'closed_trades': closed_trades,
            'equity_curve': self.equity_curve
        }
        
        return results
    
    def generate_report(self, results: Dict):
        """Generate detailed backtest report"""
        print("\n" + "="*60)
        print("TREND FOLLOWING EMA BOT - BACKTEST RESULTS")
        print("="*60)
        
        print(f"Initial Capital: ${self.initial_capital:,.2f}")
        print(f"Final Capital: ${results['final_capital']:,.2f}")
        print(f"Total Return: {(results['final_capital'] - self.initial_capital) / self.initial_capital * 100:.2f}%")
        
        print(f"\nTotal Trades: {results['total_trades']}")
        print(f"Winning Trades: {results['winning_trades']}")
        print(f"Losing Trades: {results['losing_trades']}")
        print(f"Win Rate: {results['win_rate'] * 100:.2f}%")
        
        print(f"\nTotal PnL: ${results['total_pnl']:.2f}")
        print(f"Max Drawdown: {results['max_drawdown'] * 100:.2f}%")
        print(f"Profit Factor: {results['profit_factor']:.2f}")
        
        print(f"\nEquity Curve Points: {len(results['equity_curve'])}")
        print(f"Starting Equity: ${results['equity_curve'][0]:,.2f}")
        print(f"Ending Equity: ${results['equity_curve'][-1]:,.2f}")
        
        print("\nDetailed Trade Log:")
        print("-" * 80)
        print(f"{'#':<3} {'Action':<6} {'Entry':<10} {'Exit':<10} {'PnL':<10} {'Status':<8}")
        print("-" * 80)
        
        for i, trade in enumerate(results['closed_trades'][:20], 1):  # Show first 20 trades
            pnl_str = f"${trade['pnl']:.2f}"
            print(f"{i:<3} {trade['action']:<6} {trade['entry_price']:<10.5f} "
                  f"{trade.get('exit_price', 'N/A'):<10} {pnl_str:<10} {trade['status']:<8}")
        
        if len(results['closed_trades']) > 20:
            print(f"... and {len(results['closed_trades']) - 20} more trades")
        
        print("\nRisk Management Summary:")
        print(f"- Max Risk per Trade: {self.max_risk_per_trade * 100:.1f}%")
        print(f"- Max Daily Drawdown: {self.max_daily_drawdown * 100:.1f}%")
        print(f"- Max Simultaneous Trades: {self.max_simultaneous_trades}")
        
        print("\nSystem Evaluation:")
        if results['final_capital'] > self.initial_capital * 0.985:  # Allow for 1.5% drawdown
            print("[SUCCESS] SYSTEM SURVIVED: Capital preserved within acceptable limits")
        else:
            print("[FAILED] SYSTEM FAILED: Exceeded maximum acceptable drawdown")

        if results['win_rate'] > 0.35:  # More than 35% win rate
            print("[SUCCESS] REASONABLE WIN RATE: Above 35% threshold")
        else:
            print("[WARNING] LOW WIN RATE: Below 35% threshold")

        if results['profit_factor'] > 1.2:
            print("[SUCCESS] PROFIT FACTOR: Above 1.2 threshold")
        else:
            print("[WARNING] PROFIT FACTOR: Below 1.2 threshold")
        
        print("="*60)
    
    def cleanup(self):
        """Clean up MT5 connection"""
        mt5.shutdown()
        logger.info("MT5 connection closed")


def main():
    """Main function to run the EMA Trend Bot"""
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
    bot = EMATrendBot(
        login=LOGIN,
        password=PASSWORD,
        server=SERVER,
        initial_capital=10000
    )
    
    try:
        # Run backtest
        results = bot.run_backtest(days=180)  # 6 months of data
        
        # Generate report
        if results:
            bot.generate_report(results)
        else:
            logger.error("Backtest failed to produce results")
    
    except Exception as e:
        logger.error(f"Error during backtest: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean up
        bot.cleanup()


if __name__ == "__main__":
    main()
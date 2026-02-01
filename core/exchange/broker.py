"""
Broker implementation for exchange operations
"""
from .interface import ExchangeInterface
import pandas as pd
from typing import Optional
from ..models import AccountSnapshot, OrderResult
import time


class Broker(ExchangeInterface):
    """Concrete broker implementation (simulator)"""
    
    def __init__(self, config):
        self.config = config
        self.connected = False
        self.initial_capital = config.get('initial_capital', 10000)
        self.current_balance = self.initial_capital
        self.current_equity = self.initial_capital
        # Change to list to store multiple positions per symbol
        self._positions = []  # List of position dictionaries
        self.orders_history = []
        self.simulated_data = {}
        
        # Get dry_run setting from config
        trading_config = config.get('trading', {})
        self.dry_run = trading_config.get('dry_run', True)
        
        # Initialize logger
        try:
            from ...utils.logger import get_logger
            self.logger = get_logger("Broker")
        except:
            # Fallback if path is wrong
            from utils.logger import get_logger
            self.logger = get_logger("Broker")
        
        # Track last order time per symbol to prevent duplicates on same candle
        self._last_order_times = {}
        
    def connect(self) -> bool:
        """Connect to the exchange"""
        # Simulate connection
        self.connected = True
        print("Connected to Demo/Simulated Exchange")
        return True

    def shutdown(self) -> None:
        """Shutdown connection to the exchange"""
        self.connected = False
        print("Disconnected from Demo/Simulated Exchange")

    def account_info(self) -> AccountSnapshot:
        """Get account snapshot information"""
        # Return an AccountSnapshot with simulated values
        from ..models import AccountSnapshot
        
        return AccountSnapshot(
            balance=self.current_balance,
            equity=self.current_equity,
            margin=0,
            free_margin=self.current_balance
        )

    def get_rates(self, symbol: str, timeframe: int, count: int = 300) -> pd.DataFrame:
        """Get market rates/candles for a symbol"""
        import numpy as np
        from datetime import datetime, timedelta
        
        # Convert timeframe integer to pandas frequency string
        # If timeframe comes as string instead, handle that too
        if isinstance(timeframe, int):
            # Assume timeframe is in minutes if it's an integer
            freq = f'{timeframe}min'
        elif isinstance(timeframe, str):
            # Convert timeframe string to pandas frequency
            timeframe_upper = timeframe.upper()
            if timeframe_upper.startswith('M'):  # Minutes: M1, M5, M15, etc.
                minutes = timeframe_upper[1:]  # Get the number part
                if minutes.isdigit():
                    freq = f'{minutes}min'
                else:
                    freq = '5min'  # Default to 5 minutes if parsing fails
            elif timeframe_upper.startswith('H'):  # Hours: H1, H4, etc.
                hours = timeframe_upper[1:]  # Get the number part
                if hours.isdigit():
                    freq = f'{hours}H'
                else:
                    freq = '1H'  # Default to 1 hour
            elif timeframe_upper.startswith('D'):  # Days
                freq = '1D'
            else:
                freq = '5min'  # Default fallback
        else:
            freq = '5min'  # Default fallback
        
        # Simulate market data for the requested symbol
        dates = pd.date_range(end=datetime.now(), periods=count, freq=freq)
        
        # Generate simulated OHLC data
        np.random.seed(hash(symbol) % 2**32)  # Different seed per symbol
        base_price = 1.0 + (hash(symbol) % 10000) / 10000  # Base price around 1.xxxx
        prices = [base_price]
        
        for i in range(1, count):
            change_percent = np.random.normal(0, 0.002)  # 0.2% average volatility (reduced for speed test)
            new_price = prices[-1] * (1 + change_percent)
            prices.append(new_price)
        
        # Create OHLC data
        opens = prices[:-1]
        closes = prices[1:]
        highs = [o * (1 + abs(np.random.normal(0, 0.001))) for o in opens]
        lows = [o * (1 - abs(np.random.normal(0, 0.001))) for o in opens]
        
        # Adjust high/low based on open/close
        for i in range(len(highs)):
            max_price = max(opens[i], closes[i])
            min_price = min(opens[i], closes[i])
            highs[i] = max(highs[i], max_price)
            lows[i] = min(lows[i], min_price)
        
        df = pd.DataFrame({
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': np.random.randint(1000, 5000, size=len(opens))  # Reduced volume range
        }, index=dates[1:])
        
        return df

    def positions(self, symbol: Optional[str] = None):
        """Get open positions, optionally filtered by symbol"""
        if symbol:
            return [pos for pos in self._positions if pos['symbol'] == symbol]
        else:
            return self._positions

    def floating_pnl(self, symbol: Optional[str] = None) -> float:
        """Get floating PnL for a symbol or all positions"""
        total_pnl = 0.0
        
        positions_to_check = self.positions(symbol) if symbol else self._positions
        
        for position in positions_to_check:
            # Get current price from latest market data
            try:
                latest_data = self.get_rates(position['symbol'], 5, 1)  # Get latest bar
                if not latest_data.empty:
                    current_price = float(latest_data.iloc[-1]['close'])
                    entry_price = position['entry_price']
                    volume = position['volume']
                    
                    # Calculate PnL based on position direction
                    if position['side'] == 'BUY':
                        pnl = (current_price - entry_price) * volume
                    else:  # SELL
                        pnl = (entry_price - current_price) * volume
                    
                    total_pnl += pnl
            except:
                # If we can't get current price, return 0
                continue
                
        return total_pnl

    def estimate_spread_points(self, symbol: str) -> Optional[float]:
        return 0.0

    def estimate_slippage_points(self, symbol: str, reference_price: Optional[float], side: Optional[str] = None) -> Optional[float]:
        if reference_price is None:
            return None
        try:
            rates = self.get_rates(symbol, 5, 1)
            if rates.empty:
                return None
            current_price = float(rates.iloc[-1]['close'])
        except Exception:
            return None
        point = 0.0001
        return float(abs(current_price - reference_price) / point)

    def place_market_order(self, symbol: str, side: str, volume: float, sl: float, tp: float, 
                          comment: str = "TradePy Live") -> OrderResult:
        """Place a market order with mandatory stop loss and take profit"""
        
        # Anti-duplication: Check if we already have an open position for this symbol
        existing_positions = self.positions(symbol)
        if existing_positions:
            self.logger.warning(f"Not placing new order for {symbol}: already has {len(existing_positions)} open position(s)")
            return OrderResult(success=False, message="existing_position_blocked")
        
        # Anti-duplication: Check if we just placed an order for this symbol recently (same candle)
        current_time = pd.Timestamp.now()
        if symbol in self._last_order_times:
            time_diff = current_time - self._last_order_times[symbol]
            # Prevent multiple orders on the same "bar" (using a small threshold like 10 seconds)
            if time_diff.total_seconds() < 10:
                self.logger.warning(f"Not placing order for {symbol}: order already placed {time_diff.total_seconds():.1f}s ago")
                return OrderResult(success=False, message="duplicate_order_blocked")
        
        # Check if this is a dry run
        if self.dry_run:
            self.logger.info(f"DRY_RUN_ORDER_SIMULATED - {side.upper()} {volume} {symbol} | SL: {sl} | TP: {tp} | Comment: {comment}")
            print(f"DRY_RUN_ORDER_SIMULATED - {side.upper()} {volume} {symbol} | SL: {sl} | TP: {tp}")
            return OrderResult(success=True, message="dry_run_simulated", comment=comment)
        
        # Get the current price as the entry price
        try:
            rates = self.get_rates(symbol, 5, 1)  # Get most recent bar
            if rates.empty:
                self.logger.error(f"Could not get current price for {symbol} to determine entry price")
                return OrderResult(success=False, message="missing_price")
            entry_price = float(rates.iloc[-1]['close'])
        except Exception as e:
            self.logger.error(f"Error getting entry price for {symbol}: {str(e)}")
            return OrderResult(success=False, message=f"entry_price_error: {e}")
        
        # In simulation mode (not dry run but not real MT5), log SIM_ORDER_SENT
        self.logger.info(f"SIM_ORDER_SENT - {side.upper()} {volume} {symbol} | Entry: {entry_price} | SL: {sl} | TP: {tp} | Comment: {comment}")
        print(f"SIM_ORDER_SENT - {side.upper()} {volume} {symbol} | Entry: {entry_price} | SL: {sl} | TP: {tp}")
        
        # Create a position object
        position_id = f"{symbol}_{int(current_time.timestamp())}"
        position = {
            'id': position_id,
            'symbol': symbol,
            'side': side.upper(),
            'volume': volume,
            'entry_price': entry_price,
            'sl': sl,
            'tp': tp,
            'open_time': current_time,
            'ticket': position_id,  # Using ID as ticket for simulation
            'pnl': 0.0
        }
        
        # Add position to our list
        self._positions.append(position)
        
        # Record in order history
        order = {
            'symbol': symbol,
            'side': side.upper(),
            'volume': volume,
            'entry_price': entry_price,
            'sl': sl,
            'tp': tp,
            'comment': comment,
            'timestamp': current_time,
            'status': 'filled',
            'position_id': position_id
        }
        self.orders_history.append(order)
        
        # Update last order time for this symbol
        self._last_order_times[symbol] = current_time
        
        return OrderResult(success=True, order_id=position_id, message="simulated_order", comment=comment)

    def get_historical_data(self, symbol: str, timeframe: str, start_date: str, end_date: str):
        """Get historical market data for backtesting"""
        # Implementation would go here
        pass

    def get_current_price(self, symbol: str):
        """Get current price for a symbol"""
        # Return the latest close price from our simulated data
        try:
            rates = self.get_rates(symbol, 5, 1)  # Get most recent bar
            if not rates.empty:
                return float(rates.iloc[-1]['close'])
        except:
            pass
            
        # Fallback if unable to get current price from rates
        import random
        # Return a simulated current price
        base_price = 1.0 + (hash(symbol) % 10000) / 10000
        return base_price * (1 + random.uniform(-0.001, 0.001))

    def place_order(self, symbol: str, side: str, quantity: float, order_type: str = 'market'):
        """Place an order (legacy method)"""
        # Call the main method for market orders
        if order_type == 'market':
            return self.place_market_order(symbol, side, quantity, None, None)
        else:
            # Implementation for other order types would go here
            pass

    def get_account_balance(self):
        """Get account balance"""
        return self.current_balance

    def get_open_positions(self):
        """Get open positions"""
        return self._positions

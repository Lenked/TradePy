"""
Simple Trend Following Strategy for TradePy bot
This serves as the baseline strategy for comparison with AI approaches
"""
import pandas as pd
import numpy as np
from typing import Tuple
from enum import Enum

from .base import Strategy
from .signal import SignalType


class TrendFollowingStrategy(Strategy):
    """
    Simple trend following strategy implementation based on EMA and RSI.
    
    This strategy follows the reference strategy outlined in the documentation:
    - Uses EMA 50 and EMA 200 for trend direction
    - Uses RSI 14 for momentum confirmation
    - Uses ATR for stop-loss positioning
    
    Buy signals when:
    - EMA 50 > EMA 200 (uptrend)
    - RSI > 50 (momentum)
    - Price > EMA 50 (confirmation)
    
    Sell signals when:
    - EMA 50 < EMA 200 (downtrend)
    - RSI < 50 (momentum)
    - Price < EMA 50 (confirmation)
    """
    
    def __init__(self, 
                 ema_short_period: int = 50,
                 ema_long_period: int = 200,
                 rsi_period: int = 14,
                 atr_period: int = 14,
                 sl_atr_multiplier: float = 2.0,
                 tp_atr_multiplier: float = 3.0,
                 sl_tp_overrides_by_symbol: dict = None):
        """
        Initialize the trend following strategy.
        
        Args:
            ema_short_period: Period for short EMA (default 50)
            ema_long_period: Period for long EMA (default 200)
            rsi_period: Period for RSI calculation (default 14)
            atr_period: Period for ATR calculation (default 14)
        """
        self.ema_short_period = ema_short_period
        self.ema_long_period = ema_long_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.sl_atr_multiplier = float(sl_atr_multiplier)
        self.tp_atr_multiplier = float(tp_atr_multiplier)
        self.sl_tp_overrides_by_symbol = sl_tp_overrides_by_symbol or {}
        self.name = "Simple Trend Following Strategy"
    
    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """
        Calculate exponential moving average.
        
        Args:
            prices: Series of prices
            period: EMA period
            
        Returns:
            pd.Series: EMA values
        """
        return prices.ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        """
        Calculate Relative Strength Index.
        
        Args:
            prices: Series of prices
            period: RSI period
            
        Returns:
            pd.Series: RSI values
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        """
        Calculate Average True Range.
        
        Args:
            df: DataFrame with 'high', 'low', 'close' columns
            period: ATR period
            
        Returns:
            pd.Series: ATR values
        """
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.rolling(window=period).mean()
    
    def generate_signal(self, data: pd.DataFrame) -> SignalType:
        """
        Generate trading signal based on trend following rules.
        
        Args:
            data: DataFrame with OHLC data and sufficient history
            
        Returns:
            SignalType: BUY, SELL, or HOLD signal
        """
        if len(data) < max(self.ema_long_period, self.rsi_period):
            return SignalType.HOLD
        
        # Calculate indicators
        data['ema_short'] = self.calculate_ema(data['close'], self.ema_short_period)
        data['ema_long'] = self.calculate_ema(data['close'], self.ema_long_period)
        data['rsi'] = self.calculate_rsi(data['close'], self.rsi_period)
        
        # Get latest values
        current_price = data['close'].iloc[-1]
        ema_short = data['ema_short'].iloc[-1]
        ema_long = data['ema_long'].iloc[-1]
        rsi = data['rsi'].iloc[-1]
        
        # Check for NaN values
        if any(pd.isna([ema_short, ema_long, rsi])):
            return SignalType.HOLD
        
        # BUY signal conditions
        if (ema_short > ema_long and    # Uptrend
            rsi > 50 and               # Positive momentum
            current_price > ema_short): # Price confirmation
            return SignalType.BUY
        
        # SELL signal conditions
        elif (ema_short < ema_long and  # Downtrend
              rsi < 50 and             # Negative momentum
              current_price < ema_short): # Price confirmation
            return SignalType.SELL
        
        # Otherwise hold
        else:
            return SignalType.HOLD
    
    def get_name(self) -> str:
        """Get strategy name."""
        return self.name
    
    def get_parameters(self) -> dict:
        """Get strategy parameters."""
        return {
            'ema_short_period': self.ema_short_period,
            'ema_long_period': self.ema_long_period,
            'rsi_period': self.rsi_period,
            'atr_period': self.atr_period
        }
    
    def compute_sl_tp(self, df: pd.DataFrame, signal: str, symbol: str = None) -> Tuple[float, float]:
        """
        Compute stop loss and take profit levels.
        
        Args:
            df: DataFrame with market data
            signal: Trading signal ('BUY' or 'SELL')
            
        Returns:
            Tuple[float, float]: (stop_loss, take_profit) values
        """
        if df is None or df.empty:
            raise ValueError("DataFrame cannot be None or empty")
            
        if len(df) < 2:
            raise ValueError("DataFrame must have at least 2 rows")
        
        current_price = df['close'].iloc[-1]
        
        # Calculate ATR for dynamic stop loss
        atr_period = min(self.atr_period, len(df) - 1)
        atr_df = df.tail(atr_period + 10) if len(df) > atr_period + 10 else df
        atr = self.calculate_atr(atr_df, atr_period).iloc[-1]
        
        # Default risk parameters
        sl_multiplier = self.sl_atr_multiplier
        tp_multiplier = self.tp_atr_multiplier

        # Symbol-specific overrides (if configured)
        if symbol and isinstance(self.sl_tp_overrides_by_symbol, dict):
            override = self.sl_tp_overrides_by_symbol.get(symbol, {})
            if isinstance(override, dict):
                if override.get("sl_atr") is not None:
                    sl_multiplier = float(override.get("sl_atr"))
                if override.get("tp_atr") is not None:
                    tp_multiplier = float(override.get("tp_atr"))
        
        if signal.upper() == 'BUY':
            sl = current_price - (sl_multiplier * atr)
            tp = current_price + (tp_multiplier * atr)
        elif signal.upper() == 'SELL':
            sl = current_price + (sl_multiplier * atr)
            tp = current_price - (tp_multiplier * atr)
        else:
            raise ValueError(f"Invalid signal: {signal}. Expected 'BUY' or 'SELL'")
        
        return sl, tp
    
    def compute_volume(self, df: pd.DataFrame, signal: str, account_equity: float) -> float:
        """
        Compute position size/volume based on account equity and risk management.
        
        Args:
            df: DataFrame with market data
            signal: Trading signal ('BUY' or 'SELL')
            account_equity: Current account equity
            
        Returns:
            float: Position size/volume in lots
        """
        # Get the current symbol from the dataframe index (assuming the last row contains current data)
        # For MT5, we typically want conservative position sizing
        # Use a fixed small lot size as default, regardless of account equity to avoid retcode=10014
        
        # Conservative position sizing for live trading
        if self.name.lower().find('demo') != -1 or str(account_equity).find('demo') != -1 or self.name.find('Demo') != -1:
            # In demo environment, use very small volumes
            base_volume = 0.01
        else:
            # For live trading, determine a reasonable risk-based volume
            # Risk management: use conservative percentage of account equity per trade
            # For typical MT5 accounts, use 1-2% of equity but capped to reasonable lot sizes
            risk_percentage = 0.01  # 1% risk per trade (conservative)
            
            # Estimate risk amount based on 1:3 risk-reward ratio assumption
            # Using a conservative approach: 0.01-0.05 lots for most retail accounts
            if account_equity < 1000:
                base_volume = 0.01  # Very small for small accounts
            elif account_equity < 5000:
                base_volume = 0.02
            elif account_equity < 10000:
                base_volume = 0.03
            elif account_equity < 25000:
                base_volume = 0.05
            else:
                base_volume = min(0.10, account_equity * 0.001)  # Cap at 0.10 lots or 0.1% of equity

        # Calculate ATR for position sizing
        current_price = df['close'].iloc[-1]
        
        atr_period = min(self.atr_period, len(df) - 1)
        atr_df = df.tail(atr_period + 10) if len(df) > atr_period + 10 else df
        atr = self.calculate_atr(atr_df, atr_period).iloc[-1]
        
        # Calculate risk per unit (difference between entry and stop loss)
        sl, _ = self.compute_sl_tp(df, signal)
        risk_per_unit = abs(current_price - sl) if sl is not None else atr * 2.0
        
        # Avoid division by zero
        if risk_per_unit <= 0:
            risk_per_unit = atr * 2.0  # Default to 2x ATR if SL calculation fails
        
        # Calculate volume based on risk management
        risk_amount = account_equity * 0.01  # Risk 1% of equity
        calculated_volume = risk_amount / risk_per_unit
        
        # Use the calculated volume but cap it to reasonable limits
        volume = min(calculated_volume, base_volume)
        
        # Apply minimum and maximum volume constraints appropriate for MT5
        min_volume = 0.01  # Minimum lot size supported by most brokers
        max_volume = 100.0  # Maximum lot size (this is quite large, most brokers have lower limits)
        
        volume = max(min_volume, min(volume, max_volume))
        
        return volume

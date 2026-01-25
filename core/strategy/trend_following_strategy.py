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
                 atr_period: int = 14):
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
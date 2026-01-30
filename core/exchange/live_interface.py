"""
Live Exchange Interface for TradePy bot
Defines minimal interface required for live trading operations
"""
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd
from ..models import AccountSnapshot, OrderResult


class LiveExchangeInterface(ABC):
    """Interface for live exchange operations - minimal methods actually used by live runner"""

    @abstractmethod
    def connect(self) -> bool:
        """Connect to the exchange"""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown connection to the exchange"""
        pass

    @abstractmethod
    def account_info(self) -> AccountSnapshot:
        """Get account snapshot information"""
        pass

    @abstractmethod
    def get_rates(self, symbol: str, timeframe: int, count: int = 300) -> pd.DataFrame:
        """Get market rates/candles for a symbol"""
        pass

    @abstractmethod
    def positions(self, symbol: Optional[str] = None):
        """Get open positions, optionally filtered by symbol"""
        pass

    @abstractmethod
    def floating_pnl(self, symbol: Optional[str] = None) -> float:
        """Get floating PnL for a symbol or all positions"""
        pass

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, volume: float, sl: float, tp: float, 
                          comment: str = "TradePy Live") -> OrderResult:
        """Place a market order with mandatory stop loss and take profit"""
        pass


class BacktestDataInterface(ABC):
    """Interface for backtesting data operations - separate from live operations"""
    
    @abstractmethod
    def get_historical_data(self, symbol: str, timeframe: str, start_date: str, end_date: str):
        """Get historical market data for backtesting"""
        pass

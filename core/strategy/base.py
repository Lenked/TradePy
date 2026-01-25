"""
Base strategy class for TradePy bot
"""
from abc import ABC, abstractmethod
import pandas as pd
from .signal import SignalType


class Strategy(ABC):
    """Abstract base class for trading strategies"""
    
    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> SignalType:
        """Generate trading signal based on data"""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get strategy name"""
        pass
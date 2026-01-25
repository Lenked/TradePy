"""
Base indicator class for TradePy bot
"""
from abc import ABC, abstractmethod
import pandas as pd


class Indicator(ABC):
    """Abstract base class for technical indicators"""
    
    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate indicator values"""
        pass
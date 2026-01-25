"""
Indicator calculator for TradePy bot
"""
import pandas as pd
from .base import Indicator


class IndicatorCalculator:
    """Calculator for technical indicators"""
    
    def __init__(self):
        self.indicators = {}
        
    def register_indicator(self, name: str, indicator: Indicator):
        """Register an indicator"""
        self.indicators[name] = indicator
        
    def calculate_all(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate all registered indicators"""
        result = data.copy()
        for name, indicator in self.indicators.items():
            result = indicator.calculate(result)
        return result
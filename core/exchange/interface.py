"""
Exchange interface for TradePy bot
This is a combined interface that extends both live and backtest interfaces
"""
from abc import ABC
from .live_interface import LiveExchangeInterface, BacktestDataInterface


class ExchangeInterface(LiveExchangeInterface, BacktestDataInterface, ABC):
    """Combined interface for both live and backtesting operations"""
    pass
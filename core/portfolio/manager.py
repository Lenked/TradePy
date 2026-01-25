"""
Portfolio management for TradePy bot
"""
from typing import Dict, Optional
from .position import Position


class PortfolioManager:
    """Manage trading portfolio and positions"""
    
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.positions: Dict[str, Position] = {}
        
    def add_position(self, position: Position):
        """Add a position to portfolio"""
        self.positions[position.symbol] = position
        
    def close_position(self, symbol: str):
        """Close a position"""
        if symbol in self.positions:
            del self.positions[symbol]
            
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get a specific position"""
        return self.positions.get(symbol)
        
    def calculate_total_value(self) -> float:
        """Calculate total portfolio value"""
        value = self.current_capital
        for position in self.positions.values():
            value += position.unrealized_pnl
        return value
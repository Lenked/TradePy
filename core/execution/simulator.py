"""
Execution simulator for TradePy bot
"""
from .order import Order


class ExecutionSimulator:
    """Simulate order execution"""
    
    def __init__(self, fee_rate: float = 0.001):
        self.fee_rate = fee_rate
    
    def execute_order(self, order: Order, current_price: float):
        """Execute an order and return result"""
        # Simulated execution logic
        fee = order.quantity * current_price * self.fee_rate
        return {
            'success': True,
            'filled_quantity': order.quantity,
            'avg_fill_price': current_price,
            'fee': fee,
            'order': order
        }
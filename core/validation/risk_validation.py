"""
Risk validation module for TradePy bot
"""
from abc import ABC, abstractmethod


class RiskValidator(ABC):
    """
    Abstract base class for risk validation.
    All risk validators should inherit from this class.
    """
    
    @abstractmethod
    def validate(self, *args, **kwargs) -> bool:
        """
        Validate risk parameters.
        
        Args:
            *args: Variable length argument list
            **kwargs: Arbitrary keyword arguments
            
        Returns:
            bool: True if validation passes, False otherwise
        """
        pass


class MaxDrawdownValidator(RiskValidator):
    """
    Validates that the maximum drawdown threshold is not exceeded.
    """
    
    def __init__(self, max_drawdown_threshold: float = 0.15):
        """
        Initialize the validator.
        
        Args:
            max_drawdown_threshold: Maximum allowed drawdown as a percentage (e.g., 0.15 for 15%)
        """
        self.max_drawdown_threshold = max_drawdown_threshold
    
    def validate(self, current_drawdown: float) -> bool:
        """
        Validate that the current drawdown is below the threshold.
        
        Args:
            current_drawdown: Current drawdown as a percentage
            
        Returns:
            bool: True if validation passes, False otherwise
        """
        return current_drawdown <= self.max_drawdown_threshold


class RiskPerTradeValidator(RiskValidator):
    """
    Validates that the risk per trade is within acceptable limits.
    """
    
    def __init__(self, max_risk_per_trade: float = 0.01):
        """
        Initialize the validator.
        
        Args:
            max_risk_per_trade: Maximum allowed risk per trade as a percentage (e.g., 0.01 for 1%)
        """
        self.max_risk_per_trade = max_risk_per_trade
    
    def validate(self, risk_amount: float, account_balance: float) -> bool:
        """
        Validate that the risk amount is within acceptable limits.
        
        Args:
            risk_amount: Amount at risk for the trade
            account_balance: Current account balance
            
        Returns:
            bool: True if validation passes, False otherwise
        """
        if account_balance <= 0:
            return False
        
        risk_percentage = risk_amount / account_balance
        return risk_percentage <= self.max_risk_per_trade


class PositionSizeValidator(RiskValidator):
    """
    Validates that the position size is within acceptable limits.
    """
    
    def __init__(self, max_position_size_percentage: float = 0.10):
        """
        Initialize the validator.
        
        Args:
            max_position_size_percentage: Maximum allowed position size as a percentage of account (e.g., 0.10 for 10%)
        """
        self.max_position_size_percentage = max_position_size_percentage
    
    def validate(self, position_value: float, account_balance: float) -> bool:
        """
        Validate that the position size is within acceptable limits.
        
        Args:
            position_value: Value of the position
            account_balance: Current account balance
            
        Returns:
            bool: True if validation passes, False otherwise
        """
        if account_balance <= 0:
            return False
        
        position_percentage = position_value / account_balance
        return position_percentage <= self.max_position_size_percentage
"""
Risk management for TradePy bot
"""
from typing import List
from .rules import RiskRule


class RiskManager:
    """Manage trading risks and validations"""
    
    def __init__(self):
        self.rules: List[RiskRule] = []
        
    def add_rule(self, rule: RiskRule):
        """Add a risk rule"""
        self.rules.append(rule)
        
    def validate_trade(self, *args, **kwargs) -> bool:
        """Validate a trade against all rules"""
        for rule in self.rules:
            if rule.enabled and not rule.validate(*args, **kwargs):
                return False
        return True
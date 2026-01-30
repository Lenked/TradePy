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
    
    def allow_trade(self, signal, sl, tp, account_snapshot):
        """Check if a trade is allowed based on risk rules"""
        if not self.rules:
            return True, "No risk rules configured"
        
        # Validate against all configured rules
        for rule in self.rules:
            if rule.enabled and hasattr(rule, 'validate'):
                try:
                    # Call the rule's validate method with appropriate parameters
                    if not rule.validate(signal, sl, tp, account_snapshot):
                        return False, f"Rule '{rule.__class__.__name__}' blocked trade"
                except Exception as e:
                    return False, f"Rule '{rule.__class__.__name__}' validation error: {e}"
        
        return True, "Trade allowed by risk management"

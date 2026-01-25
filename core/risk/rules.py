"""
Risk rules for TradePy bot
"""


class RiskRule:
    """Base class for risk rules"""
    
    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled
    
    def validate(self, *args, **kwargs) -> bool:
        """Validate the rule"""
        raise NotImplementedError
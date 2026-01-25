"""
DEPRECATED: Compatibility module for trend following strategy
This module exists for backward compatibility only.
Use core.strategy.trend_following_strategy instead.
"""
import warnings
from .trend_following_strategy import TrendFollowingStrategy

warnings.warn(
    "core.strategy.trend_following is deprecated. "
    "Use core.strategy.trend_following_strategy instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export the class for backward compatibility
__all__ = ['TrendFollowingStrategy']
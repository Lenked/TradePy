"""
Helper utilities for TradePy bot
"""


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """Calculate percentage change between two values"""
    if old_value == 0:
        return 0
    return ((new_value - old_value) / old_value) * 100


def round_to_tick(value: float, tick_size: float) -> float:
    """Round value to nearest tick size"""
    return round(value / tick_size) * tick_size
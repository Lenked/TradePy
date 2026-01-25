"""
Symbol scheduling utilities for TradePy
Maps days of the week to specific trading symbols
"""
import os
from datetime import datetime
import yaml


def get_symbols_for_today(config_path: str = "config/settings.yaml") -> list:
    """
    Get the symbols to trade based on the current day of the week.

    Args:
        config_path: Path to config file with custom symbol mapping (optional)

    Returns:
        List of symbols to trade for the current day
    """
    # Day of week mapping (0=Monday, 6=Sunday)
    default_mapping = {
        0: ["BTCUSDm", "XAUUSDm", "EURUSDm", "USOILm", "NVDAm"],  # Monday
        1: ["BTCUSDm", "XAUUSDm", "EURUSDm", "USOILm", "NVDAm"],  # Tuesday
        2: ["BTCUSDm", "XAUUSDm", "EURUSDm", "USOILm", "NVDAm"],  # Wednesday
        3: ["BTCUSDm", "XAUUSDm", "EURUSDm", "USOILm", "NVDAm"],  # Thursday
        4: ["BTCUSDm", "XAUUSDm", "EURUSDm", "USOILm", "NVDAm"],  # Friday
        5: ["BTCUSDm"],  # Saturday
        6: ["BTCUSDm"]   # Sunday
    }

    # Try to load custom mapping from config if it exists
    custom_mapping = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                if config and 'symbol_schedule' in config:
                    custom_mapping = config['symbol_schedule']
        except Exception:
            # If config loading fails, continue with default mapping
            pass

    # Use custom mapping if provided, otherwise default
    mapping = {**default_mapping, **custom_mapping}

    # Get current day of week (0=Monday, 6=Sunday)
    current_day = datetime.now().weekday()

    # Return symbols for current day
    return mapping.get(current_day, ["BTCUSDm"])  # Default to BTCUSDm if not found
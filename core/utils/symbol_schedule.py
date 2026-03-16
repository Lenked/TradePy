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

    # Try to load custom mapping and symbols_disabled from config
    custom_mapping = {}
    symbols_disabled = []
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                if config:
                    if 'symbol_schedule' in config:
                        custom_mapping = config['symbol_schedule']
                    if config.get('symbols_disabled'):
                        symbols_disabled = list(config['symbols_disabled']) if isinstance(config['symbols_disabled'], (list, tuple)) else []
        except Exception:
            pass

    # Use custom mapping if provided, otherwise default
    mapping = {**default_mapping, **custom_mapping}

    # Get current day of week (0=Monday, 6=Sunday)
    current_day = datetime.now().weekday()
    symbols = mapping.get(current_day, ["BTCUSDm"])

    # Exclude disabled symbols
    if symbols_disabled:
        symbols = [s for s in symbols if s not in symbols_disabled]

    return symbols if symbols else ["BTCUSDm"]
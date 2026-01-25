"""
Time utilities for TradePy bot
"""
from datetime import datetime


def get_current_time():
    """Get current timestamp"""
    return datetime.now()


def parse_time(time_str: str):
    """Parse time string to datetime object"""
    return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
"""
Centralized logging utility for TradePy bot
"""
import logging
import sys
import os
from datetime import datetime
from typing import Optional


class Logger:
    """Centralized logging utility class using Python's logging module"""

    def __init__(self, name: str, level: int = None):
        self.name = name
        
        # Default to INFO level if not specified, but allow override from environment
        if level is None:
            level = self._get_log_level_from_env()

        # Create logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # Avoid adding handlers multiple times
        if not self.logger.handlers:
            # Create console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)

            # Create file handler
            file_handler = logging.FileHandler(f'{name.replace(".", "_")}.log')
            file_handler.setLevel(level)

            # Create formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

            console_handler.setFormatter(formatter)
            file_handler.setFormatter(formatter)

            # Add handlers to logger
            self.logger.addHandler(console_handler)
            self.logger.addHandler(file_handler)
    
    def _get_log_level_from_env(self):
        """Get log level from environment variable or default to INFO"""
        log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
        
        log_levels = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        
        return log_levels.get(log_level_str, logging.INFO)

    def info(self, message: str):
        """Log info message"""
        self.logger.info(message)

    def error(self, message: str):
        """Log error message"""
        self.logger.error(message)

    def warning(self, message: str):
        """Log warning message"""
        self.logger.warning(message)

    def debug(self, message: str):
        """Log debug message"""
        self.logger.debug(message)

    def set_level(self, level: int):
        """Set logging level"""
        self.logger.setLevel(level)
        for handler in self.logger.handlers:
            handler.setLevel(level)


# Global logger instance for the application
def get_logger(name: str, level: int = logging.INFO) -> Logger:
    """
    Get a logger instance with the specified name

    Args:
        name: Name of the logger
        level: Logging level (default: INFO)

    Returns:
        Logger instance
    """
    return Logger(name, level)


# Rate-limited logger to reduce noise
class RateLimitedLogger:
    """Logger that limits messages to reduce noise"""

    def __init__(self, name: str, min_interval: int = 60):
        """
        Initialize rate-limited logger

        Args:
            name: Name of the logger
            min_interval: Minimum interval between messages in seconds (default: 60)
        """
        self.logger = get_logger(name)
        self.min_interval = min_interval
        self.last_log_time = {}

    def info(self, message: str, key: Optional[str] = None):
        """
        Log info message with rate limiting

        Args:
            message: Message to log
            key: Key to identify the specific message type for rate limiting
        """
        key = key or message
        current_time = datetime.now().timestamp()

        if key not in self.last_log_time or \
           current_time - self.last_log_time[key] >= self.min_interval:
            self.logger.info(message)
            self.last_log_time[key] = current_time

    def error(self, message: str):
        """Always log error messages"""
        self.logger.error(message)

    def warning(self, message: str):
        """Always log warning messages"""
        self.logger.warning(message)

    def debug(self, message: str, key: Optional[str] = None):
        """
        Log debug message with rate limiting
        """
        key = key or message
        current_time = datetime.now().timestamp()

        if key not in self.last_log_time or \
           current_time - self.last_log_time[key] >= self.min_interval:
            self.logger.debug(message)
            self.last_log_time[key] = current_time
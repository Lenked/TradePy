"""
Models and data types for TradePy
Contains dataclasses and type definitions used across the system
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any
import pandas as pd


@dataclass
class AccountSnapshot:
    """Snapshot of account information"""
    balance: float
    equity: float
    margin: float
    free_margin: float


@dataclass
class OrderRequest:
    """Request to place an order"""
    symbol: str
    side: str  # 'BUY' or 'SELL'
    volume: float
    sl: float  # Stop Loss
    tp: float  # Take Profit
    comment: str = "TradePy Order"


@dataclass 
class OrderResult:
    """Result of an order placement"""
    success: bool
    order_id: Optional[str] = None
    retcode: Optional[int] = None
    comment: str = ""
    request: Optional[Dict[str, Any]] = None
    message: str = ""
    details: Optional[Dict[str, Any]] = None

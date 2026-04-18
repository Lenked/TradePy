"""
Models and data types for TradePy
Contains dataclasses and type definitions used across the system
"""
from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class SymbolTradeConstraints:
    """Broker constraints and tick metadata used for sizing."""
    symbol: str
    min_lot: float
    max_lot: float
    lot_step: float
    point: Optional[float] = None
    tick_size: Optional[float] = None
    tick_value: Optional[float] = None
    contract_size: Optional[float] = None


@dataclass
class TradeState:
    """Runtime state tracked for an active trade."""
    trade_id: str
    symbol: str
    side: str
    volume: float
    open_time: Optional[datetime]
    snapshot_id: Optional[str] = None
    position_ticket: Optional[str] = None
    requested_trade_id: Optional[str] = None
    timeframe_key: str = "default"
    entry_bar_time: Optional[datetime] = None
    entry_price: float = 0.0
    initial_sl: float = 0.0
    initial_tp: float = 0.0
    current_sl: float = 0.0
    current_tp: float = 0.0
    initial_risk_distance: float = 0.0
    initial_tp_distance: float = 0.0
    atr_at_entry: float = 0.0
    rsi_at_entry: float = 0.0
    volume_ratio_at_entry: float = 0.0
    spread_at_entry: float = 0.0
    signal_confidence: float = 0.0
    signal_force: float = 0.0
    trend_alignment_score: float = 0.0
    sl_tp_quality_score: float = 0.0
    touched_break_even: bool = False
    profit_locked: bool = False
    used_trailing: bool = False
    momentum_reversal: bool = False
    max_drawdown: float = 0.0
    max_profit_reached: float = 0.0
    bars_held: int = 0
    reentry_count_same_bar: int = 0
    last_protection_update: Optional[datetime] = None
    pending_exit_reason: str = ""
    last_exit_price: float = 0.0

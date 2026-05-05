"""
Auto-close scheduler for TradePy bot
Automatically closes trades after 90 minutes to prevent long sessions
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from core.exchange.live_interface import LiveExchangeInterface
from core.models import OrderResult


class AutoCloseScheduler:
    """
    Scheduler that automatically closes trades after 90 minutes to prevent long sessions
    """
    
    def __init__(self, exchange: LiveExchangeInterface, timeout_minutes: int = 90):
        """
        Initialize the auto-close scheduler
        
        Args:
            exchange: The exchange interface to use for closing positions
            timeout_minutes: Number of minutes after which to auto-close trades (default 90)
        """
        self.exchange = exchange
        self.timeout_minutes = timeout_minutes
        self.open_trades: Dict[str, datetime] = {}  # ticket -> open_time
        self.logger = logging.getLogger(__name__)
        
    def register_trade(self, ticket: str, open_time: Optional[datetime] = None) -> None:
        """
        Register a new trade that should be monitored for auto-closing
        
        Args:
            ticket: The trade ticket/ID
            open_time: The time the trade was opened (defaults to now)
        """
        if open_time is None:
            open_time = datetime.now()
        self.open_trades[ticket] = open_time
        self.logger.info(f"AUTO_CLOSE_REGISTERED - Ticket: {ticket} | Timeout: {self.timeout_minutes}min | OpenTime: {open_time}")
    
    def unregister_trade(self, ticket: str) -> None:
        """
        Unregister a trade (when it's closed manually or reaches target/stop)
        
        Args:
            ticket: The trade ticket/ID to remove from monitoring
        """
        if ticket in self.open_trades:
            del self.open_trades[ticket]
            self.logger.info(f"AUTO_CLOSE_UNREGISTERED - Ticket: {ticket}")

    def transfer_ticket(self, old_ticket: str, new_ticket: str) -> None:
        """Move monitoring from a provisional id (e.g. pre-sync) to the exchange ticket."""
        old = str(old_ticket)
        new = str(new_ticket)
        if old in self.open_trades and old != new:
            self.open_trades[new] = self.open_trades.pop(old)
            self.logger.info(f"AUTO_CLOSE_TRANSFER - From: {old} | To: {new}")
    
    def check_and_close_expired_trades(self) -> List[OrderResult]:
        """
        Check for expired trades and close them automatically
        
        Returns:
            List of OrderResult objects for each closure attempt
        """
        results = []
        now = datetime.now()
        expired_tickets = []
        
        # Find expired trades
        for ticket, open_time in self.open_trades.items():
            elapsed = now - open_time
            if elapsed.total_seconds() >= (self.timeout_minutes * 60):
                expired_tickets.append((ticket, open_time))
        
        # Close expired trades
        for ticket, open_time in expired_tickets:
            result = self._close_trade(ticket)
            results.append(result)
            
            # Unregister the trade regardless of success/failure
            self.unregister_trade(ticket)
            
            # Log the action
            duration = now - open_time
            if result.success:
                self.logger.info(
                    f"AUTO_CLOSE_SUCCESS - Ticket: {ticket} | Duration: {duration} | "
                    f"Comment: Auto-closed after {self.timeout_minutes} minutes"
                )
            else:
                self.logger.error(
                    f"AUTO_CLOSE_FAILED - Ticket: {ticket} | Duration: {duration} | "
                    f"Error: {result.message}"
                )
        
        return results
    
    def _close_trade(self, ticket: str) -> OrderResult:
        """
        Attempt to close a specific trade
        
        Args:
            ticket: The trade ticket/ID to close
            
        Returns:
            OrderResult indicating success or failure
        """
        # Get position details to determine side and volume
        positions = self.exchange.positions()
        position_to_close = None
        
        for pos in positions:
            pos_ticket = str(getattr(pos, "ticket", None) or getattr(pos, "id", None) or "")
            if pos_ticket == ticket:
                position_to_close = pos
                break
        
        if not position_to_close:
            # Position no longer exists, might have been closed elsewhere
            return OrderResult(
                success=True,
                order_id=ticket,
                message="position_already_closed",
                comment="Position not found, likely already closed"
            )
        
        # Extract position details (MT5 TradePosition uses attributes, not dict)
        symbol = getattr(position_to_close, "symbol", None)
        raw_type = getattr(position_to_close, "type", None)
        side = "BUY" if raw_type == 0 else "SELL" if raw_type == 1 else None
        volume = float(getattr(position_to_close, "volume", 0.0))
        
        if not all([symbol, side, volume]):
            return OrderResult(
                success=False,
                order_id=ticket,
                message="missing_position_details",
                comment="Could not determine position details"
            )
        
        # Close the position using the exchange's close_position method
        try:
            result = self.exchange.close_position(
                ticket=ticket,
                symbol=symbol,
                volume=volume,
                side=side,
                comment=f"TradePy Auto-Close: {self.timeout_minutes}min timeout"
            )
            return result
        except Exception as e:
            self.logger.error(f"AUTO_CLOSE_EXCEPTION - Ticket: {ticket} | Error: {str(e)}")
            return OrderResult(
                success=False,
                order_id=ticket,
                message=f"exception: {str(e)}",
                comment="Exception during auto-close attempt"
            )
    
    def get_active_trades(self) -> Dict[str, Dict[str, any]]:
        """
        Get information about all actively monitored trades
        
        Returns:
            Dictionary mapping ticket to trade info (open_time, remaining_time)
        """
        now = datetime.now()
        active_info = {}
        
        for ticket, open_time in self.open_trades.items():
            elapsed = now - open_time
            remaining = timedelta(minutes=self.timeout_minutes) - elapsed
            active_info[ticket] = {
                "open_time": open_time,
                "elapsed": elapsed,
                "remaining": remaining if remaining.total_seconds() > 0 else timedelta(0),
                "expired": remaining.total_seconds() <= 0
            }
        
        return active_info
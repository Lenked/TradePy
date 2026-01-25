"""
Kill switch module for TradePy bot
This provides emergency shutdown capabilities based on critical thresholds
"""


class KillSwitch:
    """
    Emergency shutdown system for the trading bot.
    Monitors critical thresholds and stops the system when exceeded.
    
    Responsibilities:
    - Monitor drawdown levels
    - Track daily losses
    - Handle abnormal behavior detection
    - Execute emergency shutdown when thresholds are breached
    """
    
    def __init__(self):
        self.active = True
        self.max_drawdown_threshold = 0.15  # 15%
        self.max_daily_loss_threshold = 0.05  # 5%
        self.max_loss_streak_threshold = 5  # 5 consecutive losses
        self.manual_override = False
        
        # Track metrics
        self.current_drawdown = 0.0
        self.daily_losses = 0.0
        self.loss_streak = 0
        self.stopped_by = None
        self.stop_reason = ""
    
    def activate_manual_stop(self, reason: str = "Manual override"):
        """
        Manually activate the kill switch.
        
        Args:
            reason: Reason for manual activation
        """
        self.active = False
        self.manual_override = True
        self.stopped_by = "MANUAL"
        self.stop_reason = reason
        print(f"Kill switch activated manually: {reason}")
    
    def deactivate_manual_stop(self):
        """
        Deactivate the manual kill switch to resume operations.
        """
        self.active = True
        self.manual_override = False
        self.stopped_by = None
        self.stop_reason = ""
        print("Kill switch deactivated manually. Operations resumed.")
    
    def update_metrics(self, current_drawdown: float, daily_loss: float, 
                      lost_trade: bool = False):
        """
        Update monitored metrics for kill switch evaluation.
        
        Args:
            current_drawdown: Current system drawdown
            daily_loss: Loss for the current day
            lost_trade: Whether the last trade was a loss
        """
        self.current_drawdown = current_drawdown
        self.daily_losses = daily_loss
        
        if lost_trade:
            self.loss_streak += 1
        else:
            self.loss_streak = 0
    
    def evaluate_kill_condition(self):
        """
        Evaluate if any kill conditions are met and activate kill switch if needed.
        
        Returns:
            tuple: (should_stop: bool, reason: str)
        """
        if not self.active or self.manual_override:
            return False, "Kill switch inactive or manually overridden"
        
        # Check drawdown threshold
        if self.current_drawdown >= self.max_drawdown_threshold:
            reason = f"Maximum drawdown threshold exceeded: {self.current_drawdown:.2%} >= {self.max_drawdown_threshold:.2%}"
            self._trigger_kill(reason, "DRAWDOWN")
            return True, reason
        
        # Check daily loss threshold
        if self.daily_losses >= self.max_daily_loss_threshold:
            reason = f"Maximum daily loss threshold exceeded: {self.daily_losses:.2%} >= {self.max_daily_loss_threshold:.2%}"
            self._trigger_kill(reason, "DAILY_LOSS")
            return True, reason
        
        # Check loss streak
        if self.loss_streak >= self.max_loss_streak_threshold:
            reason = f"Maximum consecutive loss streak exceeded: {self.loss_streak} >= {self.max_loss_streak_threshold}"
            self._trigger_kill(reason, "LOSS_STREAK")
            return True, reason
        
        return False, "No kill conditions met"
    
    def _trigger_kill(self, reason: str, trigger_type: str):
        """
        Internal method to trigger the kill switch.
        
        Args:
            reason: Reason for triggering kill switch
            trigger_type: Type of trigger that caused the shutdown
        """
        self.active = False
        self.stopped_by = trigger_type
        self.stop_reason = reason
        print(f"KILL SWITCH TRIGGERED: {reason}")
        print(f"System stopped by: {trigger_type}")
        
        # Log the event with more details
        self._log_shutdown_event()
    
    def _log_shutdown_event(self):
        """
        Log detailed information about the shutdown event.
        This could be extended to write to a file or database.
        """
        print("--- SHUTDOWN EVENT LOG ---")
        print(f"Active: {self.active}")
        print(f"Stopped by: {self.stopped_by}")
        print(f"Reason: {self.stop_reason}")
        print(f"Current drawdown: {self.current_drawdown:.2%}")
        print(f"Daily losses: {self.daily_losses:.2%}")
        print(f"Loss streak: {self.loss_streak}")
        print("--- END LOG ---")
    
    def get_status(self):
        """
        Get current status of the kill switch.
        
        Returns:
            dict: Status information
        """
        return {
            'active': self.active,
            'manual_override': self.manual_override,
            'current_drawdown': self.current_drawdown,
            'daily_losses': self.daily_losses,
            'loss_streak': self.loss_streak,
            'stopped_by': self.stopped_by,
            'stop_reason': self.stop_reason,
            'max_drawdown_threshold': self.max_drawdown_threshold,
            'max_daily_loss_threshold': self.max_daily_loss_threshold,
            'max_loss_streak_threshold': self.max_loss_streak_threshold
        }


class GlobalKillSwitch:
    """
    Global singleton kill switch that can be accessed from anywhere in the system.
    This ensures consistent kill switch behavior across all components.
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GlobalKillSwitch, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Initialize only once
        if not GlobalKillSwitch._initialized:
            self.kill_switch = KillSwitch()
            GlobalKillSwitch._initialized = True
    
    def activate_manual_stop(self, reason: str = "Manual override"):
        """Activate the global kill switch manually."""
        return self.kill_switch.activate_manual_stop(reason)
    
    def deactivate_manual_stop(self):
        """Deactivate the global kill switch."""
        return self.kill_switch.deactivate_manual_stop()
    
    def update_metrics(self, current_drawdown: float, daily_loss: float, 
                      lost_trade: bool = False):
        """Update metrics for the global kill switch."""
        return self.kill_switch.update_metrics(current_drawdown, daily_loss, lost_trade)
    
    def evaluate_kill_condition(self):
        """Evaluate kill conditions on the global kill switch."""
        return self.kill_switch.evaluate_kill_condition()
    
    def get_status(self):
        """Get status of the global kill switch."""
        return self.kill_switch.get_status()


def get_global_kill_switch():
    """
    Convenience function to get the global kill switch instance.
    
    Returns:
        GlobalKillSwitch: Singleton instance of the global kill switch
    """
    return GlobalKillSwitch()
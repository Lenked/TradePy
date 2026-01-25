"""
Watcher for live trading
Monitors positions, risk, and account conditions
"""
import time
from datetime import datetime
from typing import Dict, List, Optional
from utils.logger import get_logger


class Watcher:
    """
    Live Trading Watcher
    Monitors positions, risk conditions, and account health
    """

    def __init__(self, executor, risk_manager, kill_switch):
        self.executor = executor
        self.risk_manager = risk_manager
        self.kill_switch = kill_switch

        # Use centralized logger
        self.logger = get_logger(__name__)

        self.running = False
        self.last_check_time = None

    def monitor_account_health(self) -> Dict[str, any]:
        """Monitor account health and return key metrics"""
        try:
            account_info = self.executor.get_account_info()

            # Calculate derived metrics
            margin_level = (account_info['equity'] / account_info['margin'] * 100) if account_info['margin'] > 0 else float('inf')

            health_metrics = {
                'balance': account_info['balance'],
                'equity': account_info['equity'],
                'margin': account_info['margin'],
                'free_margin': account_info['free_margin'],
                'margin_level': margin_level,
                'profit': account_info['profit'],
                'timestamp': datetime.now()
            }

            return health_metrics
        except Exception as e:
            self.logger.error(f"Error getting account info: {str(e)}")
            return {}

    def monitor_positions(self, symbol: str = None) -> Dict[str, any]:
        """Monitor open positions"""
        try:
            positions = self.executor.get_open_positions(symbol)

            if not positions:
                return {
                    'count': 0,
                    'total_profit': 0.0,
                    'positions': []
                }

            total_profit = sum(pos.profit for pos in positions)
            position_details = []

            for pos in positions:
                position_info = {
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'volume': pos.volume,
                    'type': 'BUY' if pos.type == 0 else 'SELL',  # 0 is buy, 1 is sell
                    'price_open': pos.price_open,
                    'price_current': pos.price_current,
                    'sl': pos.sl,
                    'tp': pos.tp,
                    'profit': pos.profit,
                    'swap': pos.swap,
                    'commission': pos.commission
                }
                position_details.append(position_info)

            return {
                'count': len(positions),
                'total_profit': total_profit,
                'positions': position_details
            }
        except Exception as e:
            self.logger.error(f"Error getting positions: {str(e)}")
            return {'count': 0, 'total_profit': 0.0, 'positions': []}

    def check_risk_conditions(self, account_info: Dict) -> bool:
        """Check overall risk conditions"""
        try:
            # Let the risk manager check conditions
            # This is a simplified check - in practice, this would be more comprehensive
            return not self.kill_switch.should_stop()
        except Exception as e:
            self.logger.error(f"Error checking risk conditions: {str(e)}")
            return False

    def run_monitoring(self, symbol: str = "EURUSDm", check_interval: int = 10):
        """Run continuous monitoring"""
        self.logger.info("Starting live monitoring...")
        self.running = True

        try:
            while self.running:
                # Monitor account health
                account_health = self.monitor_account_health()

                # Monitor positions
                position_info = self.monitor_positions(symbol)

                # Check risk conditions
                risk_ok = self.check_risk_conditions(account_health)

                # Log status
                if account_health:
                    self.logger.info(
                        f"Account: Balance=${account_health.get('balance', 0):.2f}, "
                        f"Equity=${account_health.get('equity', 0):.2f}, "
                        f"MarginLevel={account_health.get('margin_level', 0):.2f}%, "
                        f"Positions={position_info['count']}, "
                        f"TotalPnL=${position_info['total_profit']:.2f}"
                    )

                # Check if kill switch is triggered
                if self.kill_switch.should_stop():
                    self.logger.warning("Kill switch activated - stopping monitoring")
                    break

                # Sleep before next check
                time.sleep(check_interval)

        except KeyboardInterrupt:
            self.logger.info("Monitoring interrupted by user")
        except Exception as e:
            self.logger.error(f"Error in monitoring: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.stop()

    def stop(self):
        """Stop the monitoring"""
        self.running = False
        self.logger.info("Live monitoring stopped")

    def get_status(self) -> Dict[str, any]:
        """Get current status of the watcher"""
        if not self.running:
            return {"status": "stopped"}

        account_health = self.monitor_account_health()
        position_info = self.monitor_positions()

        return {
            "status": "running",
            "account_health": account_health,
            "position_info": position_info,
            "risk_ok": self.check_risk_conditions(account_health),
            "last_check_time": self.last_check_time
        }


# Compatibility alias for backward compatibility
LiveWatcher = Watcher
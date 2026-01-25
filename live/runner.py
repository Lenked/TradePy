"""
Live runner for TradePy bot
"""

import time
from datetime import datetime
import pandas as pd
from core.utils.symbol_schedule import get_symbols_for_today
from utils.logger import RateLimitedLogger
from core.exchange.live_interface import LiveExchangeInterface


class LiveRunner:
    """Main runner for live trading"""

    def __init__(self, strategy, exchange: LiveExchangeInterface, risk_manager=None, kill_switch=None,
                 symbol: str = "AUTO", timeframe=None, poll_seconds: int = 5):
        self.strategy = strategy
        self.exchange = exchange
        self.risk_manager = risk_manager
        self.kill_switch = kill_switch

        self.symbol = symbol  # "AUTO" or specific symbol
        self.timeframe = timeframe
        self.poll_seconds = poll_seconds

        self._available_symbols = []
        self._current_symbol = None
        self._last_closed_bar_time = None
        self._startup_grace_period_active = True
        self._daily_start_equity = None
        self._daily_date = None

        # Initialize rate-limited logger to reduce "waiting for new bar" noise
        self.logger = RateLimitedLogger("LiveRunner", min_interval=60)  # Log every 60 seconds

    def _is_new_closed_bar(self, df: pd.DataFrame) -> bool:
        if df is None or df.empty or len(df) < 3:
            return False
        closed_time = df.index[-2]  # last CLOSED candle
        if self._last_closed_bar_time is None or closed_time > self._last_closed_bar_time:
            self._last_closed_bar_time = closed_time
            return True
        return False

    def _reset_daily_if_needed(self, equity: float):
        today = datetime.now().date()
        if self._daily_date != today:
            self._daily_date = today
            self._daily_start_equity = equity

    def _get_available_symbols(self) -> list:
        """Get the list of available symbols based on auto mode or fixed symbol"""
        if self.symbol == "AUTO":
            return get_symbols_for_today()
        return [self.symbol] if self.symbol else []

    def run(self):
        """Run the live trading loop"""
        self.exchange.connect()
        try:
            # Initial sync
            snap = self.exchange.account_info()
            self._reset_daily_if_needed(snap.equity)

            # Get initial symbols
            self._available_symbols = self._get_available_symbols()
            if self._available_symbols:
                self._current_symbol = self._available_symbols[0]

            # Get initial market data to set up startup grace period
            if self._current_symbol:
                df = self.exchange.get_rates(self._current_symbol, self.timeframe, count=300)
                if df is not None and not df.empty and len(df) >= 3:
                    # Store the last closed bar time for startup grace period
                    self._last_closed_bar_time = df.index[-2]

            while True:
                # Get current symbols (may change based on day)
                new_available_symbols = self._get_available_symbols()
                current_day = datetime.now().strftime("%A")

                # Log current day and active symbols for visibility (every loop)
                self.logger.logger.info(f"[LiveRunner] Today={current_day} | Active Symbols={new_available_symbols}")

                if self._available_symbols != new_available_symbols:
                    self.logger.info(f"DAY CHANGED: Switching symbol universe to: {new_available_symbols}")
                    self._available_symbols = new_available_symbols
                    if self._available_symbols:
                        self._current_symbol = self._available_symbols[0]  # Use first available symbol

                # Sync account info
                snap = self.exchange.account_info()
                self._reset_daily_if_needed(snap.equity)

                # Check if there are any open positions globally (max 1 trade constraint)
                all_positions = self.exchange.positions()
                has_open_positions_globally = all_positions is not None and len(all_positions) >= 1

                # Get floating PnL for current symbol
                floating = self.exchange.floating_pnl(symbol=self._current_symbol) if self._current_symbol else 0.0
                daily_pnl = (snap.equity - self._daily_start_equity) if self._daily_start_equity is not None else 0.0

                # Kill switch check (if provided)
                if self.kill_switch is not None:
                    # You can feed it with your own metrics; minimal example:
                    metrics = {
                        "equity": snap.equity,
                        "balance": snap.balance,
                        "daily_pnl": daily_pnl,
                        "floating_pnl": floating,
                        "symbols_scanned": self._available_symbols,
                        "chosen_symbol": self._current_symbol,
                        "day": datetime.now().strftime("%A"),
                    }
                    decision = self.kill_switch.evaluate(metrics)  # depending on your signature
                    if decision.get("triggered"):
                        self.logger.error(f"KILL SWITCH TRIGGERED: {decision}")
                        time.sleep(self.poll_seconds)
                        continue

                # Global position check: if any positions exist, don't enter new trades
                if has_open_positions_globally:
                    self.logger.info(f"[{datetime.now().strftime('%A')}] {', '.join(self._available_symbols) if self._available_symbols else 'None'} | "
                          f"Chosen: {self._current_symbol} | "
                          f"HOLD (Global positions exist: {len(all_positions)}) | Bal={snap.balance:.2f} Eq={snap.equity:.2f} "
                          f"Float={floating:.2f} DailyPnL={daily_pnl:.2f}")
                    time.sleep(self.poll_seconds)
                    continue

                # Iterate through available symbols to find trading opportunity
                signal_found = False
                for symbol in self._available_symbols:
                    if signal_found:
                        break  # Only process one signal per cycle

                    # Get market data for current symbol
                    df = self.exchange.get_rates(symbol, self.timeframe, count=300)
                    if df.empty:
                        continue

                    # Check for new closed bar
                    is_new_closed_bar = self._is_new_closed_bar(df)

                    # Only act on new closed bar and after startup grace period
                    if is_new_closed_bar:
                        # Disable startup grace period after first closed bar seen
                        if self._startup_grace_period_active:
                            self._startup_grace_period_active = False
                            self.logger.info("Startup grace period ended. Ready to trade.")

                        # Generate signal only after startup grace period
                        if not self._startup_grace_period_active:
                            self._current_symbol = symbol
                            signal = self.strategy.generate_signal(df)  # expects BUY/SELL/HOLD

                            self.logger.info(f"[{datetime.now().strftime('%A')}] {', '.join(self._available_symbols)} | "
                                  f"Chosen: {symbol} | Signal={signal} | Bal={snap.balance:.2f} Eq={snap.equity:.2f} "
                                  f"Float={floating:.2f} DailyPnL={daily_pnl:.2f}")

                            if signal in ("BUY", "SELL"):
                                # Strategy should provide SL/TP or risk_manager should compute it.
                                # For now, assume strategy exposes compute_sl_tp(df, signal)
                                sl, tp = self.strategy.compute_sl_tp(df, signal)

                                # risk manager optional
                                if self.risk_manager is not None and not self.risk_manager.allow_trade(signal, sl, tp, snap):
                                    continue

                                volume = self.strategy.compute_volume(df, signal, snap.equity)
                                ok = self.exchange.place_market_order(
                                    symbol=symbol,
                                    side=signal,
                                    volume=volume,
                                    sl=sl,
                                    tp=tp,
                                    comment="TradePy Live"
                                )
                                self.logger.info(f"ORDER {'OK' if ok else 'FAILED'} for {symbol}")
                                signal_found = True  # Only process one signal per cycle
                                break
                    else:
                        # Log status even when not trading (using rate-limited logger to reduce noise)
                        if symbol == self._available_symbols[0]:  # Only log once per cycle
                            # Use rate-limited logging for "waiting" messages to reduce noise
                            self.logger.info(f"[{datetime.now().strftime('%A')}] {', '.join(self._available_symbols)} | "
                                  f"Chosen: {self._current_symbol} | Waiting for new bar | Bal={snap.balance:.2f} Eq={snap.equity:.2f} "
                                  f"Float={floating:.2f} DailyPnL={daily_pnl:.2f}", key="waiting_for_bar")

                time.sleep(self.poll_seconds)

        finally:
            self.exchange.shutdown()
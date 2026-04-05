"""
Live runner for TradePy bot
"""

import time
import logging
import os
from datetime import datetime
import pandas as pd
from core.utils.symbol_schedule import get_symbols_for_today
from utils.logger import RateLimitedLogger
from core.exchange.live_interface import LiveExchangeInterface
from core.reporting.trade_reporter import TradeReporter


class LiveRunner:
    """Main runner for live trading"""

    def __init__(self, strategy, exchange: LiveExchangeInterface, risk_manager=None, kill_switch=None,
                 decision_guard=None, snapshot_store=None,
                 symbol: str = "AUTO", timeframe=None, timeframes=None, preferred_timeframe=None,
                 poll_seconds: int = 5):
        self.strategy = strategy
        self.exchange = exchange
        self.risk_manager = risk_manager
        self.kill_switch = kill_switch
        self.decision_guard = decision_guard
        self.snapshot_store = snapshot_store

        self.symbol = symbol  # "AUTO" or specific symbol
        self.timeframe = timeframe
        self.timeframes = self._normalize_timeframes(timeframes, timeframe)
        self.preferred_timeframe_key = preferred_timeframe
        self.poll_seconds = poll_seconds

        self._available_symbols = []
        self._current_symbol = None
        self._last_closed_bar_times = {}  # Track last processed bar time per symbol/timeframe
        self._last_trade_bar_time = {}  # Track last bar where a trade was attempted per symbol
        self._startup_grace_period_active = True
        self._daily_start_equity = None
        self._daily_date = None
        self._last_decision_trace_time = {}  # Track when decision trace was last logged per symbol/timeframe
        self._last_guard_status = {}
        self._open_positions_snapshot = {}
        self._open_trades = {}
        self._reporter = TradeReporter()

        # Initialize rate-limited logger to reduce "waiting for new bar" noise
        self.logger = RateLimitedLogger("LiveRunner", min_interval=60)  # Log every 60 seconds
        
        # Set logger level based on environment variable
        import logging
        log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
        log_levels = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        log_level = log_levels.get(log_level_str, logging.INFO)
        self.logger.logger.set_level(log_level)

        if self.decision_guard is not None and getattr(self.decision_guard, "enabled", False):
            status = "ready" if getattr(self.decision_guard, "active", False) else "not_ready"
            reason = getattr(self.decision_guard, "load_error", None) or getattr(self.decision_guard, "mode", "shadow")
            self.logger.logger.info(
                f"MODEL_GUARD_INIT - status={status} | target={getattr(self.decision_guard, 'target', 'unknown')} | "
                f"mode={getattr(self.decision_guard, 'mode', 'shadow')} | reason={reason}"
            )

    def _normalize_timeframes(self, timeframes, fallback_timeframe):
        if timeframes:
            normalized = []
            for item in timeframes:
                if isinstance(item, dict):
                    key = item.get("key") or item.get("label") or str(item.get("value"))
                    value = item.get("value")
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    key, value = item[0], item[1]
                else:
                    key, value = None, item
                if value is None:
                    continue
                normalized.append({"key": key, "value": value})
            if normalized:
                return normalized
        if fallback_timeframe is None:
            return []
        return [{"key": None, "value": fallback_timeframe}]

    def _is_new_closed_bar(self, df: pd.DataFrame, symbol: str, timeframe_key: str = None) -> bool:
        """Check if there's a new closed bar for the specific symbol/timeframe"""
        if df is None or df.empty or len(df) < 3:
            return False
        
        closed_time = df.index[-2]  # last CLOSED candle
        bar_key = (symbol, timeframe_key or "default")
        last_processed_time = self._last_closed_bar_times.get(bar_key)

        # First sight of a symbol/timeframe should establish a baseline, not trigger a trade
        if last_processed_time is None:
            self._last_closed_bar_times[bar_key] = closed_time
            return False
        
        if closed_time > last_processed_time:
            self._last_closed_bar_times[bar_key] = closed_time
            return True
        return False

    @staticmethod
    def _analysis_view(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        if len(df) >= 2:
            closed_df = df.iloc[:-1].copy()
            if not closed_df.empty:
                return closed_df
        return df.copy()

    def _log_model_guard_result(self, symbol: str, timeframe_key: str, guard_result: dict) -> None:
        if not isinstance(guard_result, dict) or not guard_result.get("enabled"):
            return

        status_key = (symbol, timeframe_key or "default")
        status_signature = (
            bool(guard_result.get("active")),
            str(guard_result.get("mode")),
            str(guard_result.get("reason")),
            guard_result.get("score"),
            bool(guard_result.get("would_block")),
        )
        last_signature = self._last_guard_status.get(status_key)
        should_log = bool(guard_result.get("active")) or last_signature != status_signature
        if not should_log:
            return

        self.logger.logger.info(
            f"MODEL_GUARD - Symbol: {symbol} | TF: {timeframe_key or 'default'} | "
            f"Target: {guard_result.get('target')} | Score: {guard_result.get('score')} | "
            f"Mode: {guard_result.get('mode')} | WouldBlock: {guard_result.get('would_block')} | "
            f"Reason: {guard_result.get('reason')}"
        )
        self._last_guard_status[status_key] = status_signature

    def _already_traded_on_bar(self, symbol: str, bar_time: pd.Timestamp) -> bool:
        last_trade_time = self._last_trade_bar_time.get(symbol)
        return last_trade_time is not None and bar_time <= last_trade_time

    def _mark_traded_on_bar(self, symbol: str, bar_time: pd.Timestamp) -> None:
        self._last_trade_bar_time[symbol] = bar_time

    @staticmethod
    def _flatten_mapping(prefix, payload):
        flattened = {}
        if not isinstance(payload, dict):
            return flattened
        for key, value in payload.items():
            flat_key = f"{prefix}{key}"
            if isinstance(value, dict):
                flattened.update(LiveRunner._flatten_mapping(f"{flat_key}_", value))
            else:
                flattened[flat_key] = value
        return flattened

    @staticmethod
    def _build_market_snapshot(df: pd.DataFrame) -> dict:
        if df is None or df.empty:
            return {}

        closed_df = df.iloc[:-1].copy() if len(df) >= 2 else df.copy()
        if closed_df.empty:
            closed_df = df.copy()
        last_bar = closed_df.iloc[-1]
        close_series = closed_df["close"].astype(float)
        last_close = float(close_series.iloc[-1])
        prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else last_close

        def _return(window: int) -> float:
            if len(close_series) <= window:
                return 0.0
            base = float(close_series.iloc[-(window + 1)])
            if not base:
                return 0.0
            return (last_close / base) - 1.0

        pct_returns = close_series.pct_change().dropna()
        return {
            "closed_bar_time": closed_df.index[-1],
            "bar_open": float(last_bar.get("open", last_close)),
            "bar_high": float(last_bar.get("high", last_close)),
            "bar_low": float(last_bar.get("low", last_close)),
            "bar_close": last_close,
            "bar_range_pct": ((float(last_bar.get("high", last_close)) - float(last_bar.get("low", last_close))) / last_close) if last_close else 0.0,
            "bar_body_pct": ((last_close - float(last_bar.get("open", last_close))) / last_close) if last_close else 0.0,
            "close_return_1": ((last_close / prev_close) - 1.0) if prev_close else 0.0,
            "close_return_3": _return(3),
            "close_return_5": _return(5),
            "close_volatility_10": float(pct_returns.tail(10).std(ddof=0)) if len(pct_returns) >= 2 else 0.0,
        }

    def _match_open_trade_to_ticket(self, ticket: str, position_info: dict) -> None:
        if ticket in self._open_trades:
            trade = self._open_trades[ticket]
            trade["position_ticket"] = ticket
            return

        candidates = []
        for key, trade in self._open_trades.items():
            if trade.get("position_ticket"):
                continue
            if trade.get("symbol") != position_info.get("symbol"):
                continue
            if trade.get("side") != position_info.get("side"):
                continue
            if abs(float(trade.get("volume", 0.0)) - float(position_info.get("volume", 0.0))) > 1e-9:
                continue
            candidates.append((key, trade))

        if len(candidates) != 1:
            return

        old_key, trade = candidates[0]
        self._open_trades.pop(old_key, None)
        trade["position_ticket"] = ticket
        trade["requested_trade_id"] = old_key
        self._open_trades[ticket] = trade

    def _record_signal_snapshot(self, payload: dict) -> None:
        if self.snapshot_store is None:
            return
        self.snapshot_store.append_event("signal_snapshot", payload)

    def _log_decision_trace(self, now, current_day, symbol, df, is_new_closed_bar, signal,
                           sl, tp, risk_allowed, risk_reason, kill_switch_triggered,
                           kill_switch_reason, dry_run, order_attempted, order_result,
                           open_positions_count, global_open_positions_count=None,
                           chosen_symbol=None, reason=None, state=None, timeframe_key=None,
                           confidence=None, decision_source=None):
        """Log decision trace once per minute per symbol to avoid spam"""
        current_time = now.timestamp()
        trace_key = f"decision_trace_{symbol}_{timeframe_key or 'default'}"
        
        # Log decision trace once per minute per symbol
        if (trace_key not in self._last_decision_trace_time or 
            current_time - self._last_decision_trace_time[trace_key] >= 60):  # 1 minute
            
            # Prepare basic trace info
            rates_len = len(df) if df is not None else 0
            last_closed_bar_time = df.index[-2].strftime('%Y-%m-%d %H:%M:%S') if df is not None and len(df) >= 2 else 'N/A'
            
            # Format SL and TP with validity
            sl_valid = sl is not None and sl > 0
            tp_valid = tp is not None and tp > 0
            
            # Determine the state for the trace - if provided, use it; otherwise derive from order_result and others
            if state is None:
                if not is_new_closed_bar:
                    state = "waiting_new_bar"
                elif order_result == "no_new_bar":
                    state = "waiting_new_bar"  # This should not happen when is_new_bar=True
                elif signal in ("BUY", "SELL"):
                    if risk_allowed and not kill_switch_triggered:
                        state = "evaluating"
                    else:
                        state = "risk_blocked" if not risk_allowed else "kill_switch"
                else:
                    state = "hold_signal"
            
            # Fix inconsistency: never show order_result=no_new_bar when is_new_bar=True
            actual_order_result = order_result
            if is_new_closed_bar and order_result == "no_new_bar":
                actual_order_result = "evaluating_new_bar"
            
            self.logger.logger.info(
                f"DECISION_TRACE - now={now.strftime('%H:%M:%S')} | "
                f"day={current_day} | symbol={symbol} | chosen_symbol={chosen_symbol} | "
                f"tf={timeframe_key or 'default'} | "
                f"rates_len={rates_len} | "
                f"last_closed_bar_time={last_closed_bar_time} | "
                f"is_new_bar={is_new_closed_bar} | "
                f"state={state} | "
                f"global_open={global_open_positions_count} | symbol_open={open_positions_count} | "
                f"reason={reason} | "
                f"startup_grace_remaining={self._startup_grace_period_active} | "
                f"open_positions_count={open_positions_count} | "
                f"signal={signal} | "
                f"confidence={confidence} | "
                f"decision_source={decision_source} | "
                f"sl={sl} (valid: {sl_valid}) | tp={tp} (valid: {tp_valid}) | "
                f"risk_allowed={risk_allowed} ({risk_reason}) | "
                f"kill_switch_triggered={kill_switch_triggered} ({kill_switch_reason}) | "
                f"dry_run={dry_run} | "
                f"order_attempted={order_attempted} | "
                f"order_result={actual_order_result}"
            )
            
            self._last_decision_trace_time[trace_key] = current_time

    def _log_debug_info(self, df, symbol):
        """Log debug information showing last 3 candles and EMA values"""
        if df is not None and len(df) >= 3:
            try:
                # Show last 3 candle times and close prices
                debug_lines = [f"DEBUG_INFO - Symbol: {symbol} - Last 3 candles:"]
                for i in range(min(3, len(df))):
                    idx = -i-1
                    time_str = str(df.index[idx])
                    close_price = df['close'].iloc[idx]
                    debug_lines.append(f"  Candle {i+1}: Time={time_str}, Close={close_price}")
                
                # Calculate and show EMAs if possible
                if len(df) >= 50:  # Need at least 50 bars for EMA50
                    try:
                        import numpy as np
                        
                        # Calculate EMA50 and EMA200
                        ema50 = df['close'].ewm(span=50).mean().iloc[-1]
                        ema200 = df['close'].ewm(span=200).mean().iloc[-1] if len(df) >= 200 else "N/A"
                        
                        debug_lines.append(f"  EMA50={ema50:.5f}, EMA200={ema200:.5f if ema200 != 'N/A' else 'N/A'}")
                        
                        # Also show trend direction
                        ema_trend = "BULLISH" if ema50 > ema200 else "BEARISH" if ema200 != "N/A" and ema50 < ema200 else "INSUFFICIENT_DATA"
                        debug_lines.append(f"  Trend: {ema_trend}")
                    except Exception as e:
                        debug_lines.append(f"  EMA calculation error: {e}")
                
                # Log all debug lines
                for line in debug_lines:
                    if hasattr(self.logger.logger, 'logger'):
                        self.logger.logger.logger.debug(line)
                    
            except Exception as e:
                if hasattr(self.logger.logger, 'logger'):
                    self.logger.logger.logger.debug(f"DEBUG_INFO - Error showing debug info for {symbol}: {e}")

    def _select_preferred_candidate(self, candidates):
        if not candidates:
            return None
        if self.preferred_timeframe_key:
            preferred = next((c for c in candidates if c.get("tf_key") == self.preferred_timeframe_key), None)
            if preferred:
                return preferred
        return max(
            candidates,
            key=lambda c: (
                1 if c.get("signal") in ("BUY", "SELL") else 0,
                float(c.get("confidence", 0.0)),
            ),
        )

    def _resolve_timeframe_signal(self, candidates):
        actionable = [c for c in candidates if c.get("signal") in ("BUY", "SELL")]
        if not actionable:
            return None, "no_actionable_signal"
        directions = {c.get("signal") for c in actionable}
        if len(directions) > 1:
            preferred = self._select_preferred_candidate(actionable)
            if preferred and self.preferred_timeframe_key:
                return preferred, "conflict_prefer_timeframe"
            return None, "timeframe_conflict"
        preferred = self._select_preferred_candidate(actionable)
        return preferred or actionable[0], "signal_selected"

    def _reset_daily_if_needed(self, equity: float):
        today = datetime.now().date()
        if self._daily_date != today:
            self._daily_date = today
            self._daily_start_equity = equity
            if self.risk_manager is not None:
                self.risk_manager.on_new_day(today)

    def _get_available_symbols(self) -> list:
        """Get the list of available symbols based on auto mode or fixed symbol"""
        if self.symbol == "AUTO":
            return get_symbols_for_today()
        return [self.symbol] if self.symbol else []

    def _normalize_position(self, pos):
        if isinstance(pos, dict):
            return {
                "ticket": str(pos.get("ticket") or pos.get("id")),
                "symbol": pos.get("symbol"),
                "profit": float(pos.get("pnl", 0.0)),
                "volume": float(pos.get("volume", 0.0)),
                "side": pos.get("side"),
                "open_time": pos.get("open_time"),
            }
        return {
            "ticket": str(getattr(pos, "ticket", "")),
            "symbol": getattr(pos, "symbol", None),
            "profit": float(getattr(pos, "profit", 0.0)),
            "volume": float(getattr(pos, "volume", 0.0)),
            "side": "BUY" if getattr(pos, "type", 0) == 0 else "SELL",
            "open_time": getattr(pos, "time", None),
        }

    def _sync_positions(self, positions):
        current = {}
        for pos in positions or []:
            info = self._normalize_position(pos)
            if info["ticket"]:
                current[info["ticket"]] = info

        previous_tickets = set(self._open_positions_snapshot.keys())
        new_tickets = [ticket for ticket in current.keys() if ticket not in previous_tickets]
        for ticket in new_tickets:
            self._match_open_trade_to_ticket(ticket, current[ticket])

        closed_tickets = [t for t in self._open_positions_snapshot.keys() if t not in current]
        for ticket in closed_tickets:
            closed = self._open_positions_snapshot[ticket]
            pnl = closed.get("profit", 0.0)
            symbol = closed.get("symbol")
            closed_at = datetime.now()
            trade_meta = self._open_trades.get(ticket, {})

            if self.risk_manager is not None:
                self.risk_manager.record_trade_close(pnl, closed_at, symbol)
            if self.decision_guard is not None:
                self.decision_guard.record_trade_close(
                    symbol=symbol,
                    side=closed.get("side"),
                    volume=closed.get("volume", 0.0),
                    pnl=pnl,
                )

            self._reporter.record_trade_close(
                trade_id=ticket,
                symbol=symbol,
                side=closed.get("side"),
                volume=closed.get("volume", 0.0),
                open_time=closed.get("open_time"),
                close_time=closed_at,
                pnl=pnl,
            )

            if self.snapshot_store is not None:
                self.snapshot_store.append_event(
                    "trade_closed",
                    {
                        "trade_id": ticket,
                        "requested_trade_id": trade_meta.get("requested_trade_id"),
                        "snapshot_id": trade_meta.get("snapshot_id"),
                        "symbol": symbol,
                        "side": closed.get("side"),
                        "volume": closed.get("volume", 0.0),
                        "open_time": closed.get("open_time"),
                        "close_time": closed_at,
                        "pnl": pnl,
                    },
                )

            if ticket in self._open_trades:
                self._open_trades.pop(ticket, None)

        self._open_positions_snapshot = current

    def _count_open_positions(self, positions, symbol: str = None) -> int:
        if not positions:
            return 0
        if symbol is None:
            return len(positions)
        count = 0
        for pos in positions:
            if isinstance(pos, dict):
                pos_symbol = pos.get("symbol")
            else:
                pos_symbol = getattr(pos, "symbol", None)
            if pos_symbol == symbol:
                count += 1
        return count

    def run(self):
        """Run the live trading loop"""
        # Connect and perform startup check
        if hasattr(self.exchange, 'connect'):
            connect_success = self.exchange.connect()
            if not connect_success:
                self.logger.error("Failed to connect to exchange. Exiting.")
                return
        else:
            # Fallback to old method for backward compatibility
            self.exchange.connect()

        # Perform startup check
        try:
            account_info = self.exchange.account_info()
            if hasattr(self.exchange, 'login'):
                account_mode = "LIVE" if not getattr(self.exchange, 'dry_run', True) else "DRY_RUN"
                self.logger.logger.info(f"=== STARTUP CHECK ===")
                self.logger.logger.info(f"MT5 Account connected - Login: {self.exchange.login}")
                self.logger.logger.info(f"Server: {getattr(self.exchange, 'server', 'Unknown')}")
                self.logger.logger.info(f"Mode: {account_mode}")
                self.logger.logger.info(f"Balance: {account_info.balance}")
                self.logger.logger.info(f"Equity: {account_info.equity}")
                self.logger.logger.info(f"=====================")
            else:
                account_mode = "DRY_RUN" if getattr(self.exchange, 'dry_run', True) else "SIMULATION"
                self.logger.logger.info(f"=== STARTUP CHECK ===")
                self.logger.logger.info(f"Simulated Account Connected")
                self.logger.logger.info(f"Mode: {account_mode}")
                self.logger.logger.info(f"Balance: {account_info.balance}")
                self.logger.logger.info(f"Equity: {account_info.equity}")
                self.logger.logger.info(f"=====================")
        except Exception as e:
            self.logger.error(f"Failed to perform startup check: {e}")

        # Initial sync
        snap = self.exchange.account_info()
        self._reset_daily_if_needed(snap.equity)

        # Get initial symbols
        self._available_symbols = self._get_available_symbols()
        if self._available_symbols:
            self._current_symbol = self._available_symbols[0]

        # Get initial market data to set up startup grace period across all symbol/timeframe pairs
        if self._available_symbols:
            timeframes = self.timeframes if self.timeframes else [{"key": None, "value": self.timeframe}]
            for initial_symbol in self._available_symbols:
                for tf in timeframes:
                    tf_key = tf.get("key")
                    tf_value = tf.get("value")
                    if tf_value is None:
                        continue
                    df = self.exchange.get_rates(initial_symbol, tf_value, count=300)
                    if df is not None and not df.empty and len(df) >= 3:
                        bar_key = (initial_symbol, tf_key or "default")
                        self._last_closed_bar_times[bar_key] = df.index[-2]

        try:
            while True:
                # Get current symbols (may change based on day)
                new_available_symbols = self._get_available_symbols()
                current_day = datetime.now().strftime("%A")
                current_date = datetime.now().date()
                
                # Only log day change or heartbeat every 5 minutes (300 seconds)
                current_time = datetime.now().timestamp()
                day_key = "day_change"
                heartbeat_key = "heartbeat"
                
                # Log day change
                if (day_key not in self.logger.last_log_time or 
                    current_time - self.logger.last_log_time[day_key] >= 86400):  # 24 hours
                    self.logger.logger.info(f"[LiveRunner] DAY CHANGE - Today={current_day} | Active Symbols={new_available_symbols}")
                    self.logger.last_log_time[day_key] = current_time
                
                # Log heartbeat every 5 minutes
                if (heartbeat_key not in self.logger.last_log_time or 
                    current_time - self.logger.last_log_time[heartbeat_key] >= 300):  # 5 minutes
                    self.logger.logger.info(f"[LiveRunner] HEARTBEAT - Today={current_day} | Active Symbols={new_available_symbols}")
                    self.logger.last_log_time[heartbeat_key] = current_time

                # Check for symbol universe change - dynamic weekday changes
                if self._available_symbols != new_available_symbols:
                    old_symbols = self._available_symbols
                    self._available_symbols = new_available_symbols
                    if self._available_symbols:
                        self._current_symbol = self._available_symbols[0]  # Use first available symbol
                    
                    self.logger.logger.info(f"SYMBOL_UNIVERSE_CHANGED old={old_symbols} new={new_available_symbols} day={current_day}")
                
                # Check for date change (handles week transition even if symbols don't change)
                if self._daily_date != current_date:
                    if self._daily_date is not None:
                        self._reporter.export_daily_report(self._daily_date)
                    old_symbols = self._available_symbols
                    new_symbols_for_date = self._get_available_symbols()
                    if new_symbols_for_date != self._available_symbols:
                        self._available_symbols = new_symbols_for_date
                        if self._available_symbols:
                            self._current_symbol = self._available_symbols[0]
                    
                    self.logger.logger.info(f"DATE_CHANGED old={self._daily_date} new={current_date} symbols_old={old_symbols} symbols_new={self._available_symbols}")

                # Sync account info
                snap = self.exchange.account_info()
                self._reset_daily_if_needed(snap.equity)
                daily_pnl = (snap.equity - self._daily_start_equity) if self._daily_start_equity is not None else 0.0
                daily_pnl_pct = (daily_pnl / self._daily_start_equity) if self._daily_start_equity else 0.0
                if self.risk_manager is not None:
                    self.risk_manager.update_daily(daily_pnl, daily_pnl_pct, datetime.now())

                # Check open positions globally (for reporting only)
                all_positions = self.exchange.positions()
                self._sync_positions(all_positions)

                # Iterate through available symbols to find trading opportunity
                signal_found = False
                active_symbol_set = set(self._available_symbols or [])
                for pos in all_positions or []:
                    pos_symbol = pos.get("symbol") if isinstance(pos, dict) else getattr(pos, "symbol", None)
                    if pos_symbol and pos_symbol not in active_symbol_set:
                        self.logger.info(f"IGNORED_INACTIVE_POSITION - {pos_symbol} open but market inactive today")
                for symbol in self._available_symbols:
                    if signal_found:
                        break  # Only process one signal per cycle

                    # Get floating PnL for current symbol specifically
                    floating = self.exchange.floating_pnl(symbol=symbol) if symbol else 0.0
                    daily_pnl = (snap.equity - self._daily_start_equity) if self._daily_start_equity is not None else 0.0

                    # Collect market data across configured timeframes
                    timeframes = self.timeframes if self.timeframes else [{"key": None, "value": self.timeframe}]
                    tf_data = []
                    for tf in timeframes:
                        tf_key = tf.get("key")
                        tf_value = tf.get("value")
                        if tf_value is None:
                            continue
                        df = self.exchange.get_rates(symbol, tf_value, count=300)
                        if df is None or df.empty:
                            continue
                        analysis_df = self._analysis_view(df)
                        is_new = self._is_new_closed_bar(df, symbol, tf_key)
                        tf_data.append({
                            "tf_key": tf_key,
                            "tf_value": tf_value,
                            "df": df,
                            "analysis_df": analysis_df,
                            "is_new": is_new,
                            "closed_bar_time": df.index[-2] if len(df) >= 2 else None,
                        })

                    if not tf_data:
                        continue

                    new_bar_candidates = [c for c in tf_data if c["is_new"]]
                    has_new_bar = bool(new_bar_candidates)
                    trace_pool = new_bar_candidates if has_new_bar else tf_data
                    trace_candidate = self._select_preferred_candidate(trace_pool)
                    df = trace_candidate["df"]
                    is_new_closed_bar = trace_candidate["is_new"]
                    timeframe_key = trace_candidate["tf_key"]
                    
                    # Count open positions for this symbol using global snapshot
                    open_positions_count = self._count_open_positions(all_positions, symbol)
                    global_open_positions_active = 0
                    if self._available_symbols:
                        for active_symbol in self._available_symbols:
                            global_open_positions_active += self._count_open_positions(all_positions, active_symbol)
                    
                    # Kill switch check (if provided) - per symbol
                    if self.kill_switch is not None:
                        # You can feed it with your own metrics; minimal example:
                        metrics = {
                            "equity": snap.equity,
                            "balance": snap.balance,
                            "daily_pnl": daily_pnl,
                            "floating_pnl": floating,
                            "symbols_scanned": self._available_symbols,
                            "chosen_symbol": symbol,
                            "day": datetime.now().strftime("%A"),
                        }
                        decision = self.kill_switch.evaluate(metrics)  # depending on your signature
                        if decision.get("triggered"):
                            self.logger.error(f"KILL SWITCH TRIGGERED: {decision}")
                            time.sleep(self.poll_seconds)
                            continue

                    # Default values for decision trace
                    signal = "HOLD"  # Will be updated if new bar
                    sl, tp = None, None
                    risk_allowed = True
                    risk_reason = "OK"
                    dry_run = getattr(self.exchange, 'dry_run', True)
                    confidence = None
                    decision_source = None
                    state = "waiting_new_bar"  # State for decision trace
                    order_result = "no_new_bar"
                    
                    # Check kill switch for decision trace
                    kill_switch_triggered = False
                    kill_switch_reason = ""
                    if self.kill_switch is not None:
                        metrics = {
                            "equity": snap.equity,
                            "balance": snap.balance,
                            "daily_pnl": daily_pnl,
                            "floating_pnl": floating,
                            "symbols_scanned": self._available_symbols,
                            "chosen_symbol": symbol,
                            "day": current_day,
                        }
                        decision = self.kill_switch.evaluate(metrics)
                        if decision.get("triggered"):
                            kill_switch_triggered = True
                            kill_switch_reason = decision.get("reason", "Unknown reason")
                    
                    # Generate decision trace once per minute per symbol (with default values when no new bar)
                    if has_new_bar:
                        state = "evaluating"
                        order_result = "evaluating_new_bar"
                    else:
                        state = "waiting_new_bar"
                        order_result = "waiting_for_new_bar"
                    
                    self._log_decision_trace(
                        datetime.now(), current_day, symbol, df, is_new_closed_bar, 
                        signal, sl, tp, risk_allowed, risk_reason, 
                        kill_switch_triggered, kill_switch_reason, 
                        dry_run, False, order_result, 
                        open_positions_count, global_open_positions_active, symbol, "waiting_new_bar_for_symbol", state,
                        timeframe_key=timeframe_key,
                        confidence=confidence,
                        decision_source=decision_source
                    )

                    # Only act on new closed bar (any timeframe) and after startup grace period
                    if has_new_bar:
                        # Disable startup grace period after first closed bar seen
                        if self._startup_grace_period_active:
                            self._startup_grace_period_active = False
                            self.logger.info("Startup grace period ended. Ready to trade.")

                        # Generate signal only after startup grace period
                        if not self._startup_grace_period_active:
                            self._current_symbol = symbol
                            hold_reason_msg = ""
                            selected_reason = "signal_selected"
                            
                            # Generate signal per timeframe (new bars only)
                            for candidate in new_bar_candidates:
                                candidate["signal"] = "HOLD"
                                candidate["confidence"] = 0.0
                                candidate["decision_source"] = "base_strategy"
                                candidate["decision_reason"] = "no_signal"
                                try:
                                    if hasattr(self.strategy, "generate_decision"):
                                        try:
                                            import inspect
                                            decision_sig = inspect.signature(self.strategy.generate_decision)
                                            if "symbol" in decision_sig.parameters:
                                                decision = self.strategy.generate_decision(candidate["analysis_df"], symbol=symbol)
                                            else:
                                                decision = self.strategy.generate_decision(candidate["analysis_df"])
                                        except (TypeError, ValueError):
                                            decision = self.strategy.generate_decision(candidate["analysis_df"])

                                        if isinstance(decision, dict):
                                            candidate["decision"] = decision
                                            candidate["signal"] = decision.get("signal", "HOLD")
                                            candidate["confidence"] = float(decision.get("confidence", 0.0) or 0.0)
                                            candidate["decision_source"] = decision.get("source", "strategy_decision")
                                            candidate["decision_reason"] = decision.get("reason", "decision_returned")
                                        else:
                                            candidate["signal"] = decision or "HOLD"
                                    else:
                                        candidate["signal"] = self.strategy.generate_signal(candidate["analysis_df"])
                                        if candidate["signal"] in ("BUY", "SELL"):
                                            candidate["confidence"] = 0.55
                                except AttributeError:
                                    self.logger.logger.warning("Strategy missing generate_signal method, defaulting to HOLD")
                                    candidate["signal"] = "HOLD"
                                except Exception as e:
                                    self.logger.logger.warning(f"Strategy signal error for {symbol}: {e}")
                                    candidate["signal"] = "HOLD"
                                    candidate["decision_reason"] = f"strategy_signal_error: {e}"

                            chosen_candidate, selected_reason = self._resolve_timeframe_signal(new_bar_candidates)
                            if chosen_candidate is None:
                                # No actionable signal or conflict
                                hold_candidate = self._select_preferred_candidate(new_bar_candidates)
                                if hold_candidate:
                                    df = hold_candidate["df"]
                                    analysis_df = hold_candidate["analysis_df"]
                                    timeframe_key = hold_candidate["tf_key"]
                                else:
                                    analysis_df = self._analysis_view(df)
                                signal = "HOLD"
                                confidence = hold_candidate.get("confidence") if hold_candidate else None
                                decision_source = hold_candidate.get("decision_source") if hold_candidate else None
                                if selected_reason == "timeframe_conflict":
                                    hold_reason_msg = f" (timeframe conflict, prefer {self.preferred_timeframe_key or 'none'})"
                                else:
                                    if hold_candidate and hold_candidate.get("decision_reason"):
                                        hold_reason_msg = f" ({hold_candidate.get('decision_reason')})"
                                    elif hasattr(self.strategy, 'hold_reason'):
                                        try:
                                            reason = self.strategy.hold_reason(analysis_df)
                                            if reason:
                                                hold_reason_msg = f" ({reason})"
                                        except Exception as e:
                                            hold_reason_msg = f" (error getting reason: {e})"
                                    else:
                                        hold_reason_msg = " (no entry conditions met)"

                                self.logger.logger.info(
                                    f"NO_TRADE - Symbol: {symbol} | TF: {timeframe_key or 'default'} | "
                                    f"Reason: {selected_reason}{hold_reason_msg}"
                                )
                                snapshot_id = self.snapshot_store.next_snapshot_id(symbol, datetime.now()) if self.snapshot_store is not None else None
                                snapshot_payload = {
                                    "snapshot_id": snapshot_id,
                                    "event_time": datetime.now(),
                                    "symbol": symbol,
                                    "timeframe_key": timeframe_key or "default",
                                    "selected_reason": selected_reason,
                                    "signal": signal,
                                    "confidence": confidence,
                                    "decision_source": decision_source,
                                    "decision_reason": hold_candidate.get("decision_reason") if hold_candidate else selected_reason,
                                    "hold_reason": hold_reason_msg.strip() if hold_reason_msg else "",
                                    "risk_allowed": risk_allowed,
                                    "risk_reason": selected_reason,
                                    "kill_switch_triggered": kill_switch_triggered,
                                    "kill_switch_reason": kill_switch_reason,
                                    "order_attempted": False,
                                    "order_result": selected_reason,
                                    "balance": snap.balance,
                                    "equity": snap.equity,
                                    "daily_pnl": daily_pnl,
                                    "floating_pnl": floating,
                                    "symbol_open_positions_count": open_positions_count,
                                    "global_open_positions_count": global_open_positions_active,
                                }
                                snapshot_payload.update(self._flatten_mapping("decision_", hold_candidate.get("decision", {}) if hold_candidate else {}))
                                snapshot_payload.update(self._flatten_mapping("market_", self._build_market_snapshot(df)))
                                self._record_signal_snapshot(snapshot_payload)
                                self._log_decision_trace(
                                    datetime.now(), current_day, symbol, df, True,
                                    signal, sl, tp, risk_allowed, selected_reason,
                                    kill_switch_triggered, kill_switch_reason,
                                    dry_run, False, selected_reason,
                                    open_positions_count, global_open_positions_active, symbol, selected_reason, "hold_signal",
                                    timeframe_key=timeframe_key,
                                    confidence=confidence,
                                    decision_source=decision_source
                                )
                                continue

                            # Use chosen timeframe for trading logic
                            df = chosen_candidate["df"]
                            analysis_df = chosen_candidate["analysis_df"]
                            timeframe_key = chosen_candidate["tf_key"]
                            signal = chosen_candidate.get("signal", "HOLD")
                            closed_bar_time = chosen_candidate.get("closed_bar_time")
                            confidence = chosen_candidate.get("confidence")
                            decision_source = chosen_candidate.get("decision_source")
                            chosen_decision = chosen_candidate.get("decision", {})
                            snapshot_id = self.snapshot_store.next_snapshot_id(symbol, datetime.now()) if self.snapshot_store is not None else None
                            entry_price = None
                            guard_result = None

                            # Check for hold reason if strategy supports it
                            if signal == "HOLD":
                                if chosen_candidate.get("decision_reason"):
                                    hold_reason_msg = f" ({chosen_candidate.get('decision_reason')})"
                                elif hasattr(self.strategy, 'hold_reason'):
                                    try:
                                        reason = self.strategy.hold_reason(analysis_df)
                                        if reason:
                                            hold_reason_msg = f" ({reason})"
                                    except Exception as e:
                                        hold_reason_msg = f" (error getting reason: {e})"
                                else:
                                    hold_reason_msg = " (no entry conditions met)"

                            # Default values
                            sl, tp, volume = None, None, 0
                            sl_valid, tp_valid = False, False
                            risk_allowed = True
                            risk_reason = "OK"
                            order_attempted = False
                            order_result = "conditions_not_met"
                            state = "evaluating"
                            
                            # Calculate stop loss and take profit if there's a trading signal
                            if signal in ("BUY", "SELL"):
                                try:
                                    if hasattr(self.strategy, 'compute_sl_tp'):
                                        try:
                                            import inspect
                                            sig = inspect.signature(self.strategy.compute_sl_tp)
                                            if "symbol" in sig.parameters:
                                                sl, tp = self.strategy.compute_sl_tp(analysis_df, signal, symbol=symbol)
                                            else:
                                                sl, tp = self.strategy.compute_sl_tp(analysis_df, signal)
                                        except (TypeError, ValueError):
                                            sl, tp = self.strategy.compute_sl_tp(analysis_df, signal)
                                        sl_valid = sl is not None and sl > 0
                                        tp_valid = tp is not None and tp > 0
                                    else:
                                        self.logger.logger.warning(f"Strategy missing compute_sl_tp method for {symbol}")
                                        sl, tp = None, None
                                        sl_valid, tp_valid = False, False
                                except Exception as e:
                                    self.logger.logger.warning(f"Failed to compute SL/TP for {symbol}: {e}")
                                    sl_valid, tp_valid = False, False

                                # Validate SL/TP logic
                                if sl is not None and tp is not None and sl_valid and tp_valid:
                                    current_price = float(analysis_df['close'].iloc[-1])
                                    if signal == "BUY":
                                        # BUY: sl < price < tp
                                        if not (sl < current_price < tp):
                                            self.logger.logger.warning(f"SL/TP validation failed for {symbol} BUY: SL({sl}) < Price({current_price}) < TP({tp}) not satisfied")
                                            sl_valid = tp_valid = False
                                    elif signal == "SELL":
                                        # SELL: tp < price < sl
                                        if not (tp < current_price < sl):
                                            self.logger.logger.warning(f"SL/TP validation failed for {symbol} SELL: TP({tp}) < Price({current_price}) < SL({sl}) not satisfied")
                                            sl_valid = tp_valid = False

                            # Calculate volume if needed
                            if signal in ("BUY", "SELL"):
                                try:
                                    entry_price = float(analysis_df["close"].iloc[-1])
                                    if self.risk_manager is not None and hasattr(self.risk_manager, "compute_position_size"):
                                        volume = self.risk_manager.compute_position_size(
                                            symbol=symbol,
                                            account_snapshot=snap,
                                            entry_price=entry_price,
                                            sl_price=sl,
                                            tp_price=tp,
                                            exchange=self.exchange,
                                            now=datetime.now(),
                                            confidence=confidence,
                                        )
                                        logging.getLogger(__name__).info(
                                            f"POSITION_SIZE - {symbol} entry={entry_price:.5f} sl={sl} "
                                            f"confidence={confidence} volume={volume:.4f}"
                                        )

                                    if volume <= 0 and hasattr(self.strategy, 'compute_volume'):
                                        try:
                                            import inspect
                                            volume_sig = inspect.signature(self.strategy.compute_volume)
                                            compute_kwargs = {}
                                            if "symbol" in volume_sig.parameters:
                                                compute_kwargs["symbol"] = symbol
                                            if "sl" in volume_sig.parameters:
                                                compute_kwargs["sl"] = sl
                                            if "tp" in volume_sig.parameters:
                                                compute_kwargs["tp"] = tp
                                            volume = self.strategy.compute_volume(analysis_df, signal, snap.equity, **compute_kwargs)
                                        except (TypeError, ValueError):
                                            volume = self.strategy.compute_volume(analysis_df, signal, snap.equity)
                                    elif volume <= 0:
                                        self.logger.logger.warning(f"No volume calculator available for {symbol}")
                                except Exception as e:
                                    self.logger.logger.warning(f"Failed to compute volume for {symbol}: {e}")
                                    volume = 0.0

                            # Check if risk is allowed
                            if self.risk_manager is not None and signal in ("BUY", "SELL"):
                                try:
                                    if hasattr(self.risk_manager, 'allow_trade'):
                                        risk_allowed, risk_reason = self.risk_manager.allow_trade(
                                            signal, sl, tp, snap,
                                            symbol=symbol,
                                            df=df,
                                            reference_price=entry_price,
                                            exchange=self.exchange,
                                            now=datetime.now(),
                                            symbol_open_positions_count=open_positions_count,
                                            global_open_positions_count=global_open_positions_active,
                                        )
                                        if not isinstance(risk_allowed, bool):
                                            risk_allowed = bool(risk_allowed)
                                            risk_reason = risk_reason or "Risk manager response normalized"
                                    else:
                                        risk_allowed = False
                                        risk_reason = "Risk manager missing allow_trade method"
                                except Exception as e:
                                    risk_allowed = False
                                    risk_reason = f"Risk manager error: {e}"

                            if self.decision_guard is not None and signal in ("BUY", "SELL") and volume > 0:
                                try:
                                    guard_result = self.decision_guard.evaluate(symbol=symbol, side=signal, volume=volume)
                                    self._log_model_guard_result(symbol, timeframe_key, guard_result)
                                    if guard_result.get("active") and guard_result.get("mode") == "enforce" and guard_result.get("would_block"):
                                        risk_allowed = False
                                        risk_reason = f"model_big_loss_block:{guard_result.get('score')}"
                                except Exception as e:
                                    guard_result = {
                                        "enabled": True,
                                        "active": False,
                                        "mode": "shadow",
                                        "score": None,
                                        "would_block": False,
                                        "should_throttle": False,
                                        "recommended_volume_factor": 1.0,
                                        "reason": f"guard_error:{e}",
                                    }

                            # Determine if in dry run mode (check if exchange has a dry_run attribute or similar)
                            dry_run = getattr(self.exchange, 'dry_run', True)  # Default to True if not specified

                            # Check all conditions before placing trade
                            if signal in ("BUY", "SELL"):
                                # Check all conditions
                                sl_tp_ok = sl_valid and tp_valid
                                has_volume_calculator = (
                                    (self.risk_manager is not None and hasattr(self.risk_manager, "compute_position_size"))
                                    or hasattr(self.strategy, "compute_volume")
                                )
                                strategy_methods_ok = hasattr(self.strategy, 'compute_sl_tp') and has_volume_calculator
                                
                                if not strategy_methods_ok:
                                    state = "hold_signal"
                                    order_result = "missing_strategy_method"
                                    risk_reason = "missing_strategy_method"
                                    risk_allowed = False
                                    self.logger.logger.info(f"NO_TRADE - Symbol: {symbol} | TF: {timeframe_key or 'default'} | Reason: Missing strategy methods")
                                elif not sl_tp_ok:
                                    state = "risk_blocked"
                                    order_result = "invalid_sl_tp"
                                    risk_reason = "invalid_sl_tp"
                                    risk_allowed = False
                                    self.logger.logger.info(f"NO_TRADE - Symbol: {symbol} | TF: {timeframe_key or 'default'} | Reason: Invalid SL/TP values")
                                elif volume <= 0:
                                    state = "risk_blocked"
                                    order_result = "invalid_volume"
                                    risk_reason = "invalid_volume"
                                    risk_allowed = False
                                    self.logger.logger.info(
                                        f"NO_TRADE - Symbol: {symbol} | TF: {timeframe_key or 'default'} | "
                                        f"Reason: Invalid computed volume"
                                    )
                                elif risk_allowed and not kill_switch_triggered:
                                    if self._already_traded_on_bar(symbol, closed_bar_time):
                                        state = "risk_blocked"
                                        order_result = "already_traded_on_bar"
                                        self.logger.logger.info(f"NO_TRADE - Symbol: {symbol} | TF: {timeframe_key or 'default'} | Reason: already traded on bar {closed_bar_time}")
                                    else:
                                        # All conditions met, try to place order
                                        try:
                                            self._mark_traded_on_bar(symbol, closed_bar_time)
                                            ok = self.exchange.place_market_order(
                                                symbol=symbol,
                                                side=signal,
                                                volume=volume,
                                                sl=sl,
                                                tp=tp,
                                                comment="TradePy Live"
                                            )
                                            order_attempted = True
                                            if hasattr(ok, "success"):
                                                order_success = ok.success
                                                order_id = ok.order_id
                                                retcode = ok.retcode
                                            else:
                                                order_success = bool(ok)
                                                order_id = None
                                                retcode = None

                                            if order_success:
                                                signal_found = True  # Only process one signal per cycle
                                                state = "order_sent"
                                                order_result = "success"
                                                extra = f" | OrderID: {order_id}" if order_id else ""
                                                self.logger.logger.info(f"ORDER_SENT - Symbol: {symbol} | TF: {timeframe_key or 'default'} | {signal} {volume} | SL: {sl} | TP: {tp}{extra}")
                                                trade_id = order_id or f"{symbol}_{int(time.time())}"
                                                self._open_trades[trade_id] = {
                                                    "trade_id": trade_id,
                                                    "symbol": symbol,
                                                    "side": signal,
                                                    "volume": volume,
                                                    "open_time": datetime.now(),
                                                    "snapshot_id": snapshot_id,
                                                }
                                                if self.snapshot_store is not None:
                                                    self.snapshot_store.append_event(
                                                        "trade_opened",
                                                        {
                                                            "trade_id": trade_id,
                                                            "snapshot_id": snapshot_id,
                                                            "symbol": symbol,
                                                            "side": signal,
                                                            "volume": volume,
                                                            "open_time": datetime.now(),
                                                            "timeframe_key": timeframe_key or "default",
                                                            "entry_price": entry_price,
                                                            "sl": sl,
                                                            "tp": tp,
                                                        },
                                                    )
                                                if self.risk_manager is not None:
                                                    self.risk_manager.record_trade_open(datetime.now(), symbol)
                                            else:
                                                state = "order_failed"
                                                order_result = "failed_place_market_order"
                                                extra = f" | Retcode: {retcode}" if retcode is not None else ""
                                                self.logger.logger.error(f"ORDER_FAILED - Symbol: {symbol} | TF: {timeframe_key or 'default'} | Could not place order{extra}")
                                            break
                                        except Exception as e:
                                            order_attempted = True
                                            state = "order_failed"
                                            order_result = f"exception: {str(e)}"
                                            self.logger.logger.error(f"ORDER_ERROR - Symbol: {symbol} | TF: {timeframe_key or 'default'} | Error: {e}")
                                else:
                                    # Trade blocked by risk or kill switch
                                    order_attempted = False
                                    order_result = "risk_or_kill_switch_blocked"
                                    
                                    reason_parts = []
                                    if not risk_allowed:
                                        reason_parts.append(f"risk blocked: {risk_reason}")
                                    if kill_switch_triggered:
                                        reason_parts.append(f"kill switch: {kill_switch_reason}")
                                        
                                    if signal == "HOLD":
                                        reason_parts.append("HOLD signal")
                                        
                                    state = "risk_blocked" if not risk_allowed else "kill_switch"
                                    reason_str = '; '.join(reason_parts) if reason_parts else 'conditions not met'
                                    self.logger.logger.info(f"NO_TRADE - Symbol: {symbol} | TF: {timeframe_key or 'default'} | Reason: {reason_str}")
                            else:
                                # Hold signal
                                state = "hold_signal"
                                order_result = "hold_signal"
                                order_attempted = False
                                self.logger.logger.debug(f"HOLD reason - Symbol: {symbol} | TF: {timeframe_key or 'default'} | HOLD signal{hold_reason_msg}")
                                self.logger.logger.info(f"NO_TRADE - Symbol: {symbol} | TF: {timeframe_key or 'default'} | Reason: HOLD signal")

                            snapshot_payload = {
                                "snapshot_id": snapshot_id,
                                "event_time": datetime.now(),
                                "symbol": symbol,
                                "timeframe_key": timeframe_key or "default",
                                "selected_reason": selected_reason,
                                "signal": signal,
                                "confidence": confidence,
                                "decision_source": decision_source,
                                "decision_reason": chosen_candidate.get("decision_reason"),
                                "hold_reason": hold_reason_msg.strip() if hold_reason_msg else "",
                                "entry_price": entry_price,
                                "sl": sl,
                                "tp": tp,
                                "volume": volume,
                                "risk_allowed": risk_allowed,
                                "risk_reason": risk_reason,
                                "kill_switch_triggered": kill_switch_triggered,
                                "kill_switch_reason": kill_switch_reason,
                                "order_attempted": order_attempted,
                                "order_result": order_result,
                                "balance": snap.balance,
                                "equity": snap.equity,
                                "daily_pnl": daily_pnl,
                                "floating_pnl": floating,
                                "symbol_open_positions_count": open_positions_count,
                                "global_open_positions_count": global_open_positions_active,
                            }
                            snapshot_payload.update(self._flatten_mapping("decision_", chosen_decision))
                            snapshot_payload.update(self._flatten_mapping("market_", self._build_market_snapshot(df)))
                            if isinstance(guard_result, dict):
                                guard_meta = dict(guard_result)
                                regime_features = guard_meta.pop("feature_row", {})
                                snapshot_payload.update(self._flatten_mapping("guard_", guard_meta))
                                snapshot_payload.update(self._flatten_mapping("regime_", regime_features))
                            self._record_signal_snapshot(snapshot_payload)
                            
                            # After processing, log the complete decision trace with updated values
                            self._log_decision_trace(
                                datetime.now(), current_day, symbol, df, is_new_closed_bar, 
                                signal, sl, tp, risk_allowed, risk_reason, 
                                kill_switch_triggered, kill_switch_reason, 
                                dry_run, order_attempted, order_result, 
                                open_positions_count, global_open_positions_active, symbol, risk_reason, state,
                                timeframe_key=timeframe_key,
                                confidence=confidence,
                                decision_source=decision_source
                            )
                            
                            # In DEBUG mode, show the last 3 candles and EMA values
                            internal_logger = self.logger.logger.logger if hasattr(self.logger.logger, 'logger') else None
                            if internal_logger and internal_logger.level <= logging.DEBUG:
                                self._log_debug_info(df, symbol)
                    else:
                        # Log status even when not trading (using rate-limited logger to reduce noise)
                        if symbol == self._available_symbols[0]:  # Only log once per cycle
                            # Use rate-limited logging for "waiting" messages to reduce noise
                            self.logger.info(f"[{datetime.now().strftime('%A')}] {', '.join(self._available_symbols)} | "
                                  f"Scanning symbols (current={symbol}) | Waiting for new bar | Bal={snap.balance:.2f} Eq={snap.equity:.2f} "
                                  f"Float={floating:.2f} DailyPnL={daily_pnl:.2f}", key="waiting_for_bar")

                time.sleep(self.poll_seconds)

        finally:
            if hasattr(self.exchange, 'shutdown'):
                self.exchange.shutdown()
            if self._daily_date is not None:
                self._reporter.export_daily_report(self._daily_date)

"""
Live runner for TradePy bot
"""

import time
import logging
import os
from dataclasses import asdict
from datetime import datetime
import pandas as pd
from core.models import TradeState
from core.utils.symbol_schedule import get_symbols_for_today
from utils.logger import RateLimitedLogger
from core.exchange.live_interface import LiveExchangeInterface
from core.reporting.trade_reporter import TradeReporter
from core.trading.auto_close_scheduler import AutoCloseScheduler


class LiveRunner:
    """Main runner for live trading"""

    def __init__(self, strategy, exchange: LiveExchangeInterface, risk_manager=None, kill_switch=None,
                 decision_guard=None, snapshot_store=None,
                 symbol: str = "AUTO", timeframe=None, timeframes=None, preferred_timeframe=None,
                 poll_seconds: int = 5, scalping_config=None, intra_bar_config=None):
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
        self.scalping_config = scalping_config if isinstance(scalping_config, dict) else {}
        self.intra_bar_config = intra_bar_config if isinstance(intra_bar_config, dict) else {}

        self._available_symbols = []
        self._current_symbol = None
        self._last_closed_bar_times = {}  # Track last processed bar time per symbol/timeframe
        self._last_trade_bar_time = {}  # Track last bar where a trade was attempted per symbol
        self._bar_trade_state = {}
        self._last_closed_trade_by_symbol = {}
        self._startup_grace_period_active = True
        self._daily_start_equity = None
        self._daily_date = None
        self._last_decision_trace_time = {}  # Track when decision trace was last logged per symbol/timeframe
        self._last_guard_status = {}
        self._open_positions_snapshot = {}
        self._open_trades = {}
        self._session_close_attempts = {}
        self._session_close_retry_seconds = 60
        self._reporter = TradeReporter()
        
        # Initialize auto-close scheduler to close trades after 90 minutes
        self.auto_close_scheduler = AutoCloseScheduler(exchange, timeout_minutes=90)

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

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    def _is_scalping_enabled(self) -> bool:
        return bool(self.scalping_config.get("enabled", False))

    def _is_intra_bar_enabled(self) -> bool:
        return bool(self.intra_bar_config.get("enabled", False))

    def _get_symbol_config(self, base_config: dict, symbol: str) -> dict:
        config = dict(base_config) if isinstance(base_config, dict) else {}
        symbol_overrides = config.pop("symbol_overrides", {})
        if symbol and isinstance(symbol_overrides, dict):
            symbol_config = symbol_overrides.get(symbol, {})
            if isinstance(symbol_config, dict):
                config.update(symbol_config)
        return config

    def _get_scalping_symbol_config(self, symbol: str) -> dict:
        return self._get_symbol_config(self.scalping_config, symbol)

    def _get_intra_bar_symbol_config(self, symbol: str) -> dict:
        return self._get_symbol_config(self.intra_bar_config, symbol)

    def _management_timeframe(self) -> dict:
        timeframes = self.timeframes if self.timeframes else [{"key": None, "value": self.timeframe}]
        valid = [tf for tf in timeframes if tf.get("value") is not None]
        if not valid:
            return {"key": None, "value": self.timeframe}
        return min(valid, key=lambda tf: tf.get("value", 10**9))

    def _normalize_bar_time(self, bar_time):
        if bar_time is None:
            return None
        try:
            return pd.Timestamp(bar_time)
        except Exception:
            return bar_time

    def _get_or_reset_bar_state(self, symbol: str, bar_time):
        normalized_bar_time = self._normalize_bar_time(bar_time)
        state = self._bar_trade_state.get(symbol)
        if state is None or state.get("bar_time") != normalized_bar_time:
            state = {
                "bar_time": normalized_bar_time,
                "count": 0,
                "last_trade_time": None,
                "last_direction": None,
                "last_entry_price": None,
                "last_exit_reason": None,
            }
            self._bar_trade_state[symbol] = state
        return state

    @staticmethod
    def _is_opposite_side(first: str, second: str) -> bool:
        first_upper = str(first or "").upper()
        second_upper = str(second or "").upper()
        return {first_upper, second_upper} == {"BUY", "SELL"}

    def _compute_sl_tp_quality_score(self, entry_price: float, sl: float, tp: float) -> float:
        if entry_price is None or sl is None or tp is None:
            return 0.0
        risk = abs(float(entry_price) - float(sl))
        reward = abs(float(tp) - float(entry_price))
        if risk <= 0 or reward <= 0:
            return 0.0
        rr = reward / risk
        return max(0.0, min(1.0, rr / 2.0))

    def _current_price_for_side(self, symbol: str, side: str):
        price = None
        spread = None
        if hasattr(self.exchange, "get_tick"):
            try:
                tick = self.exchange.get_tick(symbol)
            except Exception:
                tick = None
            if tick is not None:
                bid = self._safe_float(getattr(tick, "bid", None), 0.0)
                ask = self._safe_float(getattr(tick, "ask", None), 0.0)
                spread = abs(ask - bid) if bid and ask else None
                if str(side or "").upper() == "BUY":
                    price = bid or ask
                elif str(side or "").upper() == "SELL":
                    price = ask or bid
                else:
                    price = bid or ask
        if not price and hasattr(self.exchange, "get_current_price"):
            try:
                price = self._safe_float(self.exchange.get_current_price(symbol), 0.0)
            except Exception:
                price = None
        if not price:
            tf = self._management_timeframe()
            try:
                df = self.exchange.get_rates(symbol, tf.get("value"), count=2)
            except Exception:
                df = None
            if df is not None and not df.empty:
                price = self._safe_float(df["close"].iloc[-1], 0.0)
        return price, spread

    def _compute_position_pnl(self, side: str, entry_price: float, current_price: float, volume: float, fallback=None) -> float:
        if fallback is not None:
            fallback_value = self._safe_float(fallback, 0.0)
            if abs(fallback_value) > 0:
                return fallback_value
        if entry_price is None or current_price is None:
            return 0.0
        if str(side or "").upper() == "BUY":
            return (float(current_price) - float(entry_price)) * float(volume)
        return (float(entry_price) - float(current_price)) * float(volume)

    def _favorable_price_distance(self, side: str, entry_price: float, current_price: float) -> float:
        if entry_price is None or current_price is None:
            return 0.0
        if str(side or "").upper() == "BUY":
            return float(current_price) - float(entry_price)
        return float(entry_price) - float(current_price)

    def _is_more_protective_stop(self, side: str, candidate_sl: float, current_sl: float) -> bool:
        if candidate_sl is None:
            return False
        if current_sl in (None, 0):
            return True
        if str(side or "").upper() == "BUY":
            return float(candidate_sl) > float(current_sl) + 1e-9
        return float(candidate_sl) < float(current_sl) - 1e-9

    def _build_indicator_snapshot(self, df: pd.DataFrame) -> dict:
        if df is None or df.empty or len(df) < 3:
            return {}
        close = df["close"].astype(float)
        high_low_df = df[["high", "low", "close"]].astype(float)
        volume_series = df["volume"].astype(float) if "volume" in df.columns else pd.Series([1.0] * len(df), index=df.index)

        rsi_period = getattr(self.strategy, "rsi_period", 14)
        atr_period = getattr(self.strategy, "atr_period", 14)
        if hasattr(self.strategy, "calculate_rsi"):
            rsi_series = self.strategy.calculate_rsi(close, rsi_period)
        else:
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0).rolling(window=rsi_period).mean()
            loss = (-delta.where(delta < 0, 0.0)).rolling(window=rsi_period).mean()
            rs = gain / loss.replace(0, pd.NA)
            rsi_series = (100 - (100 / (1 + rs))).fillna(50.0)
        if hasattr(self.strategy, "calculate_atr"):
            atr_series = self.strategy.calculate_atr(high_low_df, atr_period)
        else:
            atr_series = (high_low_df["high"] - high_low_df["low"]).rolling(window=atr_period).mean()
        if hasattr(self.strategy, "calculate_macd_histogram"):
            macd_hist_series = self.strategy.calculate_macd_histogram(close)
        else:
            ema_fast = close.ewm(span=12, adjust=False).mean()
            ema_slow = close.ewm(span=26, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            macd_signal = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist_series = macd_line - macd_signal

        current_close = self._safe_float(close.iloc[-1], 0.0)
        previous_close = self._safe_float(close.iloc[-2], current_close)
        current_rsi = self._safe_float(rsi_series.iloc[-1], 50.0)
        previous_rsi = self._safe_float(rsi_series.iloc[-2], current_rsi)
        current_macd_hist = self._safe_float(macd_hist_series.iloc[-1], 0.0)
        previous_macd_hist = self._safe_float(macd_hist_series.iloc[-2], current_macd_hist)
        atr = self._safe_float(atr_series.iloc[-1], max(current_close * 0.001, 1e-6))
        volume_now = self._safe_float(volume_series.iloc[-1], 0.0)
        volume_avg_5 = self._safe_float(volume_series.tail(5).mean(), volume_now)

        return {
            "atr": max(atr, max(current_close * 0.001, 1e-6)),
            "current_close": current_close,
            "previous_close": previous_close,
            "current_rsi": current_rsi,
            "previous_rsi": previous_rsi,
            "current_macd_hist": current_macd_hist,
            "previous_macd_hist": previous_macd_hist,
            "volume_now": volume_now,
            "volume_avg_5": volume_avg_5,
            "last_bar_open": self._safe_float(df["open"].iloc[-1], current_close),
            "last_bar_high": self._safe_float(df["high"].iloc[-1], current_close),
            "last_bar_low": self._safe_float(df["low"].iloc[-1], current_close),
            "previous_bar_high": self._safe_float(df["high"].iloc[-2], current_close),
            "previous_bar_low": self._safe_float(df["low"].iloc[-2], current_close),
        }

    def _momentum_reversal_signal(self, side: str, df: pd.DataFrame, symbol: str) -> dict:
        config = self._get_scalping_symbol_config(symbol)
        if not config.get("fast_exit_on_reversal", False):
            return {"triggered": False, "reasons": []}

        snapshot = self._build_indicator_snapshot(df)
        if not snapshot:
            return {"triggered": False, "reasons": []}

        reasons = []
        side_upper = str(side or "").upper()
        rsi_turn = abs(snapshot["current_rsi"] - snapshot["previous_rsi"])
        if side_upper == "BUY" and snapshot["previous_rsi"] - snapshot["current_rsi"] >= 3.0:
            reasons.append("rsi_rollover")
        if side_upper == "SELL" and snapshot["current_rsi"] - snapshot["previous_rsi"] >= 3.0:
            reasons.append("rsi_rollover")

        previous_macd_abs = max(abs(snapshot["previous_macd_hist"]), 1e-6)
        macd_force_drop = (previous_macd_abs - abs(snapshot["current_macd_hist"])) / previous_macd_abs
        if macd_force_drop >= 0.20:
            reasons.append("macd_force_loss")

        volume_avg = max(snapshot["volume_avg_5"], 1e-6)
        if snapshot["volume_now"] <= volume_avg * 0.70:
            reasons.append("volume_drop")

        current_bar_body = snapshot["current_close"] - snapshot["last_bar_open"]
        reversal_candles_required = max(1, int(config.get("reversal_candles_required", 1) or 1))
        opposite_candle = False
        if side_upper == "BUY":
            opposite_candle = current_bar_body < 0
            failed_breakout = snapshot["current_close"] < snapshot["previous_bar_high"] and snapshot["last_bar_high"] > snapshot["previous_bar_high"]
        else:
            opposite_candle = current_bar_body > 0
            failed_breakout = snapshot["current_close"] > snapshot["previous_bar_low"] and snapshot["last_bar_low"] < snapshot["previous_bar_low"]
        if opposite_candle and reversal_candles_required <= 1:
            reasons.append("opposite_candle")
        if failed_breakout:
            reasons.append("failed_breakout")

        return {
            "triggered": bool(reasons),
            "reasons": reasons,
            "rsi_turn": rsi_turn,
            "macd_force_drop": macd_force_drop,
            "volume_ratio": snapshot["volume_now"] / volume_avg,
        }

    def _default_trade_state(self, ticket: str, position_info: dict) -> dict:
        entry_price = self._safe_float(position_info.get("entry_price"), 0.0)
        sl = self._safe_float(position_info.get("sl"), 0.0)
        tp = self._safe_float(position_info.get("tp"), 0.0)
        state = TradeState(
            trade_id=str(ticket),
            symbol=str(position_info.get("symbol", "")),
            side=str(position_info.get("side", "")),
            volume=self._safe_float(position_info.get("volume"), 0.0),
            open_time=position_info.get("open_time"),
            position_ticket=str(ticket),
            entry_price=entry_price,
            initial_sl=sl,
            initial_tp=tp,
            current_sl=sl,
            current_tp=tp,
            initial_risk_distance=abs(entry_price - sl) if entry_price and sl else 0.0,
            initial_tp_distance=abs(tp - entry_price) if entry_price and tp else 0.0,
        )
        return asdict(state)

    def _ensure_trade_state(self, ticket: str, position_info: dict) -> dict:
        trade = self._open_trades.get(ticket)
        if trade is None:
            trade = self._default_trade_state(ticket, position_info)
            self._open_trades[ticket] = trade
        trade["position_ticket"] = str(ticket)
        trade["symbol"] = position_info.get("symbol", trade.get("symbol"))
        trade["side"] = position_info.get("side", trade.get("side"))
        trade["volume"] = self._safe_float(position_info.get("volume"), trade.get("volume", 0.0))
        if position_info.get("open_time") is not None:
            trade["open_time"] = position_info.get("open_time")
        if position_info.get("entry_price") not in (None, 0):
            trade["entry_price"] = self._safe_float(position_info.get("entry_price"), trade.get("entry_price", 0.0))
        if position_info.get("sl") not in (None, 0):
            trade["current_sl"] = self._safe_float(position_info.get("sl"), trade.get("current_sl", 0.0))
            if not trade.get("initial_sl"):
                trade["initial_sl"] = trade["current_sl"]
        if position_info.get("tp") not in (None, 0):
            trade["current_tp"] = self._safe_float(position_info.get("tp"), trade.get("current_tp", 0.0))
            if not trade.get("initial_tp"):
                trade["initial_tp"] = trade["current_tp"]
        if trade.get("entry_price") and trade.get("initial_tp") and not trade.get("initial_tp_distance"):
            trade["initial_tp_distance"] = abs(float(trade["initial_tp"]) - float(trade["entry_price"]))
        if trade.get("entry_price") and trade.get("initial_sl") and not trade.get("initial_risk_distance"):
            trade["initial_risk_distance"] = abs(float(trade["entry_price"]) - float(trade["initial_sl"]))
        return trade

    def _prepare_trade_state(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        volume: float,
        open_time: datetime,
        snapshot_id,
        timeframe_key,
        entry_price: float,
        sl: float,
        tp: float,
        decision: dict,
        trade_context: dict,
        bar_time,
        spread_points,
        reentry_count: int,
    ) -> dict:
        metrics = decision.get("metrics", {}) if isinstance(decision, dict) else {}
        context = trade_context or {}
        state = TradeState(
            trade_id=str(trade_id),
            symbol=str(symbol),
            side=str(side),
            volume=self._safe_float(volume),
            open_time=open_time,
            snapshot_id=snapshot_id,
            position_ticket=str(trade_id),
            timeframe_key=str(timeframe_key or "default"),
            entry_bar_time=self._normalize_bar_time(bar_time),
            entry_price=self._safe_float(entry_price),
            initial_sl=self._safe_float(sl),
            initial_tp=self._safe_float(tp),
            current_sl=self._safe_float(sl),
            current_tp=self._safe_float(tp),
            initial_risk_distance=abs(float(entry_price) - float(sl)) if entry_price and sl else 0.0,
            initial_tp_distance=abs(float(tp) - float(entry_price)) if entry_price and tp else 0.0,
            atr_at_entry=self._safe_float(context.get("atr", metrics.get("atr"))),
            rsi_at_entry=self._safe_float(context.get("rsi", metrics.get("rsi"))),
            volume_ratio_at_entry=self._safe_float(context.get("volume_ratio", metrics.get("volume_ratio")), 1.0),
            spread_at_entry=self._safe_float(spread_points),
            signal_confidence=self._safe_float(decision.get("confidence")),
            signal_force=self._safe_float(context.get("signal_force", metrics.get("signal_force", decision.get("confidence", 0.0)))),
            trend_alignment_score=self._safe_float(context.get("trend_alignment_score", metrics.get("trend_alignment_score"))),
            sl_tp_quality_score=self._safe_float(
                context.get("sl_tp_quality_score", self._compute_sl_tp_quality_score(entry_price, sl, tp))
            ),
            reentry_count_same_bar=int(reentry_count or 0),
        )
        return asdict(state)

    def _can_trade_on_bar(self, symbol: str, side: str, bar_time, now: datetime, entry_price: float, breakout_ok: bool = True):
        normalized_bar_time = self._normalize_bar_time(bar_time)
        if normalized_bar_time is None:
            return False, "missing_bar_time"

        if not self._is_intra_bar_enabled():
            if self._already_traded_on_bar(symbol, normalized_bar_time):
                return False, "already_traded_on_bar"
            return True, "bar_trade_allowed"

        config = self._get_intra_bar_symbol_config(symbol)
        state = self._get_or_reset_bar_state(symbol, normalized_bar_time)
        max_trades_per_bar = max(1, int(config.get("max_trades_per_bar", 1) or 1))
        min_seconds_between_trades = max(0.0, self._safe_float(config.get("min_seconds_between_trades"), 0.0))
        allow_same_direction = bool(config.get("allow_reentry_same_direction", False))
        allow_reentry_after_tp = bool(config.get("allow_reentry_after_tp", True))
        allow_reverse = bool(config.get("allow_reverse_trade_same_bar", False))
        require_move_pct = max(0.0, self._safe_float(config.get("require_price_move_pct_between_entries"), 0.0))
        require_breakout = bool(config.get("require_new_high_low_breakout", False))
        cooldown_after_loss = max(0.0, self._safe_float(config.get("cooldown_after_loss_seconds"), 0.0))

        if state.get("count", 0) >= max_trades_per_bar:
            return False, "max_trades_per_bar"

        last_trade_time = state.get("last_trade_time")
        if last_trade_time is not None and (now - last_trade_time).total_seconds() < min_seconds_between_trades:
            return False, "min_seconds_between_trades"

        if require_breakout and not breakout_ok:
            return False, "breakout_not_confirmed"

        last_closed_trade = self._last_closed_trade_by_symbol.get(symbol, {})
        last_close_time = last_closed_trade.get("close_time")
        if last_close_time is not None and self._safe_float(last_closed_trade.get("pnl"), 0.0) < 0:
            if (now - last_close_time).total_seconds() < cooldown_after_loss:
                return False, "cooldown_after_loss_seconds"

        last_direction = state.get("last_direction")
        if state.get("count", 0) > 0:
            last_exit_reason = str(state.get("last_exit_reason") or "")
            if not allow_reentry_after_tp and last_exit_reason in {"take_profit", "trailing_stop", "profit_lock", "break_even"}:
                return False, "reentry_after_tp_blocked"
            if self._is_opposite_side(last_direction, side) and not allow_reverse:
                return False, "reverse_same_bar_blocked"
            if str(last_direction or "").upper() == str(side or "").upper() and not allow_same_direction:
                return False, "same_direction_reentry_blocked"
            last_entry_price = self._safe_float(state.get("last_entry_price"), 0.0)
            if require_move_pct > 0 and last_entry_price > 0:
                move_pct = abs(float(entry_price) - last_entry_price) / last_entry_price * 100.0
                if move_pct < require_move_pct:
                    return False, "price_move_too_small"

        return True, "intra_bar_allowed"

    def _mark_trade_attempt(self, symbol: str, bar_time, side: str, now: datetime, entry_price: float, exit_reason: str = None) -> None:
        normalized_bar_time = self._normalize_bar_time(bar_time)
        self._last_trade_bar_time[symbol] = normalized_bar_time
        state = self._get_or_reset_bar_state(symbol, normalized_bar_time)
        state["count"] = int(state.get("count", 0) or 0) + 1
        state["last_trade_time"] = now
        state["last_direction"] = str(side or "").upper()
        state["last_entry_price"] = self._safe_float(entry_price, 0.0)
        if exit_reason:
            state["last_exit_reason"] = exit_reason

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
        normalized_bar_time = self._normalize_bar_time(bar_time)
        state = self._bar_trade_state.get(symbol)
        if state is not None and state.get("bar_time") == normalized_bar_time and int(state.get("count", 0) or 0) > 0:
            return True
        last_trade_time = self._last_trade_bar_time.get(symbol)
        return last_trade_time is not None and normalized_bar_time <= last_trade_time

    def _mark_traded_on_bar(self, symbol: str, bar_time: pd.Timestamp) -> None:
        self._mark_trade_attempt(symbol, bar_time, side="", now=datetime.now(), entry_price=0.0)

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
            self._ensure_trade_state(ticket, position_info)
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
        self._ensure_trade_state(ticket, position_info)

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
        def _normalize_open_time(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            if isinstance(value, pd.Timestamp):
                return value.to_pydatetime()
            try:
                return datetime.fromtimestamp(float(value))
            except Exception:
                return value

        if isinstance(pos, dict):
            return {
                "ticket": str(pos.get("ticket") or pos.get("id")),
                "symbol": pos.get("symbol"),
                "profit": float(pos.get("pnl", 0.0)),
                "volume": float(pos.get("volume", 0.0)),
                "side": pos.get("side"),
                "open_time": _normalize_open_time(pos.get("open_time")),
                "entry_price": self._safe_float(pos.get("entry_price"), 0.0),
                "current_price": self._safe_float(pos.get("price_current"), 0.0),
                "sl": self._safe_float(pos.get("sl"), 0.0),
                "tp": self._safe_float(pos.get("tp"), 0.0),
            }
        return {
            "ticket": str(getattr(pos, "ticket", "")),
            "symbol": getattr(pos, "symbol", None),
            "profit": float(getattr(pos, "profit", 0.0)),
            "volume": float(getattr(pos, "volume", 0.0)),
            "side": "BUY" if getattr(pos, "type", 0) == 0 else "SELL",
            "open_time": _normalize_open_time(getattr(pos, "time", None)),
            "entry_price": self._safe_float(getattr(pos, "price_open", None), 0.0),
            "current_price": self._safe_float(getattr(pos, "price_current", None), 0.0),
            "sl": self._safe_float(getattr(pos, "sl", None), 0.0),
            "tp": self._safe_float(getattr(pos, "tp", None), 0.0),
        }

    def _sync_positions(self, positions):
        current = {}
        for pos in positions or []:
            info = self._normalize_position(pos)
            if info["ticket"]:
                current[info["ticket"]] = info
                self._ensure_trade_state(info["ticket"], info)

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
            trade_meta = self._open_trades.get(ticket, {}) or {}
            exit_reason = (
                trade_meta.get("pending_exit_reason")
                or ("momentum_reversal" if trade_meta.get("momentum_reversal") else "")
                or ("trailing_stop" if trade_meta.get("used_trailing") and pnl > 0 else "")
                or ("profit_lock" if trade_meta.get("profit_locked") and pnl > 0 else "")
                or ("break_even" if trade_meta.get("touched_break_even") and pnl >= 0 else "")
                or ("take_profit" if pnl > 0 else "stop_loss")
            )
            duration_seconds = 0.0
            if trade_meta.get("open_time") is not None:
                try:
                    duration_seconds = max(0.0, (closed_at - trade_meta.get("open_time")).total_seconds())
                except Exception:
                    duration_seconds = 0.0

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
                open_time=trade_meta.get("open_time") or closed.get("open_time"),
                close_time=closed_at,
                pnl=pnl,
                spread=trade_meta.get("spread_at_entry", 0.0),
                atr=trade_meta.get("atr_at_entry", 0.0),
                rsi=trade_meta.get("rsi_at_entry", 0.0),
                volume_ratio=trade_meta.get("volume_ratio_at_entry", 1.0),
                signal_force=trade_meta.get("signal_force", 0.0),
                signal_confidence=trade_meta.get("signal_confidence", 0.0),
                trend_alignment_score=trade_meta.get("trend_alignment_score", 0.0),
                sl_tp_quality_score=trade_meta.get("sl_tp_quality_score", 0.0),
                entry_price=trade_meta.get("entry_price", closed.get("entry_price", 0.0)),
                exit_price=trade_meta.get("last_exit_price", closed.get("current_price", 0.0)),
                sl=trade_meta.get("initial_sl", closed.get("sl", 0.0)),
                tp=trade_meta.get("initial_tp", closed.get("tp", 0.0)),
                max_drawdown=trade_meta.get("max_drawdown", 0.0),
                max_profit_reached=trade_meta.get("max_profit_reached", 0.0),
                profit_final=pnl,
                duration_seconds=duration_seconds,
                exit_reason=exit_reason,
                touched_be=trade_meta.get("touched_break_even", False),
                profit_locked=trade_meta.get("profit_locked", False),
                used_trailing=trade_meta.get("used_trailing", False),
                momentum_reversal=trade_meta.get("momentum_reversal", False),
                bars_held=trade_meta.get("bars_held", 0),
                reentry_count_same_bar=trade_meta.get("reentry_count_same_bar", 0),
                timeframe_key=trade_meta.get("timeframe_key", "default"),
            )
            self._last_closed_trade_by_symbol[symbol] = {
                "close_time": closed_at,
                "pnl": pnl,
                "exit_reason": exit_reason,
            }
            if trade_meta.get("entry_bar_time") is not None:
                bar_state = self._get_or_reset_bar_state(symbol, trade_meta.get("entry_bar_time"))
                bar_state["last_exit_reason"] = exit_reason

            self.logger.logger.info(
                f"MICRO_SCALP_EXIT - Ticket: {ticket} | Symbol: {symbol} | Side: {closed.get('side')} | "
                f"PnL: {self._safe_float(pnl):.5f} | ExitReason: {exit_reason}"
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
                        "open_time": trade_meta.get("open_time") or closed.get("open_time"),
                        "close_time": closed_at,
                        "pnl": pnl,
                        "exit_reason": exit_reason,
                        "trade_score": trade_meta.get("trade_score"),
                    },
                )

            if ticket in self._open_trades:
                self._open_trades.pop(ticket, None)
                # Unregister the trade from auto-close scheduler
                self.auto_close_scheduler.unregister_trade(ticket)
            self._session_close_attempts.pop(ticket, None)

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

    @staticmethod
    def _format_session_window(session: dict) -> str:
        if not isinstance(session, dict):
            return "unknown"
        start_hour = int(session.get("start_hour", 0))
        start_minute = int(session.get("start_minute", 0))
        end_hour = int(session.get("end_hour", 0))
        end_minute = int(session.get("end_minute", 0))
        return f"{start_hour:02d}:{start_minute:02d}-{end_hour:02d}:{end_minute:02d}"

    def _close_positions_outside_session(self, positions, now: datetime) -> bool:
        if self.risk_manager is None or not hasattr(self.risk_manager, "is_within_trading_session"):
            return False
        if not hasattr(self.exchange, "close_position"):
            return False

        current_tickets = set()
        close_attempted = False
        now_ts = time.time()

        for pos in positions or []:
            info = self._normalize_position(pos)
            ticket = info.get("ticket")
            symbol = info.get("symbol")
            side = info.get("side")
            volume = float(info.get("volume", 0.0) or 0.0)

            if ticket:
                current_tickets.add(ticket)

            if not ticket or not symbol or not side or volume <= 0:
                continue

            session = {}
            if hasattr(self.risk_manager, "get_effective_trading_session"):
                try:
                    session = self.risk_manager.get_effective_trading_session(symbol)
                except Exception:
                    session = {}

            if not session or not bool(session.get("enabled", False)):
                self._session_close_attempts.pop(ticket, None)
                continue

            try:
                within_session = self.risk_manager.is_within_trading_session(now, symbol=symbol)
            except Exception as exc:
                self.logger.logger.warning(
                    f"SESSION_CHECK_FAILED - Ticket: {ticket} | Symbol: {symbol} | Error: {exc}"
                )
                continue

            if within_session:
                self._session_close_attempts.pop(ticket, None)
                continue

            last_attempt = self._session_close_attempts.get(ticket)
            if last_attempt is not None and (now_ts - last_attempt) < self._session_close_retry_seconds:
                continue

            session_window = self._format_session_window(session)
            self.logger.logger.warning(
                f"SESSION_ENDED - Ticket: {ticket} | Symbol: {symbol} | Session: {session_window} | "
                f"Closing open {side} position"
            )

            try:
                result = self.exchange.close_position(
                    ticket=ticket,
                    symbol=symbol,
                    volume=volume,
                    side=side,
                    comment="TradePy Session End",
                )
            except Exception as exc:
                self.logger.logger.error(
                    f"SESSION_CLOSE_ERROR - Ticket: {ticket} | Symbol: {symbol} | Error: {exc}"
                )
                continue

            close_attempted = True
            success = bool(getattr(result, "success", result))
            if success:
                self._session_close_attempts[ticket] = now_ts
                details = getattr(result, "details", {}) or {}
                if ticket in self._open_positions_snapshot and details.get("profit") is not None:
                    try:
                        self._open_positions_snapshot[ticket]["profit"] = float(details.get("profit"))
                    except Exception:
                        pass
                self.logger.logger.info(
                    f"SESSION_CLOSE_SENT - Ticket: {ticket} | Symbol: {symbol} | "
                    f"Result: {getattr(result, 'message', 'ok')}"
                )
            else:
                self._session_close_attempts.pop(ticket, None)
                self.logger.logger.error(
                    f"SESSION_CLOSE_FAILED - Ticket: {ticket} | Symbol: {symbol} | "
                    f"Reason: {getattr(result, 'message', '') or getattr(result, 'comment', 'unknown_error')}"
                )

        stale_tickets = [ticket for ticket in self._session_close_attempts if ticket not in current_tickets]
        for ticket in stale_tickets:
            self._session_close_attempts.pop(ticket, None)

        return close_attempted

    def _build_intrabar_candidate(self, symbol: str, tf_data, now: datetime):
        if not self._is_intra_bar_enabled() or self._startup_grace_period_active:
            return None
        if not tf_data:
            return None

        candidate = min(tf_data, key=lambda item: item.get("tf_value", 10**9))
        df = candidate.get("df")
        if df is None or df.empty or len(df) < 3:
            return None

        try:
            if hasattr(self.strategy, "generate_decision"):
                decision = self.strategy.generate_decision(df, symbol=symbol)
            else:
                signal = self.strategy.generate_signal(df)
                decision = {"signal": signal, "confidence": 0.0, "source": "generate_signal", "reason": "intrabar"}
        except Exception as exc:
            self.logger.logger.warning(f"INTRABAR_DECISION_FAILED - Symbol: {symbol} | Error: {exc}")
            return None

        signal = decision.get("signal", "HOLD")
        if signal not in ("BUY", "SELL"):
            return None

        entry_price, _ = self._current_price_for_side(symbol, signal)
        if not entry_price:
            entry_price = self._safe_float(df["close"].iloc[-1], 0.0)

        current_bar_time = df.index[-1]
        current_bar = df.iloc[-1]
        previous_bar = df.iloc[-2]
        if signal == "BUY":
            breakout_ok = self._safe_float(current_bar.get("high"), 0.0) > self._safe_float(previous_bar.get("high"), 0.0)
        else:
            breakout_ok = self._safe_float(current_bar.get("low"), 0.0) < self._safe_float(previous_bar.get("low"), 0.0)

        allowed, reason = self._can_trade_on_bar(
            symbol=symbol,
            side=signal,
            bar_time=current_bar_time,
            now=now,
            entry_price=entry_price,
            breakout_ok=breakout_ok,
        )
        if not allowed:
            return None

        return {
            "tf_key": candidate.get("tf_key"),
            "tf_value": candidate.get("tf_value"),
            "df": df,
            "analysis_df": df,
            "is_new": False,
            "is_intrabar": True,
            "closed_bar_time": current_bar_time,
            "current_bar_time": current_bar_time,
            "decision": decision,
            "signal": signal,
            "confidence": self._safe_float(decision.get("confidence"), 0.0),
            "decision_source": decision.get("source", "intrabar"),
            "decision_reason": reason,
        }

    def _update_trade_extremes(self, trade: dict, position_info: dict, df: pd.DataFrame, current_price: float) -> None:
        trade["bars_held"] = int(trade.get("bars_held", 0) or 0)
        open_time = trade.get("open_time")
        if open_time is not None and df is not None and not df.empty:
            try:
                trade["bars_held"] = int((df.index >= pd.Timestamp(open_time)).sum())
            except Exception:
                pass

        current_pnl = self._compute_position_pnl(
            side=trade.get("side"),
            entry_price=trade.get("entry_price"),
            current_price=current_price,
            volume=trade.get("volume", 0.0),
            fallback=position_info.get("profit"),
        )
        trade["max_profit_reached"] = max(self._safe_float(trade.get("max_profit_reached"), 0.0), current_pnl)
        if current_pnl < 0:
            trade["max_drawdown"] = max(self._safe_float(trade.get("max_drawdown"), 0.0), abs(current_pnl))

    def _apply_scalping_management(self, positions, now: datetime) -> bool:
        if not self._is_scalping_enabled():
            return False
        action_taken = False
        rates_cache = {}

        for pos in positions or []:
            info = self._normalize_position(pos)
            ticket = info.get("ticket")
            symbol = info.get("symbol")
            side = str(info.get("side", "")).upper()
            volume = self._safe_float(info.get("volume"), 0.0)
            if not ticket or not symbol or side not in ("BUY", "SELL") or volume <= 0:
                continue

            tf = self._management_timeframe()
            cache_key = (symbol, tf.get("value"))
            if cache_key not in rates_cache:
                rates_cache[cache_key] = self.exchange.get_rates(symbol, tf.get("value"), count=300)
            df = rates_cache.get(cache_key)
            if df is None or df.empty or len(df) < 3:
                continue

            trade = self._ensure_trade_state(ticket, info)
            current_price, _ = self._current_price_for_side(symbol, side)
            current_price = current_price or self._safe_float(info.get("current_price"), 0.0) or self._safe_float(df["close"].iloc[-1], 0.0)
            if current_price <= 0:
                continue

            self._update_trade_extremes(trade, info, df, current_price)

            config = self._get_scalping_symbol_config(symbol)
            entry_price = self._safe_float(trade.get("entry_price"), self._safe_float(info.get("entry_price"), 0.0))
            current_sl = self._safe_float(trade.get("current_sl"), self._safe_float(info.get("sl"), 0.0))
            current_tp = self._safe_float(trade.get("current_tp"), self._safe_float(info.get("tp"), 0.0))
            initial_tp_distance = self._safe_float(trade.get("initial_tp_distance"), 0.0)
            if initial_tp_distance <= 0 and entry_price and current_tp:
                initial_tp_distance = abs(current_tp - entry_price)
                trade["initial_tp_distance"] = initial_tp_distance
            if initial_tp_distance <= 0:
                continue

            favorable_distance = self._favorable_price_distance(side, entry_price, current_price)
            progress = favorable_distance / max(initial_tp_distance, 1e-6)
            indicator_snapshot = self._build_indicator_snapshot(df)
            atr = max(self._safe_float(indicator_snapshot.get("atr"), trade.get("atr_at_entry", 0.0)), max(current_price * 0.001, 1e-6))

            desired_sl = current_sl
            break_even_trigger = self._safe_float(config.get("break_even_trigger_pct"), 0.25)
            break_even_offset = self._safe_float(config.get("break_even_offset_usd"), 0.0)
            secure_profit_trigger = self._safe_float(config.get("secure_profit_trigger_pct"), 0.50)
            secure_profit_lock_pct = self._safe_float(config.get("secure_profit_lock_pct"), 0.40)

            if progress >= break_even_trigger and not trade.get("touched_break_even"):
                candidate_sl = entry_price + break_even_offset if side == "BUY" else entry_price - break_even_offset
                if self._is_more_protective_stop(side, candidate_sl, desired_sl):
                    desired_sl = candidate_sl
                trade["touched_break_even"] = True
                self.logger.logger.info(
                    f"TRADE_BREAK_EVEN_TRIGGERED - Ticket: {ticket} | Symbol: {symbol} | Side: {side} | "
                    f"Progress: {progress:.2f} | NewSL: {candidate_sl}"
                )

            if progress >= secure_profit_trigger and not trade.get("profit_locked"):
                profit_lock_distance = initial_tp_distance * secure_profit_lock_pct
                candidate_sl = entry_price + profit_lock_distance if side == "BUY" else entry_price - profit_lock_distance
                if self._is_more_protective_stop(side, candidate_sl, desired_sl):
                    desired_sl = candidate_sl
                trade["profit_locked"] = True
                self.logger.logger.info(
                    f"TRADE_PROFIT_LOCKED - Ticket: {ticket} | Symbol: {symbol} | Side: {side} | "
                    f"Progress: {progress:.2f} | LockedPct: {secure_profit_lock_pct:.2f} | NewSL: {candidate_sl}"
                )

            if config.get("trailing_stop_enabled", False) and progress > 0:
                trailing_distance = atr * self._safe_float(config.get("trailing_stop_distance_atr_multiplier"), 0.45)
                trailing_sl = current_price - trailing_distance if side == "BUY" else current_price + trailing_distance
                if self._is_more_protective_stop(side, trailing_sl, desired_sl):
                    desired_sl = trailing_sl
                    trade["used_trailing"] = True
                    self.logger.logger.info(
                        f"TRADE_TRAILING_STOP_UPDATED - Ticket: {ticket} | Symbol: {symbol} | Side: {side} | "
                        f"ATR: {atr:.5f} | NewSL: {trailing_sl:.5f}"
                    )

            if desired_sl and self._is_more_protective_stop(side, desired_sl, current_sl):
                try:
                    result = self.exchange.update_position_protection(
                        ticket=ticket,
                        symbol=symbol,
                        sl=desired_sl,
                        tp=current_tp or trade.get("initial_tp", 0.0),
                        comment="TradePy Micro-Scalp Protection",
                    )
                    if bool(getattr(result, "success", result)):
                        trade["current_sl"] = desired_sl
                        trade["last_protection_update"] = now
                        action_taken = True
                except Exception as exc:
                    self.logger.logger.warning(
                        f"PROTECTION_UPDATE_FAILED - Ticket: {ticket} | Symbol: {symbol} | Error: {exc}"
                    )

            reversal = self._momentum_reversal_signal(side, df, symbol)
            if reversal.get("triggered"):
                trade["momentum_reversal"] = True
                trade["pending_exit_reason"] = "momentum_reversal"
                trade["last_exit_price"] = current_price
                self.logger.logger.info(
                    f"TRADE_EXITED_ON_MOMENTUM_REVERSAL - Ticket: {ticket} | Symbol: {symbol} | "
                    f"Reasons: {','.join(reversal.get('reasons', []))}"
                )
                try:
                    result = self.exchange.close_position(
                        ticket=ticket,
                        symbol=symbol,
                        volume=volume,
                        side=side,
                        comment="TradePy Momentum Reversal",
                    )
                    if bool(getattr(result, "success", result)):
                        action_taken = True
                except Exception as exc:
                    self.logger.logger.error(
                        f"MICRO_SCALP_EXIT_FAILED - Ticket: {ticket} | Symbol: {symbol} | Error: {exc}"
                    )

        return action_taken

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
                loop_now = datetime.now()
                if self.risk_manager is not None:
                    self.risk_manager.update_daily(daily_pnl, daily_pnl_pct, loop_now)

                # Check open positions globally (for reporting only)
                all_positions = self.exchange.positions()
                self._sync_positions(all_positions)
                if self._close_positions_outside_session(all_positions, now=loop_now):
                    all_positions = self.exchange.positions()
                    self._sync_positions(all_positions)
                
                # Check and close expired trades (auto-close after 90 minutes)
                expired_results = self.auto_close_scheduler.check_and_close_expired_trades()
                if expired_results:
                    # Refresh positions after auto-closing trades
                    all_positions = self.exchange.positions()
                    self._sync_positions(all_positions)
                if self._apply_scalping_management(all_positions, now=loop_now):
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
                    intrabar_candidate = None
                    has_new_bar = bool(new_bar_candidates)
                    if not has_new_bar:
                        intrabar_candidate = self._build_intrabar_candidate(symbol, tf_data, now=loop_now)
                    evaluation_candidates = list(new_bar_candidates)
                    if intrabar_candidate is not None:
                        evaluation_candidates.append(intrabar_candidate)
                    has_signal_evaluation = bool(evaluation_candidates)
                    trace_pool = evaluation_candidates if has_signal_evaluation else tf_data
                    trace_candidate = self._select_preferred_candidate(trace_pool)
                    df = trace_candidate["df"]
                    is_new_closed_bar = trace_candidate["is_new"] if trace_candidate is not None else False
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
                    if has_signal_evaluation:
                        state = "evaluating"
                        order_result = "evaluating_new_bar" if has_new_bar else "evaluating_intrabar"
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
                    if has_signal_evaluation:
                        # Disable startup grace period after first closed bar seen
                        if has_new_bar and self._startup_grace_period_active:
                            self._startup_grace_period_active = False
                            self.logger.info("Startup grace period ended. Ready to trade.")

                        # Generate signal only after startup grace period
                        if not self._startup_grace_period_active:
                            self._current_symbol = symbol
                            hold_reason_msg = ""
                            selected_reason = "signal_selected"
                            
                            # Generate signal per timeframe (closed bars first, plus optional intrabar candidate)
                            for candidate in evaluation_candidates:
                                if candidate.get("decision") is not None:
                                    continue
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

                            chosen_candidate, selected_reason = self._resolve_timeframe_signal(evaluation_candidates)
                            if chosen_candidate is not None and chosen_candidate.get("is_intrabar"):
                                selected_reason = chosen_candidate.get("decision_reason", "intra_bar_signal")
                            if chosen_candidate is None:
                                # No actionable signal or conflict
                                hold_candidate = self._select_preferred_candidate(evaluation_candidates)
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
                            trade_bar_time = chosen_candidate.get("current_bar_time") or (df.index[-1] if df is not None and not df.empty else closed_bar_time)
                            confidence = chosen_candidate.get("confidence")
                            decision_source = chosen_candidate.get("decision_source")
                            chosen_decision = chosen_candidate.get("decision", {})
                            snapshot_id = self.snapshot_store.next_snapshot_id(symbol, datetime.now()) if self.snapshot_store is not None else None
                            entry_price = None
                            spread_points = None
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
                                    market_entry_price, _ = self._current_price_for_side(symbol, signal)
                                    entry_price = market_entry_price or float(analysis_df["close"].iloc[-1])
                                    if hasattr(self.exchange, "estimate_spread_points"):
                                        try:
                                            spread_points = self.exchange.estimate_spread_points(symbol)
                                        except Exception:
                                            spread_points = None
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
                                    breakout_ok = True
                                    if chosen_candidate.get("is_intrabar"):
                                        breakout_ok = chosen_candidate.get("decision_reason") != "breakout_not_confirmed"
                                    bar_allowed, bar_reason = self._can_trade_on_bar(
                                        symbol=symbol,
                                        side=signal,
                                        bar_time=trade_bar_time,
                                        now=datetime.now(),
                                        entry_price=entry_price,
                                        breakout_ok=breakout_ok,
                                    )
                                    if not bar_allowed:
                                        state = "risk_blocked"
                                        order_result = bar_reason
                                        self.logger.logger.info(
                                            f"NO_TRADE - Symbol: {symbol} | TF: {timeframe_key or 'default'} | Reason: {bar_reason}"
                                        )
                                    else:
                                        # All conditions met, try to place order
                                        try:
                                            order_now = datetime.now()
                                            comment = "TradePy Ultra Scalp" if self._is_scalping_enabled() else "TradePy Live"
                                            ok = self.exchange.place_market_order(
                                                symbol=symbol,
                                                side=signal,
                                                volume=volume,
                                                sl=sl,
                                                tp=tp,
                                                comment=comment
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
                                                bar_state = self._get_or_reset_bar_state(symbol, trade_bar_time)
                                                reentry_count = int(bar_state.get("count", 0) or 0)
                                                trade_context = {}
                                                if hasattr(self.strategy, "build_trade_context"):
                                                    try:
                                                        trade_context = self.strategy.build_trade_context(
                                                            analysis_df,
                                                            signal,
                                                            symbol=symbol,
                                                            sl=sl,
                                                            tp=tp,
                                                        )
                                                    except Exception:
                                                        trade_context = {}
                                                self._open_trades[trade_id] = self._prepare_trade_state(
                                                    trade_id=trade_id,
                                                    symbol=symbol,
                                                    side=signal,
                                                    volume=volume,
                                                    open_time=order_now,
                                                    snapshot_id=snapshot_id,
                                                    timeframe_key=timeframe_key,
                                                    entry_price=entry_price,
                                                    sl=sl,
                                                    tp=tp,
                                                    decision=chosen_decision,
                                                    trade_context=trade_context,
                                                    bar_time=trade_bar_time,
                                                    spread_points=spread_points,
                                                    reentry_count=reentry_count,
                                                )
                                                self._mark_trade_attempt(symbol, trade_bar_time, signal, order_now, entry_price)
                                                if reentry_count > 0:
                                                    self.logger.logger.info(
                                                        f"TRADE_REENTRY_SAME_BAR - Symbol: {symbol} | Side: {signal} | "
                                                        f"BarTime: {trade_bar_time} | ReentryCount: {reentry_count + 1}"
                                                    )
                                                if self._is_scalping_enabled():
                                                    signal_force = self._safe_float(self._open_trades[trade_id].get("signal_force"), 0.0)
                                                    self.logger.logger.info(
                                                        f"ULTRA_SCALP_ENTRY - Symbol: {symbol} | TF: {timeframe_key or 'default'} | "
                                                        f"Side: {signal} | Entry: {entry_price} | SignalForce: {signal_force:.4f}"
                                                    )
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
                                                            "signal_force": self._open_trades[trade_id].get("signal_force", 0.0),
                                                            "reentry_count_same_bar": self._open_trades[trade_id].get("reentry_count_same_bar", 0),
                                                        },
                                                    )
                                                if self.risk_manager is not None:
                                                    self.risk_manager.record_trade_open(order_now, symbol)
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

"""
Risk management for TradePy bot
"""
from typing import List, Optional, Set, Dict, Any
from collections import deque
from datetime import datetime, date, timedelta, time as dt_time
import json
import os
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - fallback for older Python
    ZoneInfo = None
from .rules import RiskRule


class RiskManager:
    """Manage trading risks and validations"""
    
    def __init__(self, config: Optional[dict] = None):
        config = config or {}
        self.rules: List[RiskRule] = []
        self.max_daily_loss_pct = float(config.get("max_daily_loss_pct", 0.03))
        self.max_daily_loss_usd = float(config.get("max_daily_loss_usd", 0.0))
        self.max_consecutive_losses = int(config.get("max_consecutive_losses", 3))
        self.max_trades_per_day = int(config.get("max_trades_per_day", 10))
        self.max_trades_per_day_by_symbol = config.get("max_trades_per_day_by_symbol", {})
        self.max_open_trades_per_symbol = int(config.get("max_open_trades_per_symbol", 1))
        self.max_open_trades_per_symbol_by_symbol = config.get("max_open_trades_per_symbol_by_symbol", {})
        self.max_global_open_positions = config.get("max_global_open_positions", None)
        self.cooldown_minutes_after_loss = int(config.get("cooldown_minutes_after_loss", 45))
        self.cooldown_after_trade_overrides_by_symbol = config.get("cooldown_after_trade_overrides_by_symbol", {})
        
        # New global cooldown option and overrides
        self.global_cooldown_minutes_after_loss = int(config.get("global_cooldown_minutes_after_loss", 0))
        self.cooldown_overrides_by_symbol = config.get("cooldown_overrides_by_symbol", {})
        
        # Handle both legacy and new config formats for spread/slippage
        # Legacy: max_spread_points_default, max_slippage_points_default
        # New: max_spread_points, max_slippage_points with max_spread_points_by_symbol, max_slippage_points_by_symbol
        self.max_spread_points_default = config.get("max_spread_points_default", config.get("max_spread_points", None))
        self.max_slippage_points_default = config.get("max_slippage_points_default", config.get("max_slippage_points", None))
        
        # Handle both the legacy format and the new nested format for per-symbol configs
        # Support legacy "max_spread_points_by_symbol": {"BTCUSDm": 80, ...} format directly
        if "max_spread_points_by_symbol" in config:
            max_spread_points_by_symbol = config["max_spread_points_by_symbol"]
            if isinstance(max_spread_points_by_symbol, dict):
                self.max_spread_points_by_symbol = max_spread_points_by_symbol
            else:
                self.max_spread_points_by_symbol = {}
        else:
            self.max_spread_points_by_symbol = {}
        
        if "max_slippage_points_by_symbol" in config:
            max_slippage_points_by_symbol = config["max_slippage_points_by_symbol"]
            if isinstance(max_slippage_points_by_symbol, dict):
                self.max_slippage_points_by_symbol = max_slippage_points_by_symbol
            else:
                self.max_slippage_points_by_symbol = {}
        else:
            self.max_slippage_points_by_symbol = {}
        
        # Store the full position sizing config for use in volume calculations
        self.position_sizing_config = config.get("position_sizing", {})
        self.symbol_daily_loss_limit_usd_by_symbol = config.get("symbol_daily_loss_limit_usd_by_symbol", {})
        self.symbol_safe_mode_by_symbol = config.get("symbol_safe_mode_by_symbol", {})
        if not isinstance(self.symbol_daily_loss_limit_usd_by_symbol, dict):
            self.symbol_daily_loss_limit_usd_by_symbol = {}
        if not isinstance(self.symbol_safe_mode_by_symbol, dict):
            self.symbol_safe_mode_by_symbol = {}
        
        self.one_trade_per_symbol_per_day = bool(config.get("one_trade_per_symbol_per_day", False))
        self.cooldown_minutes_after_trade_per_symbol = int(config.get("cooldown_minutes_after_trade_per_symbol", 0))
        self.daily_profit_target_usd = float(config.get("daily_profit_target_usd", 0.0))
        self.profit_lock_mode = str(config.get("profit_lock_mode", "until_next_day"))
        self.profit_lock_hours = int(config.get("profit_lock_hours", 6))
        self.trading_timezone = str(config.get("trading_timezone", "UTC"))
        self.daily_reset_hour = int(config.get("daily_reset_hour", 0))
        self.trading_session = config.get("trading_session", {})
        if not isinstance(self.trading_session, dict):
            self.trading_session = {}
        self.trading_session_by_symbol = config.get("trading_session_by_symbol", {})
        if not isinstance(self.trading_session_by_symbol, dict):
            self.trading_session_by_symbol = {}
        self.state_path = config.get("state_path")

        self._current_day: Optional[date] = None
        self._daily_pnl = 0.0
        self._daily_pnl_pct = 0.0
        self._trades_today = 0
        self._consecutive_losses = 0
        self._last_loss_time: Optional[datetime] = None  # Kept for global cooldown
        self._last_loss_time_by_symbol: Dict[str, datetime] = {}  # Per-symbol cooldown
        self._traded_symbols_today: Set[str] = set()
        self._trades_today_by_symbol: Dict[str, int] = {}
        self._daily_realized_pnl = 0.0
        self._daily_realized_pnl_by_symbol: Dict[str, float] = {}
        self._profit_lock_active = False
        self._profit_lock_until: Optional[datetime] = None
        self._last_trade_time_by_symbol: Dict[str, datetime] = {}
        self._spread_samples_by_symbol: Dict[str, deque] = {}
        self._slippage_samples_by_symbol: Dict[str, deque] = {}
        self._last_risk_sample_log_by_symbol: Dict[str, datetime] = {}

        self._load_state()
        
    def add_rule(self, rule: RiskRule):
        """Add a risk rule"""
        self.rules.append(rule)
        
    def validate_trade(self, *args, **kwargs) -> bool:
        """Validate a trade against all rules"""
        for rule in self.rules:
            if rule.enabled and not rule.validate(*args, **kwargs):
                return False
        return True
    
    def _get_tz(self):
        if ZoneInfo is None:
            return None
        try:
            return ZoneInfo(self.trading_timezone)
        except Exception:
            return None

    def _get_trading_day(self, now: datetime) -> date:
        if now is None:
            from datetime import datetime
            now = datetime.now()
            
        tz = self._get_tz()
        if tz is not None and now.tzinfo is None:
            now = now.replace(tzinfo=tz)
        if tz is not None and now.tzinfo is not None:
            now = now.astimezone(tz)
        reset_time = dt_time(self.daily_reset_hour, 0, 0)
        if now.time() < reset_time:
            return (now.date() - timedelta(days=1))
        return now.date()

    def _normalize_now_to_trading_timezone(self, now: Optional[datetime]) -> datetime:
        if now is None:
            now = datetime.now()
        tz = self._get_tz()
        if tz is not None and now.tzinfo is None:
            return now.replace(tzinfo=tz)
        if tz is not None and now.tzinfo is not None:
            return now.astimezone(tz)
        return now

    def _get_effective_trading_session(self, symbol: Optional[str]) -> Dict[str, Any]:
        session = dict(self.trading_session) if isinstance(self.trading_session, dict) else {}
        if symbol and isinstance(self.trading_session_by_symbol, dict):
            symbol_session = self.trading_session_by_symbol.get(symbol)
            if isinstance(symbol_session, dict):
                session.update(symbol_session)
        return session

    def _is_within_trading_session(self, now: Optional[datetime], symbol: Optional[str] = None) -> bool:
        session = self._get_effective_trading_session(symbol)
        if not session or not bool(session.get("enabled", False)):
            return True

        local_now = self._normalize_now_to_trading_timezone(now)
        start_hour = int(session.get("start_hour", 0))
        start_minute = int(session.get("start_minute", 0))
        end_hour = int(session.get("end_hour", 0))
        end_minute = int(session.get("end_minute", 0))

        start_time = dt_time(start_hour, start_minute)
        end_time = dt_time(end_hour, end_minute)
        current_time = local_now.time()

        if start_time == end_time:
            return True
        if start_time < end_time:
            return start_time <= current_time < end_time
        return current_time >= start_time or current_time < end_time

    def _get_active_symbol_safe_mode(self, symbol: Optional[str], now: Optional[datetime]) -> Optional[Dict[str, Any]]:
        if not symbol or not isinstance(self.symbol_safe_mode_by_symbol, dict):
            return None
        safe_mode = self.symbol_safe_mode_by_symbol.get(symbol)
        if not isinstance(safe_mode, dict):
            return None

        enabled_until = safe_mode.get("enabled_until")
        if not enabled_until:
            return safe_mode

        enabled_until_str = str(enabled_until).strip()
        if not enabled_until_str:
            return safe_mode

        # Accept either YYYY-MM-DD or full ISO datetime; date granularity is enough here.
        try:
            cutoff_day = date.fromisoformat(enabled_until_str[:10])
        except Exception:
            return None

        trading_day_now = self._get_trading_day(now or datetime.now())
        if trading_day_now <= cutoff_day:
            return safe_mode
        return None

    def _get_effective_symbol_daily_loss_limit_usd(self, symbol: Optional[str], safe_mode: Optional[Dict[str, Any]]) -> Optional[float]:
        if not symbol:
            return None

        base_limit = None
        raw_base_limit = self.symbol_daily_loss_limit_usd_by_symbol.get(symbol)
        if raw_base_limit is not None:
            try:
                base_limit = abs(float(raw_base_limit))
            except Exception:
                base_limit = None

        safe_mode_limit = None
        if safe_mode is not None and safe_mode.get("daily_loss_limit_usd") is not None:
            try:
                safe_mode_limit = abs(float(safe_mode.get("daily_loss_limit_usd")))
            except Exception:
                safe_mode_limit = None

        if base_limit is None:
            return safe_mode_limit
        if safe_mode_limit is None:
            return base_limit
        return min(base_limit, safe_mode_limit)

    def get_effective_volume_multiplier(self, symbol: Optional[str], now: Optional[datetime] = None) -> float:
        multiplier = 1.0
        if symbol and isinstance(self.position_sizing_config, dict):
            per_symbol = self.position_sizing_config.get("per_symbol", {})
            if isinstance(per_symbol, dict):
                symbol_cfg = per_symbol.get(symbol, {})
                if isinstance(symbol_cfg, dict):
                    try:
                        multiplier = float(symbol_cfg.get("multiplier", 1.0))
                    except Exception:
                        multiplier = 1.0

        safe_mode = self._get_active_symbol_safe_mode(symbol, now or datetime.now())
        if safe_mode is not None and safe_mode.get("volume_multiplier") is not None:
            try:
                multiplier *= float(safe_mode.get("volume_multiplier"))
            except Exception:
                pass

        if multiplier <= 0:
            return 1.0
        return multiplier

    def _get_position_sizing_settings(self, symbol: Optional[str]) -> Dict[str, Any]:
        settings: Dict[str, Any] = {}
        if not isinstance(self.position_sizing_config, dict):
            return settings

        defaults = self.position_sizing_config.get("defaults", {})
        if isinstance(defaults, dict):
            settings.update(defaults)

        if self.position_sizing_config.get("max_lot") is not None:
            settings["max_lot"] = self.position_sizing_config.get("max_lot")

        if symbol:
            per_symbol = self.position_sizing_config.get("per_symbol", {})
            if isinstance(per_symbol, dict):
                symbol_cfg = per_symbol.get(symbol, {})
                if isinstance(symbol_cfg, dict):
                    settings.update(symbol_cfg)
        return settings

    @staticmethod
    def _normalize_volume(volume: float, min_lot: float, max_lot: float, lot_step: float) -> float:
        if max_lot <= 0:
            max_lot = min_lot
        adjusted_volume = max(min_lot, min(volume, max_lot))

        if lot_step > 0:
            epsilon = lot_step * 1e-9
            steps = int((adjusted_volume + epsilon) / lot_step)
            adjusted_volume = steps * lot_step
            if adjusted_volume < min_lot:
                adjusted_volume = min_lot
            step_str = str(lot_step)
            decimals = len(step_str.split(".")[1]) if "." in step_str else 0
            adjusted_volume = round(adjusted_volume, decimals)
        else:
            adjusted_volume = round(adjusted_volume, 2)

        return max(min_lot, min(adjusted_volume, max_lot))

    @staticmethod
    def _estimate_loss_per_lot(entry_price: float, sl_price: float, constraints: Optional[Any]) -> Optional[float]:
        price_distance = abs(float(entry_price) - float(sl_price))
        if price_distance <= 0:
            return None

        if constraints is not None:
            tick_size = getattr(constraints, "tick_size", None) or getattr(constraints, "point", None)
            tick_value = getattr(constraints, "tick_value", None)
            contract_size = getattr(constraints, "contract_size", None)

            if tick_size and tick_value:
                return (price_distance / float(tick_size)) * abs(float(tick_value))
            if contract_size:
                return price_distance * abs(float(contract_size))

        return price_distance

    @staticmethod
    def _distance_pct(entry_price: float, target_price: Optional[float]) -> float:
        if entry_price is None or target_price is None:
            return 0.0
        entry_abs = abs(float(entry_price))
        if entry_abs <= 0:
            return 0.0
        return abs(float(target_price) - float(entry_price)) / entry_abs

    def _get_wide_setup_volume_factor(
        self,
        entry_price: float,
        sl_price: Optional[float],
        tp_price: Optional[float],
        settings: Dict[str, Any],
    ) -> float:
        sl_distance_pct = self._distance_pct(entry_price, sl_price)
        tp_distance_pct = self._distance_pct(entry_price, tp_price)

        soft_sl_pct = float(settings.get("soft_max_sl_distance_pct", 0.01) or 0.0)
        soft_tp_pct = float(settings.get("soft_max_tp_distance_pct", 0.02) or 0.0)
        hard_sl_pct = float(settings.get("hard_max_sl_distance_pct", 0.03) or 0.0)
        hard_tp_pct = float(settings.get("hard_max_tp_distance_pct", 0.06) or 0.0)
        min_factor = float(settings.get("wide_distance_min_factor", 0.35) or 0.0)
        min_factor = max(0.0, min(1.0, min_factor))

        if hard_sl_pct > 0 and sl_distance_pct > hard_sl_pct:
            return 0.0
        if hard_tp_pct > 0 and tp_distance_pct > hard_tp_pct:
            return 0.0

        sl_factor = 1.0
        tp_factor = 1.0

        if soft_sl_pct > 0 and sl_distance_pct > soft_sl_pct:
            sl_factor = min(1.0, soft_sl_pct / sl_distance_pct)
        if soft_tp_pct > 0 and tp_distance_pct > soft_tp_pct:
            tp_factor = min(1.0, soft_tp_pct / tp_distance_pct)

        combined_factor = sl_factor * tp_factor
        if combined_factor >= 1.0:
            return 1.0
        return max(min_factor, combined_factor)

    def _get_wide_setup_block_reason(
        self,
        entry_price: Optional[float],
        sl_price: Optional[float],
        tp_price: Optional[float],
        settings: Dict[str, Any],
    ) -> Optional[str]:
        if entry_price is None:
            return None

        sl_distance_pct = self._distance_pct(entry_price, sl_price)
        tp_distance_pct = self._distance_pct(entry_price, tp_price)

        hard_sl_pct = float(settings.get("hard_max_sl_distance_pct", 0.03) or 0.0)
        hard_tp_pct = float(settings.get("hard_max_tp_distance_pct", 0.06) or 0.0)

        if hard_sl_pct > 0 and sl_distance_pct > hard_sl_pct:
            return "sl_distance_too_wide"
        if hard_tp_pct > 0 and tp_distance_pct > hard_tp_pct:
            return "tp_distance_too_wide"
        return None

    def compute_position_size(
        self,
        symbol: Optional[str],
        account_snapshot,
        entry_price: Optional[float],
        sl_price: Optional[float],
        tp_price: Optional[float] = None,
        exchange=None,
        now: Optional[datetime] = None,
        confidence: Optional[float] = None,
    ) -> float:
        settings = self._get_position_sizing_settings(symbol)
        equity = float(getattr(account_snapshot, "equity", 0.0) or 0.0)
        if equity <= 0 or entry_price is None or sl_price is None:
            return 0.0

        constraints = None
        if exchange is not None and hasattr(exchange, "get_symbol_trade_constraints"):
            try:
                constraints = exchange.get_symbol_trade_constraints(symbol)
            except Exception:
                constraints = None

        base_lot = float(settings.get("base_lot", 0.01))
        min_lot = float(settings.get("min_lot", getattr(constraints, "min_lot", base_lot) or base_lot))
        max_lot = float(settings.get("max_lot", getattr(constraints, "max_lot", 100.0) or 100.0))
        lot_step = float(settings.get("lot_step", getattr(constraints, "lot_step", 0.01) or 0.01))

        if constraints is not None:
            try:
                min_lot = max(min_lot, float(getattr(constraints, "min_lot", min_lot)))
                max_lot = min(max_lot, float(getattr(constraints, "max_lot", max_lot)))
                lot_step = float(getattr(constraints, "lot_step", lot_step) or lot_step)
            except Exception:
                pass
        max_lot = max(min_lot, max_lot)

        risk_pct = float(settings.get("risk_per_trade_pct", 0.01))
        risk_pct = max(0.0001, risk_pct)
        risk_amount = equity * risk_pct
        loss_per_lot = self._estimate_loss_per_lot(entry_price, sl_price, constraints)

        if loss_per_lot is None or loss_per_lot <= 0:
            raw_volume = base_lot
        else:
            raw_volume = risk_amount / loss_per_lot

        raw_volume *= self.get_effective_volume_multiplier(symbol, now=now or datetime.now())

        if confidence is not None:
            confidence_value = max(0.0, min(1.0, float(confidence)))
            confidence_floor = float(settings.get("confidence_floor", 0.80))
            confidence_ceiling = float(settings.get("confidence_ceiling", 1.25))
            confidence_factor = confidence_floor + ((confidence_ceiling - confidence_floor) * confidence_value)
            raw_volume *= confidence_factor

        geometry_factor = self._get_wide_setup_volume_factor(
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            settings=settings,
        )
        if geometry_factor <= 0:
            return 0.0
        raw_volume *= geometry_factor

        raw_volume = max(base_lot, raw_volume)
        return self._normalize_volume(raw_volume, min_lot=min_lot, max_lot=max_lot, lot_step=lot_step)

    def _record_risk_sample(self, symbol: Optional[str], now: datetime,
                            spread_points: Optional[float] = None,
                            slippage_points: Optional[float] = None):
        if not symbol or now is None:
            return
        if spread_points is not None:
            samples = self._spread_samples_by_symbol.setdefault(symbol, deque(maxlen=60))
            samples.append(float(spread_points))
        if slippage_points is not None:
            samples = self._slippage_samples_by_symbol.setdefault(symbol, deque(maxlen=60))
            samples.append(float(slippage_points))

        last_log = self._last_risk_sample_log_by_symbol.get(symbol)
        if last_log is None or (now - last_log).total_seconds() >= 60:
            spread_samples = self._spread_samples_by_symbol.get(symbol, deque())
            slippage_samples = self._slippage_samples_by_symbol.get(symbol, deque())
            spread_avg = (sum(spread_samples) / len(spread_samples)) if spread_samples else None
            slippage_avg = (sum(slippage_samples) / len(slippage_samples)) if slippage_samples else None
            if spread_points is not None or slippage_points is not None or spread_avg is not None or slippage_avg is not None:
                import logging
                logging.getLogger(__name__).info(
                    f"RISK_SAMPLE - {symbol} "
                    f"spread={spread_points} avg={spread_avg} n={len(spread_samples)} | "
                    f"slippage={slippage_points} avg={slippage_avg} n={len(slippage_samples)}"
                )
                self._last_risk_sample_log_by_symbol[symbol] = now

    def _ensure_runtime_dir(self):
        if not self.state_path:
            return
        directory = os.path.dirname(self.state_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def _save_state(self):
        if not self.state_path:
            return
        self._ensure_runtime_dir()
        data = {
            "current_day": self._current_day.isoformat() if self._current_day else None,
            "daily_pnl": self._daily_pnl,
            "daily_pnl_pct": self._daily_pnl_pct,
            "trades_today": self._trades_today,
            "trades_today_by_symbol": self._trades_today_by_symbol,
            "consecutive_losses": self._consecutive_losses,
            "last_loss_time": self._last_loss_time.isoformat() if self._last_loss_time else None,
            "last_loss_time_by_symbol": {k: v.isoformat() for k, v in self._last_loss_time_by_symbol.items()},
            "traded_symbols_today": sorted(self._traded_symbols_today),
            "daily_realized_pnl": self._daily_realized_pnl,
            "daily_realized_pnl_by_symbol": self._daily_realized_pnl_by_symbol,
            "profit_lock_active": self._profit_lock_active,
            "profit_lock_until": self._profit_lock_until.isoformat() if self._profit_lock_until else None,
            "last_trade_time_by_symbol": {k: v.isoformat() for k, v in self._last_trade_time_by_symbol.items()},
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)

    def _load_state(self):
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            current_day = data.get("current_day")
            self._current_day = date.fromisoformat(current_day) if current_day else None
            self._daily_pnl = float(data.get("daily_pnl", 0.0))
            self._daily_pnl_pct = float(data.get("daily_pnl_pct", 0.0))
            self._trades_today = int(data.get("trades_today", 0))
            self._trades_today_by_symbol = {
                k: int(v) for k, v in data.get("trades_today_by_symbol", {}).items()
            }
            self._consecutive_losses = int(data.get("consecutive_losses", 0))
            last_loss_time = data.get("last_loss_time")
            self._last_loss_time = datetime.fromisoformat(last_loss_time) if last_loss_time else None
            last_loss_time_by_symbol = data.get("last_loss_time_by_symbol", {})
            self._last_loss_time_by_symbol = {
                k: datetime.fromisoformat(v) for k, v in last_loss_time_by_symbol.items()
            }
            self._traded_symbols_today = set(data.get("traded_symbols_today", []))
            self._daily_realized_pnl = float(data.get("daily_realized_pnl", 0.0))
            self._daily_realized_pnl_by_symbol = {
                k: float(v) for k, v in data.get("daily_realized_pnl_by_symbol", {}).items()
            }
            self._profit_lock_active = bool(data.get("profit_lock_active", False))
            profit_lock_until = data.get("profit_lock_until")
            self._profit_lock_until = datetime.fromisoformat(profit_lock_until) if profit_lock_until else None
            last_trade_time_by_symbol = data.get("last_trade_time_by_symbol", {})
            self._last_trade_time_by_symbol = {
                k: datetime.fromisoformat(v) for k, v in last_trade_time_by_symbol.items()
            }
        except Exception:
            return

    def on_new_day(self, new_day: date):
        if self._current_day != new_day:
            self._current_day = new_day
            self._daily_pnl = 0.0
            self._daily_pnl_pct = 0.0
            self._trades_today = 0
            self._trades_today_by_symbol = {}
            self._consecutive_losses = 0
            self._last_loss_time = None
            self._traded_symbols_today = set()
            self._daily_realized_pnl = 0.0
            self._daily_realized_pnl_by_symbol = {}
            self._profit_lock_active = False
            self._profit_lock_until = None
            self._last_trade_time_by_symbol = {}
            self._save_state()

    def update_daily(self, daily_pnl: float, daily_pnl_pct: float, now: datetime):
        self.on_new_day(self._get_trading_day(now))
        self._daily_pnl = float(daily_pnl)
        self._daily_pnl_pct = float(daily_pnl_pct)
        self._save_state()

    def record_trade_open(self, opened_at: datetime, symbol: Optional[str] = None):
        self.on_new_day(self._get_trading_day(opened_at))
        self._trades_today += 1
        if symbol:
            self._traded_symbols_today.add(symbol)
            self._last_trade_time_by_symbol[symbol] = opened_at
            self._trades_today_by_symbol[symbol] = self._trades_today_by_symbol.get(symbol, 0) + 1
        self._save_state()

    def record_trade_close(self, pnl: float, closed_at: datetime, symbol: Optional[str] = None):
        self.on_new_day(self._get_trading_day(closed_at))
        self._daily_realized_pnl += float(pnl)
        if symbol:
            self._daily_realized_pnl_by_symbol[symbol] = self._daily_realized_pnl_by_symbol.get(symbol, 0.0) + float(pnl)
        if pnl < 0:
            self._consecutive_losses += 1
            self._last_loss_time = closed_at  # Global loss time
            if symbol:
                self._last_loss_time_by_symbol[symbol] = closed_at  # Per-symbol loss time
        else:
            self._consecutive_losses = 0
            # Reset per-symbol loss time only if we want to
            # For now, we only set it on loss, so no need to reset
        if self.daily_profit_target_usd and self._daily_realized_pnl >= self.daily_profit_target_usd:
            self._profit_lock_active = True
            if self.profit_lock_mode == "cooldown_hours":
                self._profit_lock_until = closed_at + timedelta(hours=self.profit_lock_hours)
            else:
                next_day = self._get_trading_day(closed_at + timedelta(days=1))
                tz = self._get_tz()
                unlock_time = datetime.combine(next_day, dt_time(self.daily_reset_hour, 0, 0))
                if tz is not None:
                    unlock_time = unlock_time.replace(tzinfo=tz)
                self._profit_lock_until = unlock_time
        self._save_state()

    def allow_trade(self, signal, sl, tp, account_snapshot, **context):
        """Check if a trade is allowed based on risk rules and global guard rails"""
        now_param = context.get("now")
        if now_param is None:
            from datetime import datetime
            now_param = datetime.now()
        
        self.on_new_day(self._get_trading_day(now_param))
        
        # Use the datetime value for comparisons below
        now = now_param
        symbol = context.get("symbol")

        if not self._is_within_trading_session(now, symbol=symbol):
            return False, "outside_trading_session"

        symbol_open_positions_count = context.get("symbol_open_positions_count", 0)
        global_open_positions_count = context.get("global_open_positions_count", None)
        safe_mode = self._get_active_symbol_safe_mode(symbol, now)
        if symbol:
            cooldown_after_trade = self.cooldown_minutes_after_trade_per_symbol
            if isinstance(self.cooldown_after_trade_overrides_by_symbol, dict):
                override = self.cooldown_after_trade_overrides_by_symbol.get(symbol)
                if override is not None:
                    cooldown_after_trade = int(override)
            if safe_mode is not None:
                safe_trade_cooldown = safe_mode.get("cooldown_after_trade_minutes")
                if safe_trade_cooldown is not None:
                    try:
                        cooldown_after_trade = max(cooldown_after_trade, int(safe_trade_cooldown))
                    except Exception:
                        pass
            if cooldown_after_trade > 0:
                last_trade_time = self._last_trade_time_by_symbol.get(symbol)
                if last_trade_time is not None:
                    cooldown_until = last_trade_time + timedelta(minutes=cooldown_after_trade)
                    if now < cooldown_until:
                        return False, "symbol_trade_cooldown"
        max_open_trades_for_symbol = self.max_open_trades_per_symbol
        if symbol and isinstance(self.max_open_trades_per_symbol_by_symbol, dict):
            override = self.max_open_trades_per_symbol_by_symbol.get(symbol)
            if override is not None:
                max_open_trades_for_symbol = int(override)
        if max_open_trades_for_symbol and symbol_open_positions_count >= max_open_trades_for_symbol:
            return False, "blocked_by_symbol_open_limit"

        if self.max_global_open_positions is not None and global_open_positions_count is not None:
            if int(global_open_positions_count) >= int(self.max_global_open_positions):
                return False, "blocked_by_max_global_open_positions"

        if self.max_trades_per_day and self._trades_today >= self.max_trades_per_day:
            return False, "max_trades_per_day"

        per_symbol_limit = None
        if symbol and isinstance(self.max_trades_per_day_by_symbol, dict):
            override_limit = self.max_trades_per_day_by_symbol.get(symbol)
            if override_limit is not None:
                per_symbol_limit = int(override_limit)
        if safe_mode is not None:
            safe_limit = safe_mode.get("max_trades_per_day")
            if safe_limit is not None:
                try:
                    safe_limit_int = int(safe_limit)
                    per_symbol_limit = safe_limit_int if per_symbol_limit is None else min(per_symbol_limit, safe_limit_int)
                except Exception:
                    pass
        if symbol and per_symbol_limit is not None:
            trades_for_symbol = self._trades_today_by_symbol.get(symbol, 0)
            if trades_for_symbol >= int(per_symbol_limit):
                return False, "max_trades_per_day_symbol"

        if symbol:
            symbol_daily_loss_limit = self._get_effective_symbol_daily_loss_limit_usd(symbol, safe_mode)
            if symbol_daily_loss_limit is not None:
                symbol_realized = self._daily_realized_pnl_by_symbol.get(symbol, 0.0)
                if symbol_realized <= -symbol_daily_loss_limit:
                    return False, "symbol_daily_loss_limit_usd"

        if self.max_daily_loss_pct and self._daily_pnl_pct <= -self.max_daily_loss_pct:
            return False, "max_daily_loss_pct"
        if self.max_daily_loss_usd and self._daily_pnl <= -abs(self.max_daily_loss_usd):
            return False, "max_daily_loss_usd"

        if self.one_trade_per_symbol_per_day and symbol and symbol in self._traded_symbols_today:
            return False, "symbol_day_lock"

        if self._profit_lock_active and self._profit_lock_until is not None:
            if now < self._profit_lock_until:
                return False, "daily_profit_lock"
            self._profit_lock_active = False
            self._profit_lock_until = None
            self._save_state()

        if self.max_consecutive_losses and self._consecutive_losses >= self.max_consecutive_losses:
            return False, "max_consecutive_losses"

        if self.cooldown_minutes_after_loss and symbol:
            # Check per-symbol cooldown after loss with potential override
            symbol_cooldown_minutes = self.cooldown_overrides_by_symbol.get(symbol, self.cooldown_minutes_after_loss)
            if safe_mode is not None:
                safe_loss_cooldown = safe_mode.get("cooldown_after_loss_minutes")
                if safe_loss_cooldown is not None:
                    try:
                        symbol_cooldown_minutes = max(symbol_cooldown_minutes, int(safe_loss_cooldown))
                    except Exception:
                        pass
            last_loss_time = self._last_loss_time_by_symbol.get(symbol)
            if last_loss_time is not None:
                cooldown_until = last_loss_time + timedelta(minutes=symbol_cooldown_minutes)
                if now < cooldown_until:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"RISK_COOLDOWN - {symbol} blocked ({symbol_cooldown_minutes}m) last_loss={last_loss_time}")
                    return False, "symbol_cooldown_after_loss"

        # Check global cooldown after loss (optional)
        if self.global_cooldown_minutes_after_loss and self._last_loss_time is not None:
            global_cooldown_until = self._last_loss_time + timedelta(minutes=self.global_cooldown_minutes_after_loss)
            if now < global_cooldown_until:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"RISK_COOLDOWN - {symbol} blocked by global cooldown ({self.global_cooldown_minutes_after_loss}m) last_loss={self._last_loss_time}")
                return False, "global_cooldown_after_loss"

        exchange = context.get("exchange")
        df = context.get("df")
        reference_price = context.get("reference_price")
        if reference_price is None and df is not None and len(df) >= 2:
            reference_price = float(df["close"].iloc[-2])
        elif reference_price is None and df is not None and len(df) >= 1:
            reference_price = float(df["close"].iloc[-1])

        if signal in ("BUY", "SELL"):
            sizing_settings = self._get_position_sizing_settings(symbol)
            wide_setup_reason = self._get_wide_setup_block_reason(
                entry_price=reference_price,
                sl_price=sl,
                tp_price=tp,
                settings=sizing_settings,
            )
            if wide_setup_reason is not None:
                import logging
                logging.getLogger(__name__).info(
                    f"RISK_FILTER - {symbol} blocked by wide setup "
                    f"entry={reference_price} sl={sl} tp={tp} reason={wide_setup_reason}"
                )
                return False, wide_setup_reason

        if exchange is not None and symbol:
            spread_sample = None
            slippage_sample = None
            # Use symbol-specific spread threshold with fallback to default
            if self.max_spread_points_default is not None or self.max_spread_points_by_symbol:
                # Use symbol-specific threshold if available, otherwise use default
                spread_threshold = self.max_spread_points_by_symbol.get(symbol, self.max_spread_points_default)
                if spread_threshold is not None and hasattr(exchange, "estimate_spread_points"):
                    spread_points = exchange.estimate_spread_points(symbol)
                    if spread_points is not None:
                        spread_sample = float(spread_points)
                        if spread_points > float(spread_threshold):
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.info(
                                f"RISK_FILTER - {symbol} blocked by spread={spread_points} > limit={spread_threshold}"
                            )
                            self._record_risk_sample(symbol, now, spread_points=spread_sample)
                            return False, "max_spread_points"
                        else:
                            import logging
                            logging.getLogger(__name__).info(
                                f"RISK_CHECK - symbol={symbol} spread={spread_points} max={spread_threshold} result=ALLOWED"
                            )

            # Use symbol-specific slippage threshold with fallback to default
            if self.max_slippage_points_default is not None or self.max_slippage_points_by_symbol:
                # Use symbol-specific threshold if available, otherwise use default
                slippage_threshold = self.max_slippage_points_by_symbol.get(symbol, self.max_slippage_points_default)
                if slippage_threshold is not None and hasattr(exchange, "estimate_slippage_points"):
                    slippage_points = exchange.estimate_slippage_points(symbol, reference_price, signal)
                    if slippage_points is not None:
                        slippage_sample = float(slippage_points)
                        if slippage_points > float(slippage_threshold):
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.info(
                                f"RISK_FILTER - {symbol} blocked by slippage={slippage_points} > limit={slippage_threshold}"
                            )
                            self._record_risk_sample(symbol, now, spread_points=spread_sample, slippage_points=slippage_sample)
                            return False, "max_slippage_points"
                        else:
                            import logging
                            logging.getLogger(__name__).info(
                                f"RISK_CHECK - symbol={symbol} slippage={slippage_points} max={slippage_threshold} result=ALLOWED"
                            )
            self._record_risk_sample(symbol, now, spread_points=spread_sample, slippage_points=slippage_sample)

        if not self.rules:
            return True, "No risk rules configured"
        
        # Validate against all configured rules
        for rule in self.rules:
            if rule.enabled and hasattr(rule, 'validate'):
                try:
                    # Call the rule's validate method with appropriate parameters
                    if not rule.validate(signal, sl, tp, account_snapshot):
                        return False, f"Rule '{rule.__class__.__name__}' blocked trade"
                except Exception as e:
                    return False, f"Rule '{rule.__class__.__name__}' validation error: {e}"
        
        return True, "Trade allowed by risk management"

    def get_state(self):
        return {
            "daily_pnl": self._daily_pnl,
            "daily_pnl_pct": self._daily_pnl_pct,
            "trades_today": self._trades_today,
            "trades_today_by_symbol": self._trades_today_by_symbol,
            "consecutive_losses": self._consecutive_losses,
            "last_loss_time": self._last_loss_time,
            "current_day": self._current_day,
            "traded_symbols_today": sorted(self._traded_symbols_today),
            "daily_realized_pnl": self._daily_realized_pnl,
            "daily_realized_pnl_by_symbol": self._daily_realized_pnl_by_symbol,
            "profit_lock_active": self._profit_lock_active,
            "profit_lock_until": self._profit_lock_until,
            "last_trade_time_by_symbol": self._last_trade_time_by_symbol,
        }

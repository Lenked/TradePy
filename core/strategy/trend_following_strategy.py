"""
Simple Trend Following Strategy for TradePy bot.
"""
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from ai.decision import HybridDecisionEngine
from .base import Strategy
from .signal import SignalType


class TrendFollowingStrategy(Strategy):
    """
    Trend-following strategy with an optional hybrid decision layer.
    """

    def __init__(
        self,
        ema_short_period: int = 50,
        ema_long_period: int = 200,
        rsi_period: int = 14,
        atr_period: int = 14,
        sl_atr_multiplier: float = 2.0,
        tp_atr_multiplier: float = 3.0,
        sl_tp_overrides_by_symbol: dict = None,
        rsi_buy_max: float = None,
        rsi_sell_min: float = None,
        ai_decision_config: dict = None,
    ):
        self.ema_short_period = int(ema_short_period)
        self.ema_long_period = int(ema_long_period)
        self.rsi_period = int(rsi_period)
        self.atr_period = int(atr_period)
        self.sl_atr_multiplier = float(sl_atr_multiplier)
        self.tp_atr_multiplier = float(tp_atr_multiplier)
        self.sl_tp_overrides_by_symbol = sl_tp_overrides_by_symbol or {}
        self.rsi_buy_max = float(rsi_buy_max) if rsi_buy_max is not None else None
        self.rsi_sell_min = float(rsi_sell_min) if rsi_sell_min is not None else None
        self.ai_decision_config = ai_decision_config or {}
        self.ai_decision_engine = HybridDecisionEngine(self.ai_decision_config)
        self.ai_volatility_target = float(self.ai_decision_config.get("volatility_target", 0.01))
        self.name = "Simple Trend Following Strategy"

    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        return prices.ewm(span=period, adjust=False).mean()

    def calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50.0)
        rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
        rsi = rsi.mask((gain == 0) & (loss > 0), 0.0)
        rsi = rsi.mask((gain == 0) & (loss == 0), 50.0)
        return rsi

    def calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.rolling(window=period).mean()

    def _indicator_snapshot(self, data: pd.DataFrame) -> Optional[Dict[str, float]]:
        min_history = max(self.ema_long_period, self.rsi_period + 2, self.atr_period + 2)
        if data is None or data.empty or len(data) < min_history:
            return None

        close = data["close"].astype(float)
        ema_short_series = self.calculate_ema(close, self.ema_short_period)
        ema_long_series = self.calculate_ema(close, self.ema_long_period)
        rsi_series = self.calculate_rsi(close, self.rsi_period)
        atr_series = self.calculate_atr(data[["high", "low", "close"]].astype(float), self.atr_period)

        current_price = float(close.iloc[-1])
        ema_short = float(ema_short_series.iloc[-1])
        ema_long = float(ema_long_series.iloc[-1])
        rsi = float(rsi_series.iloc[-1])
        atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0
        atr = atr if atr > 0 else max(current_price * 0.001, 1e-6)

        lookback = min(5, len(close) - 1)
        prev_close = float(close.iloc[-(lookback + 1)]) if lookback > 0 else current_price

        snapshot = {
            "current_price": current_price,
            "ema_short": ema_short,
            "ema_long": ema_long,
            "rsi": rsi,
            "atr": atr,
            "previous_close": prev_close,
            "recent_return": ((current_price / prev_close) - 1.0) if prev_close else 0.0,
        }
        if any(pd.isna(list(snapshot.values()))):
            return None
        return snapshot

    def _base_signal_from_snapshot(self, snapshot: Dict[str, float]) -> str:
        current_price = snapshot["current_price"]
        ema_short = snapshot["ema_short"]
        ema_long = snapshot["ema_long"]
        rsi = snapshot["rsi"]

        if self.rsi_buy_max is not None and rsi >= self.rsi_buy_max:
            return SignalType.HOLD
        if self.rsi_sell_min is not None and rsi <= self.rsi_sell_min:
            return SignalType.HOLD

        if ema_short > ema_long and rsi > 50 and current_price > ema_short:
            return SignalType.BUY
        if ema_short < ema_long and rsi < 50 and current_price < ema_short:
            return SignalType.SELL
        return SignalType.HOLD

    def _ai_snapshot(self, snapshot: Dict[str, float]) -> Dict[str, float]:
        current_price = snapshot["current_price"]
        atr = max(snapshot["atr"], current_price * 0.001, 1e-6)
        atr_pct = atr / max(current_price, 1e-6)
        volatility_penalty = min(abs(atr_pct - self.ai_volatility_target) / max(self.ai_volatility_target, 1e-6), 1.0)

        return {
            "trend_bias": (snapshot["ema_short"] - snapshot["ema_long"]) / atr,
            "momentum_bias": (snapshot["rsi"] - 50.0) / 25.0,
            "alignment_bias": (current_price - snapshot["ema_short"]) / atr,
            "breakout_bias": snapshot["recent_return"] / max(atr_pct, 1e-6),
            "volatility_penalty": volatility_penalty,
        }

    def generate_decision(self, data: pd.DataFrame, symbol: str = None) -> Dict[str, Any]:
        snapshot = self._indicator_snapshot(data)
        if snapshot is None:
            return {
                "signal": SignalType.HOLD,
                "confidence": 0.0,
                "reason": "insufficient_data",
                "source": "base_strategy",
                "base_signal": SignalType.HOLD,
                "symbol": symbol,
            }

        base_signal = self._base_signal_from_snapshot(snapshot)
        decision = {
            "signal": base_signal,
            "confidence": 0.55 if base_signal in (SignalType.BUY, SignalType.SELL) else 0.0,
            "reason": "base_strategy_signal" if base_signal != SignalType.HOLD else "base_strategy_hold",
            "source": "base_strategy",
            "base_signal": base_signal,
            "symbol": symbol,
        }

        if self.ai_decision_engine.enabled:
            decision = self.ai_decision_engine.evaluate(self._ai_snapshot(snapshot), base_signal=base_signal)
            decision["symbol"] = symbol

        decision["metrics"] = {
            "rsi": round(snapshot["rsi"], 4),
            "atr": round(snapshot["atr"], 6),
            "atr_pct": round(snapshot["atr"] / max(snapshot["current_price"], 1e-6), 6),
            "price": round(snapshot["current_price"], 6),
            "ema_short": round(snapshot["ema_short"], 6),
            "ema_long": round(snapshot["ema_long"], 6),
            "ema_spread": round(snapshot["ema_short"] - snapshot["ema_long"], 6),
            "ema_spread_pct": round((snapshot["ema_short"] - snapshot["ema_long"]) / max(snapshot["current_price"], 1e-6), 6),
            "recent_return": round(snapshot["recent_return"], 6),
        }
        return decision

    def generate_signal(self, data: pd.DataFrame) -> SignalType:
        return self.generate_decision(data).get("signal", SignalType.HOLD)

    def hold_reason(self, data: pd.DataFrame) -> Optional[str]:
        decision = self.generate_decision(data)
        if decision.get("signal") == SignalType.HOLD:
            return decision.get("reason")
        return None

    def get_name(self) -> str:
        return self.name

    def get_parameters(self) -> dict:
        return {
            "ema_short_period": self.ema_short_period,
            "ema_long_period": self.ema_long_period,
            "rsi_period": self.rsi_period,
            "atr_period": self.atr_period,
            "rsi_buy_max": self.rsi_buy_max,
            "rsi_sell_min": self.rsi_sell_min,
            "ai_decision_enabled": self.ai_decision_engine.enabled,
        }

    def compute_sl_tp(self, df: pd.DataFrame, signal: str, symbol: str = None) -> Tuple[float, float]:
        if df is None or df.empty:
            raise ValueError("DataFrame cannot be None or empty")
        if len(df) < 2:
            raise ValueError("DataFrame must have at least 2 rows")

        current_price = float(df["close"].iloc[-1])
        atr_period = min(self.atr_period, len(df) - 1)
        atr_df = df.tail(atr_period + 10) if len(df) > atr_period + 10 else df
        atr = self.calculate_atr(atr_df[["high", "low", "close"]].astype(float), atr_period).iloc[-1]
        atr = float(atr) if not pd.isna(atr) and atr > 0 else max(current_price * 0.001, 1e-6)

        sl_multiplier = self.sl_atr_multiplier
        tp_multiplier = self.tp_atr_multiplier
        if symbol and isinstance(self.sl_tp_overrides_by_symbol, dict):
            override = self.sl_tp_overrides_by_symbol.get(symbol, {})
            if isinstance(override, dict):
                if override.get("sl_atr") is not None:
                    sl_multiplier = float(override.get("sl_atr"))
                if override.get("tp_atr") is not None:
                    tp_multiplier = float(override.get("tp_atr"))

        signal_upper = signal.upper()
        if signal_upper == SignalType.BUY:
            sl = current_price - (sl_multiplier * atr)
            tp = current_price + (tp_multiplier * atr)
        elif signal_upper == SignalType.SELL:
            sl = current_price + (sl_multiplier * atr)
            tp = current_price - (tp_multiplier * atr)
        else:
            raise ValueError(f"Invalid signal: {signal}. Expected 'BUY' or 'SELL'")
        return sl, tp

    def compute_volume(
        self,
        df: pd.DataFrame,
        signal: str,
        account_equity: float,
        symbol: str = None,
        sl: float = None,
        tp: float = None,
    ) -> float:
        """
        Fallback position sizing when no dedicated risk-based sizer is provided.
        """
        if df is None or df.empty:
            return 0.01

        current_price = float(df["close"].iloc[-1])
        atr_period = min(self.atr_period, len(df) - 1)
        atr_df = df.tail(atr_period + 10) if len(df) > atr_period + 10 else df
        atr = self.calculate_atr(atr_df[["high", "low", "close"]].astype(float), atr_period).iloc[-1]
        atr = float(atr) if not pd.isna(atr) and atr > 0 else max(current_price * 0.001, 1e-6)

        if sl is None:
            sl, _ = self.compute_sl_tp(df, signal, symbol=symbol)
        risk_distance = abs(current_price - sl) if sl is not None else atr
        risk_distance = max(risk_distance, atr, current_price * 0.001)

        risk_amount = max(float(account_equity), 0.0) * 0.01
        raw_volume = risk_amount / max(risk_distance * 1000.0, 1e-6)

        min_volume = 0.01
        max_volume = max(0.1, (float(account_equity) / 10000.0) * 0.3)
        volume = max(min_volume, min(raw_volume, max_volume))
        return round(volume, 2)

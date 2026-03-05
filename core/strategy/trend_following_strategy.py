"""
Simple Trend Following Strategy for TradePy bot.
"""
from typing import Optional, Tuple

import numpy as np
import pandas as pd

try:
    import pandas_ta as pandas_ta
except ImportError:  # pragma: no cover - optional dependency
    pandas_ta = None

try:
    from ta.momentum import rsi as ta_rsi
    from ta.trend import adx as ta_adx
    from ta.trend import ema_indicator as ta_ema
    from ta.volatility import average_true_range as ta_atr
except ImportError:  # pragma: no cover - optional dependency
    ta_ema = None
    ta_rsi = None
    ta_atr = None
    ta_adx = None

try:
    from arch import arch_model
except ImportError:  # pragma: no cover - optional dependency
    arch_model = None

from .base import Strategy
from .signal import SignalType


class TrendFollowingStrategy(Strategy):
    """
    EMA/RSI trend strategy with optional ADX regime filter and ARCH volatility filter.
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
        use_pandas_ta: bool = True,
        use_adx_filter: bool = True,
        adx_period: int = 14,
        adx_threshold: float = 18.0,
        use_arch_volatility_filter: bool = False,
        arch_lookback: int = 300,
        max_conditional_volatility: Optional[float] = 0.02,
    ):
        self.ema_short_period = int(ema_short_period)
        self.ema_long_period = int(ema_long_period)
        self.rsi_period = int(rsi_period)
        self.atr_period = int(atr_period)
        self.sl_atr_multiplier = float(sl_atr_multiplier)
        self.tp_atr_multiplier = float(tp_atr_multiplier)
        self.sl_tp_overrides_by_symbol = sl_tp_overrides_by_symbol or {}

        self.use_pandas_ta = bool(use_pandas_ta)
        self.use_adx_filter = bool(use_adx_filter)
        self.adx_period = int(adx_period)
        self.adx_threshold = float(adx_threshold)

        self.use_arch_volatility_filter = bool(use_arch_volatility_filter)
        self.arch_lookback = int(arch_lookback)
        self.max_conditional_volatility = (
            float(max_conditional_volatility) if max_conditional_volatility is not None else None
        )

        self._last_hold_reason = "not_evaluated"
        self._arch_cache_key = None
        self._arch_cache_value = None

        self.name = "Simple Trend Following Strategy"

    def _hold(self, reason: str) -> SignalType:
        self._last_hold_reason = reason
        return SignalType.HOLD

    def hold_reason(self, _data: Optional[pd.DataFrame] = None) -> str:
        return self._last_hold_reason or "no_entry_conditions_met"

    def _closed_bar_index(self, df: pd.DataFrame) -> int:
        return -2 if len(df) >= 2 else -1

    def _closed_bars_only(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) >= 2:
            return df.iloc[:-1]
        return df

    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        return prices.ewm(span=period, adjust=False).mean()

    def calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        # Keep RSI finite when one side has no movement for the window.
        rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
        rsi = rsi.where(~((avg_gain == 0) & (avg_loss > 0)), 0.0)
        rsi = rsi.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
        return rsi

    def calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    def calculate_adx(self, df: pd.DataFrame, period: int) -> pd.Series:
        up_move = df["high"].diff()
        down_move = -df["low"].diff()

        plus_dm = pd.Series(
            np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
        )
        minus_dm = pd.Series(
            np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
        )

        atr = self.calculate_atr(df, period).replace(0, np.nan)
        plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr)

        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    def _estimate_conditional_volatility(self, close: pd.Series) -> Optional[float]:
        if not self.use_arch_volatility_filter or arch_model is None:
            return None

        returns = np.log(close).diff().dropna() * 100.0
        if len(returns) < 80:
            return None

        returns = returns.tail(max(self.arch_lookback, 80))
        cache_key = (str(returns.index[-1]), len(returns))
        if self._arch_cache_key == cache_key:
            return self._arch_cache_value

        try:
            model = arch_model(returns, mean="Zero", vol="GARCH", p=1, q=1, rescale=False)
            fit = model.fit(disp="off", show_warning=False)
            variance = float(fit.forecast(horizon=1, reindex=False).variance.values[-1, 0])
            if variance < 0:
                return None
            cond_vol = float(np.sqrt(variance) / 100.0)
        except Exception:
            return None

        self._arch_cache_key = cache_key
        self._arch_cache_value = cond_vol
        return cond_vol

    def _compute_indicators(self, df: pd.DataFrame) -> dict:
        close = df["close"]
        if self.use_pandas_ta and pandas_ta is not None:
            ema_short = pandas_ta.ema(close, length=self.ema_short_period)
            ema_long = pandas_ta.ema(close, length=self.ema_long_period)
            rsi = pandas_ta.rsi(close, length=self.rsi_period)
            atr = pandas_ta.atr(high=df["high"], low=df["low"], close=close, length=self.atr_period)

            adx = None
            if self.use_adx_filter:
                adx_df = pandas_ta.adx(high=df["high"], low=df["low"], close=close, length=self.adx_period)
                if isinstance(adx_df, pd.DataFrame) and not adx_df.empty:
                    adx_col = f"ADX_{self.adx_period}"
                    if adx_col not in adx_df.columns:
                        adx_col = adx_df.columns[0]
                    adx = adx_df[adx_col]

            return {
                "ema_short": ema_short,
                "ema_long": ema_long,
                "rsi": rsi,
                "atr": atr,
                "adx": adx,
            }

        if self.use_pandas_ta and ta_ema is not None and ta_rsi is not None and ta_atr is not None:
            ema_short = ta_ema(close=close, window=self.ema_short_period, fillna=False)
            ema_long = ta_ema(close=close, window=self.ema_long_period, fillna=False)
            rsi = ta_rsi(close=close, window=self.rsi_period, fillna=False)
            atr = ta_atr(
                high=df["high"], low=df["low"], close=close, window=self.atr_period, fillna=False
            )
            adx = (
                ta_adx(high=df["high"], low=df["low"], close=close, window=self.adx_period, fillna=False)
                if self.use_adx_filter and ta_adx is not None
                else None
            )
            return {
                "ema_short": ema_short,
                "ema_long": ema_long,
                "rsi": rsi,
                "atr": atr,
                "adx": adx,
            }

        return {
            "ema_short": self.calculate_ema(close, self.ema_short_period),
            "ema_long": self.calculate_ema(close, self.ema_long_period),
            "rsi": self.calculate_rsi(close, self.rsi_period),
            "atr": self.calculate_atr(df, self.atr_period),
            "adx": self.calculate_adx(df, self.adx_period) if self.use_adx_filter else None,
        }

    def generate_signal(self, data: pd.DataFrame) -> SignalType:
        if data is None or data.empty:
            return self._hold("empty_data")

        required_columns = ("close", "high", "low")
        missing_columns = [col for col in required_columns if col not in data.columns]
        if missing_columns:
            return self._hold(f"missing_columns:{','.join(missing_columns)}")

        min_bars = max(self.ema_long_period, self.rsi_period, self.atr_period, self.adx_period) + 5
        if len(data) < max(min_bars, 8):
            return self._hold("insufficient_history")

        df = data.copy()
        indicators = self._compute_indicators(df)
        ref_idx = self._closed_bar_index(df)

        current_price = float(df["close"].iloc[ref_idx])
        ema_short = indicators["ema_short"].iloc[ref_idx]
        ema_long = indicators["ema_long"].iloc[ref_idx]
        rsi = indicators["rsi"].iloc[ref_idx]

        if any(pd.isna([ema_short, ema_long, rsi])):
            return self._hold("indicators_not_ready")

        if self.use_adx_filter and indicators.get("adx") is not None:
            adx_value = indicators["adx"].iloc[ref_idx]
            if pd.isna(adx_value):
                return self._hold("adx_not_ready")
            if float(adx_value) < self.adx_threshold:
                return self._hold(f"weak_trend_adx:{float(adx_value):.2f}")

        if self.use_arch_volatility_filter and self.max_conditional_volatility is not None:
            close_for_arch = self._closed_bars_only(df)["close"]
            cond_vol = self._estimate_conditional_volatility(close_for_arch)
            if cond_vol is not None and cond_vol > self.max_conditional_volatility:
                return self._hold(f"high_conditional_volatility:{cond_vol:.4f}")

        if ema_short > ema_long and rsi > 50 and current_price > ema_short:
            self._last_hold_reason = "buy_signal"
            return SignalType.BUY

        if ema_short < ema_long and rsi < 50 and current_price < ema_short:
            self._last_hold_reason = "sell_signal"
            return SignalType.SELL

        return self._hold("no_entry_conditions_met")

    def get_name(self) -> str:
        return self.name

    def get_parameters(self) -> dict:
        return {
            "ema_short_period": self.ema_short_period,
            "ema_long_period": self.ema_long_period,
            "rsi_period": self.rsi_period,
            "atr_period": self.atr_period,
            "use_pandas_ta": self.use_pandas_ta,
            "use_adx_filter": self.use_adx_filter,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold,
            "use_arch_volatility_filter": self.use_arch_volatility_filter,
            "arch_lookback": self.arch_lookback,
            "max_conditional_volatility": self.max_conditional_volatility,
        }

    def _latest_atr(self, df: pd.DataFrame) -> float:
        if df is None or df.empty:
            return 0.0

        atr_period = min(max(2, self.atr_period), max(2, len(df) - 1))
        if atr_period <= 1:
            return float((df["high"] - df["low"]).iloc[-1])

        atr_series = self._compute_indicators(df).get("atr")
        if atr_series is None or atr_series.empty:
            return float((df["high"] - df["low"]).tail(5).mean())

        atr_value = float(atr_series.iloc[-1])
        if np.isnan(atr_value) or atr_value <= 0:
            return float((df["high"] - df["low"]).tail(5).mean())
        return atr_value

    def compute_sl_tp(self, df: pd.DataFrame, signal: str, symbol: str = None) -> Tuple[float, float]:
        if df is None or df.empty:
            raise ValueError("DataFrame cannot be None or empty")
        if len(df) < 3:
            raise ValueError("DataFrame must have at least 3 rows")

        ref_idx = self._closed_bar_index(df)
        current_price = float(df["close"].iloc[ref_idx])
        closed_df = self._closed_bars_only(df)
        atr = self._latest_atr(closed_df)

        sl_multiplier = self.sl_atr_multiplier
        tp_multiplier = self.tp_atr_multiplier

        if symbol and isinstance(self.sl_tp_overrides_by_symbol, dict):
            override = self.sl_tp_overrides_by_symbol.get(symbol, {})
            if isinstance(override, dict):
                if override.get("sl_atr") is not None:
                    sl_multiplier = float(override.get("sl_atr"))
                if override.get("tp_atr") is not None:
                    tp_multiplier = float(override.get("tp_atr"))

        signal_upper = str(signal).upper()
        if signal_upper == "BUY":
            sl = current_price - (sl_multiplier * atr)
            tp = current_price + (tp_multiplier * atr)
        elif signal_upper == "SELL":
            sl = current_price + (sl_multiplier * atr)
            tp = current_price - (tp_multiplier * atr)
        else:
            raise ValueError(f"Invalid signal: {signal}. Expected 'BUY' or 'SELL'")

        return float(sl), float(tp)

    def compute_volume(self, df: pd.DataFrame, signal: str, account_equity: float) -> float:
        if self.name.lower().find("demo") != -1 or str(account_equity).find("demo") != -1:
            base_volume = 0.01
        else:
            if account_equity < 1000:
                base_volume = 0.01
            elif account_equity < 5000:
                base_volume = 0.02
            elif account_equity < 10000:
                base_volume = 0.03
            elif account_equity < 25000:
                base_volume = 0.05
            else:
                base_volume = min(0.10, account_equity * 0.001)

        ref_idx = self._closed_bar_index(df)
        current_price = float(df["close"].iloc[ref_idx])

        closed_df = self._closed_bars_only(df)
        atr = self._latest_atr(closed_df)
        sl, _ = self.compute_sl_tp(df, signal)
        risk_per_unit = abs(current_price - sl) if sl is not None else atr * 2.0

        if risk_per_unit <= 0:
            risk_per_unit = max(atr * 2.0, 0.0001)

        risk_amount = float(account_equity) * 0.01
        calculated_volume = risk_amount / risk_per_unit
        volume = min(calculated_volume, base_volume)

        min_volume = 0.01
        max_volume = 100.0
        return float(max(min_volume, min(volume, max_volume)))

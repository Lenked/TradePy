"""
Backtesting engine for TradePy bot.

This engine uses the `backtesting` package and adapts TradePy strategies
(`generate_signal`, `compute_sl_tp`, `compute_volume`) to its runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy as BacktestingStrategy


@dataclass
class BacktestResult:
    """Container for backtest artifacts."""

    stats: pd.Series
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    data: pd.DataFrame
    strategy_name: str
    symbol: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "stats": self.stats,
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "data": self.data,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
        }


class BacktestEngine:
    """Main backtesting engine."""

    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission: float = 0.0,
        trade_on_close: bool = True,
        exclusive_orders: bool = True,
        finalize_trades: bool = True,
    ):
        self.initial_capital = float(initial_capital)
        self.commission = float(commission)
        self.trade_on_close = bool(trade_on_close)
        self.exclusive_orders = bool(exclusive_orders)
        self.finalize_trades = bool(finalize_trades)

    def _prepare_ohlcv_data(self, data: pd.DataFrame) -> pd.DataFrame:
        if data is None or data.empty:
            raise ValueError("Backtest data cannot be None or empty")

        df = data.copy()

        # Resolve index
        if not isinstance(df.index, pd.DatetimeIndex):
            time_col = None
            for candidate in ("time", "timestamp", "datetime", "date"):
                if candidate in df.columns:
                    time_col = candidate
                    break
            if time_col is not None:
                df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
                df = df.set_index(time_col)

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[~df.index.isna()]
        df = df.sort_index()

        # Normalize OHLCV names expected by backtesting.py
        rename_map = {}
        for low, high in (
            ("open", "Open"),
            ("high", "High"),
            ("low", "Low"),
            ("close", "Close"),
            ("volume", "Volume"),
        ):
            if low in df.columns and high not in df.columns:
                rename_map[low] = high
        if rename_map:
            df = df.rename(columns=rename_map)

        required = {"Open", "High", "Low", "Close"}
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"Data must contain OHLC columns; missing={missing}")

        if "Volume" not in df.columns:
            df["Volume"] = 0.0

        numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if len(df) < 50:
            raise ValueError("Not enough bars for a meaningful backtest (min 50)")

        return df[["Open", "High", "Low", "Close", "Volume"]]

    def _build_adapter(self, strategy_obj, symbol: str):
        class TradePyStrategyAdapter(BacktestingStrategy):
            _strategy_obj = strategy_obj
            _symbol = symbol

            def init(self):
                self._last_signal = "HOLD"

            def _frame(self) -> pd.DataFrame:
                close = pd.Series(self.data.Close, index=self.data.index)
                high = pd.Series(self.data.High, index=self.data.index)
                low = pd.Series(self.data.Low, index=self.data.index)
                open_ = pd.Series(self.data.Open, index=self.data.index)
                volume = pd.Series(self.data.Volume, index=self.data.index)
                return pd.DataFrame(
                    {
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    }
                )

            def _normalize_signal(self, raw_signal: Any) -> str:
                if raw_signal is None:
                    return "HOLD"
                text = str(raw_signal).upper()
                return text if text in {"BUY", "SELL", "HOLD"} else "HOLD"

            def _normalize_size(self, raw_size: float) -> float:
                try:
                    size = float(raw_size)
                except Exception:
                    size = 0.01
                # backtesting.py accepts sizes <1 as a fraction of available equity.
                return float(max(0.01, min(size, 1.0)))

            def _safe_sl_tp(self, signal: str, price: float, sl: Optional[float], tp: Optional[float]):
                try:
                    sl_val = float(sl) if sl is not None else None
                    tp_val = float(tp) if tp is not None else None
                except Exception:
                    return None, None

                if sl_val is None or tp_val is None:
                    return None, None

                if signal == "BUY":
                    if not (sl_val < price < tp_val):
                        return None, None
                elif signal == "SELL":
                    if not (tp_val < price < sl_val):
                        return None, None
                return sl_val, tp_val

            def next(self):
                df = self._frame()
                if len(df) < 3:
                    return

                signal = self._normalize_signal(self._strategy_obj.generate_signal(df))
                self._last_signal = signal

                if signal == "HOLD":
                    return

                # If opposite signal arrives, flatten first.
                if self.position:
                    if (self.position.is_long and signal == "SELL") or (
                        self.position.is_short and signal == "BUY"
                    ):
                        self.position.close()
                    else:
                        return

                sl = tp = None
                if hasattr(self._strategy_obj, "compute_sl_tp"):
                    try:
                        sl, tp = self._strategy_obj.compute_sl_tp(df, signal, symbol=self._symbol)
                    except TypeError:
                        sl, tp = self._strategy_obj.compute_sl_tp(df, signal)
                    except Exception:
                        sl, tp = None, None

                size = 0.02
                if hasattr(self._strategy_obj, "compute_volume"):
                    try:
                        size = self._strategy_obj.compute_volume(df, signal, self.equity)
                    except Exception:
                        size = 0.02
                size = self._normalize_size(size)

                current_price = float(self.data.Close[-1])
                sl, tp = self._safe_sl_tp(signal, current_price, sl, tp)

                if signal == "BUY":
                    self.buy(size=size, sl=sl, tp=tp)
                elif signal == "SELL":
                    self.sell(size=size, sl=sl, tp=tp)

        return TradePyStrategyAdapter

    def run_backtest(
        self,
        strategy,
        data: pd.DataFrame,
        symbol: str = "BACKTEST",
    ) -> BacktestResult:
        prepared = self._prepare_ohlcv_data(data)
        adapter = self._build_adapter(strategy_obj=strategy, symbol=symbol)

        bt = Backtest(
            prepared,
            adapter,
            cash=self.initial_capital,
            commission=self.commission,
            trade_on_close=self.trade_on_close,
            exclusive_orders=self.exclusive_orders,
            finalize_trades=self.finalize_trades,
        )
        stats = bt.run()
        equity_curve = stats.get("_equity_curve", pd.DataFrame())
        trades = stats.get("_trades", pd.DataFrame())

        strategy_name = strategy.get_name() if hasattr(strategy, "get_name") else strategy.__class__.__name__
        return BacktestResult(
            stats=stats,
            equity_curve=equity_curve,
            trades=trades,
            data=prepared,
            strategy_name=strategy_name,
            symbol=symbol,
        )

    def run_backtest_from_csv(self, strategy, csv_path: str, symbol: str = "BACKTEST") -> BacktestResult:
        df = pd.read_csv(csv_path)
        return self.run_backtest(strategy=strategy, data=df, symbol=symbol)

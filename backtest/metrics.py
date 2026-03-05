"""
Backtesting metrics for TradePy bot.
"""
from __future__ import annotations

import math
from typing import Any, Dict

import pandas as pd


class BacktestMetrics:
    """Calculate normalized performance metrics from backtesting results."""

    def __init__(self, results: Any):
        if isinstance(results, dict):
            self.stats = results.get("stats", pd.Series(dtype=float))
        else:
            self.stats = results
        if self.stats is None:
            self.stats = pd.Series(dtype=float)

    def _get(self, key: str, default: float = 0.0) -> float:
        value = self.stats.get(key, default) if hasattr(self.stats, "get") else default
        try:
            val = float(value)
            return val if math.isfinite(val) else float(default)
        except Exception:
            return float(default)

    def calculate_total_return(self) -> float:
        """Total return in percent."""
        return self._get("Return [%]", 0.0)

    def calculate_sharpe_ratio(self) -> float:
        """Sharpe ratio."""
        return self._get("Sharpe Ratio", 0.0)

    def calculate_max_drawdown(self) -> float:
        """Maximum drawdown in percent (absolute value)."""
        dd = self._get("Max. Drawdown [%]", 0.0)
        return abs(dd)

    def calculate_win_rate(self) -> float:
        """Win rate in percent."""
        return self._get("Win Rate [%]", 0.0)

    def calculate_profit_factor(self) -> float:
        return self._get("Profit Factor", 0.0)

    def calculate_expectancy(self) -> float:
        return self._get("Expectancy [%]", 0.0)

    def to_dict(self) -> Dict[str, float]:
        return {
            "total_return_pct": self.calculate_total_return(),
            "sharpe_ratio": self.calculate_sharpe_ratio(),
            "max_drawdown_pct": self.calculate_max_drawdown(),
            "win_rate_pct": self.calculate_win_rate(),
            "profit_factor": self.calculate_profit_factor(),
            "expectancy_pct": self.calculate_expectancy(),
            "trades": self._get("# Trades", 0.0),
            "buy_and_hold_return_pct": self._get("Buy & Hold Return [%]", 0.0),
            "return_ann_pct": self._get("Return (Ann.) [%]", 0.0),
            "volatility_ann_pct": self._get("Volatility (Ann.) [%]", 0.0),
            "calmar_ratio": self._get("Calmar Ratio", 0.0),
            "sortino_ratio": self._get("Sortino Ratio", 0.0),
            "sqn": self._get("SQN", 0.0),
        }

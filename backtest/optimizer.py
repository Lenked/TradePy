"""
Optuna-based parameter optimization for TradePy strategies.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Optional

import optuna
import pandas as pd

from backtest.engine import BacktestEngine
from core.strategy.trend_following_strategy import TrendFollowingStrategy


@dataclass
class OptimizationResult:
    study: optuna.Study
    best_params: Dict[str, float]
    best_value: float
    best_metrics: Dict[str, float]


class StrategyOptimizer:
    """Optimize trend-following strategy parameters using Optuna."""

    def __init__(
        self,
        data: pd.DataFrame,
        initial_capital: float = 10000.0,
        commission: float = 0.0,
        symbol: str = "BACKTEST",
        min_trades: int = 3,
    ):
        self.data = data
        self.symbol = symbol
        self.min_trades = int(min_trades)
        self.engine = BacktestEngine(initial_capital=initial_capital, commission=commission)

    def _score_from_stats(self, stats) -> float:
        def _finite(value, default=0.0):
            try:
                v = float(value)
                if math.isfinite(v):
                    return v
            except Exception:
                pass
            return float(default)

        total_return = _finite(stats.get("Return [%]", 0.0), 0.0)
        max_drawdown = abs(_finite(stats.get("Max. Drawdown [%]", 0.0), 0.0))
        sharpe = _finite(stats.get("Sharpe Ratio", 0.0), 0.0)
        trades = _finite(stats.get("# Trades", 0.0), 0.0)
        win_rate = _finite(stats.get("Win Rate [%]", 0.0), 0.0)

        if trades < self.min_trades:
            return -1e6 + trades

        # Return-centric objective, penalize deep drawdowns, reward consistency.
        return total_return - 0.5 * max_drawdown + 5.0 * sharpe + 0.05 * win_rate

    def _build_strategy(self, trial: optuna.Trial) -> TrendFollowingStrategy:
        use_arch = trial.suggest_categorical("use_arch_volatility_filter", [False, True])
        max_cond_vol = trial.suggest_float("max_conditional_volatility", 0.005, 0.05)
        return TrendFollowingStrategy(
            ema_short_period=trial.suggest_int("ema_short_period", 20, 80),
            ema_long_period=trial.suggest_int("ema_long_period", 120, 320),
            rsi_period=trial.suggest_int("rsi_period", 8, 24),
            atr_period=trial.suggest_int("atr_period", 7, 28),
            sl_atr_multiplier=trial.suggest_float("sl_atr_multiplier", 1.0, 3.5),
            tp_atr_multiplier=trial.suggest_float("tp_atr_multiplier", 1.2, 5.0),
            use_pandas_ta=True,
            use_adx_filter=True,
            adx_period=trial.suggest_int("adx_period", 7, 28),
            adx_threshold=trial.suggest_float("adx_threshold", 12.0, 35.0),
            use_arch_volatility_filter=use_arch,
            arch_lookback=trial.suggest_int("arch_lookback", 120, 420),
            max_conditional_volatility=max_cond_vol if use_arch else None,
        )

    def optimize(
        self,
        n_trials: int = 50,
        timeout: Optional[int] = None,
        study_name: str = "tradepy_optuna_study",
    ) -> OptimizationResult:
        def objective(trial: optuna.Trial) -> float:
            try:
                strategy = self._build_strategy(trial)
                result = self.engine.run_backtest(strategy=strategy, data=self.data, symbol=self.symbol)
                score = self._score_from_stats(result.stats)
                return score if math.isfinite(score) else -1e6
            except Exception:
                return -1e6

        study = optuna.create_study(direction="maximize", study_name=study_name)
        study.optimize(objective, n_trials=int(n_trials), timeout=timeout)

        best_strategy = TrendFollowingStrategy(
            **{k: v for k, v in study.best_params.items() if k in {
                "ema_short_period",
                "ema_long_period",
                "rsi_period",
                "atr_period",
                "sl_atr_multiplier",
                "tp_atr_multiplier",
                "adx_period",
                "adx_threshold",
                "use_arch_volatility_filter",
                "arch_lookback",
                "max_conditional_volatility",
            }},
            use_pandas_ta=True,
            use_adx_filter=True,
        )
        best_result = self.engine.run_backtest(strategy=best_strategy, data=self.data, symbol=self.symbol)

        best_metrics = {
            "return_pct": float(best_result.stats.get("Return [%]", 0.0)),
            "max_drawdown_pct": abs(float(best_result.stats.get("Max. Drawdown [%]", 0.0))),
            "sharpe_ratio": float(best_result.stats.get("Sharpe Ratio", 0.0) or 0.0),
            "win_rate_pct": float(best_result.stats.get("Win Rate [%]", 0.0) or 0.0),
            "trades": float(best_result.stats.get("# Trades", 0.0) or 0.0),
            "profit_factor": float(best_result.stats.get("Profit Factor", 0.0) or 0.0),
        }

        return OptimizationResult(
            study=study,
            best_params=study.best_params,
            best_value=float(study.best_value),
            best_metrics=best_metrics,
        )

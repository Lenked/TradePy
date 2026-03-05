from pathlib import Path

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.optimizer import StrategyOptimizer
from backtest.reports import BacktestReport
from core.strategy.trend_following_strategy import TrendFollowingStrategy


def _make_ohlc(rows: int = 320) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=rows, freq="min")
    base = 100 + np.sin(np.linspace(0, 18, rows)) * 1.8 + np.linspace(0, 6, rows)
    close = base + 0.2 * np.sin(np.linspace(0, 30, rows))
    open_ = close + 0.03
    high = np.maximum(open_, close) + 0.25
    low = np.minimum(open_, close) - 0.25
    vol = np.full(rows, 1000.0)
    return pd.DataFrame(
        {
            "time": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )


def test_backtest_engine_and_plotly_report(tmp_path):
    data = _make_ohlc()
    strategy = TrendFollowingStrategy(use_arch_volatility_filter=False)
    engine = BacktestEngine(initial_capital=10000.0, commission=0.0)

    result = engine.run_backtest(strategy=strategy, data=data, symbol="TESTm")
    assert result.stats is not None
    assert "Return [%]" in result.stats.index
    assert isinstance(result.equity_curve, pd.DataFrame)
    assert not result.equity_curve.empty

    report = BacktestReport(result.as_dict())
    summary = report.generate_report()
    assert "total_return_pct" in summary

    out_html = tmp_path / "backtest_report.html"
    generated = report.plot_equity_curve(str(out_html))
    assert Path(generated).exists()


def test_optuna_optimizer_runs_small_study():
    data = _make_ohlc()
    optimizer = StrategyOptimizer(
        data=data,
        initial_capital=10000.0,
        commission=0.0,
        symbol="TESTm",
        min_trades=0,
    )
    result = optimizer.optimize(n_trials=2, timeout=120, study_name="tradepy_test_study")

    assert isinstance(result.best_params, dict)
    assert result.best_params
    assert "ema_short_period" in result.best_params

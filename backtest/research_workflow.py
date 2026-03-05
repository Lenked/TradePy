"""
Research workflow:
- load OHLCV CSV
- optional Optuna optimization
- run backtest
- generate Plotly report
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Dict

import pandas as pd

from backtest.apply_best_params import apply_best_params_to_settings
from backtest.engine import BacktestEngine
from backtest.optimizer import StrategyOptimizer
from backtest.reports import BacktestReport
from config.config import load_config
from core.strategy.trend_following_strategy import TrendFollowingStrategy


def _strategy_from_config(strategy_cfg: Dict) -> TrendFollowingStrategy:
    return TrendFollowingStrategy(
        ema_short_period=int(strategy_cfg.get("ema_short_period", 50)),
        ema_long_period=int(strategy_cfg.get("ema_long_period", 200)),
        rsi_period=int(strategy_cfg.get("rsi_period", 14)),
        atr_period=int(strategy_cfg.get("atr_period", 14)),
        sl_atr_multiplier=float(strategy_cfg.get("sl_atr_multiplier", 2.0)),
        tp_atr_multiplier=float(strategy_cfg.get("tp_atr_multiplier", 3.0)),
        sl_tp_overrides_by_symbol=strategy_cfg.get("sl_tp_overrides_by_symbol", {}),
        use_pandas_ta=bool(strategy_cfg.get("use_pandas_ta", True)),
        use_adx_filter=bool(strategy_cfg.get("use_adx_filter", True)),
        adx_period=int(strategy_cfg.get("adx_period", 14)),
        adx_threshold=float(strategy_cfg.get("adx_threshold", 18.0)),
        use_arch_volatility_filter=bool(strategy_cfg.get("use_arch_volatility_filter", False)),
        arch_lookback=int(strategy_cfg.get("arch_lookback", 300)),
        max_conditional_volatility=(
            float(strategy_cfg.get("max_conditional_volatility"))
            if strategy_cfg.get("max_conditional_volatility") is not None
            else None
        ),
    )


def _strategy_from_optuna_params(base_cfg: Dict, best_params: Dict) -> TrendFollowingStrategy:
    cfg = dict(base_cfg)
    cfg.update(best_params)
    return _strategy_from_config(cfg)


def main():
    parser = argparse.ArgumentParser(description="TradePy research workflow")
    parser.add_argument("--csv", required=True, help="OHLCV CSV path")
    parser.add_argument("--symbol", default="BACKTEST", help="Symbol label in reports")
    parser.add_argument("--config", default="config/settings.yaml", help="TradePy config file")
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument("--optimize", action="store_true", help="Run Optuna before final backtest")
    parser.add_argument("--trials", type=int, default=30, help="Optuna trials")
    parser.add_argument("--timeout", type=int, default=None, help="Optuna timeout in seconds")
    parser.add_argument("--report-html", default="reports/backtest_report.html")
    parser.add_argument("--summary-json", default="reports/backtest_summary.json")
    parser.add_argument("--params-json", default="reports/best_params.json")
    parser.add_argument(
        "--apply-best-params",
        action="store_true",
        help="Apply best Optuna params to settings file",
    )
    parser.add_argument(
        "--optimized-settings-out",
        default="config/settings.optimized.yaml",
        help="Output settings path when applying params in non in-place mode",
    )
    parser.add_argument(
        "--update-settings-in-place",
        action="store_true",
        help="Update --config file directly instead of writing optimized settings file",
    )
    parser.add_argument(
        "--no-settings-backup",
        action="store_true",
        help="Disable .bak creation when --update-settings-in-place is used",
    )
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        raise FileNotFoundError(f"CSV not found: {args.csv}")

    cfg = load_config(args.config) if args.config else {}
    strategy_cfg = cfg.get("strategy", {}) if isinstance(cfg, dict) else {}

    raw_df = pd.read_csv(args.csv)
    engine = BacktestEngine(initial_capital=args.initial_capital, commission=args.commission)

    strategy = _strategy_from_config(strategy_cfg)

    if args.optimize:
        optimizer = StrategyOptimizer(
            data=raw_df,
            initial_capital=args.initial_capital,
            commission=args.commission,
            symbol=args.symbol,
        )
        optimization = optimizer.optimize(n_trials=args.trials, timeout=args.timeout)
        strategy = _strategy_from_optuna_params(strategy_cfg, optimization.best_params)

        os.makedirs(os.path.dirname(args.params_json) or ".", exist_ok=True)
        with open(args.params_json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "best_params": optimization.best_params,
                    "best_value": optimization.best_value,
                    "best_metrics": optimization.best_metrics,
                },
                f,
                ensure_ascii=True,
                indent=2,
            )
        print(f"OPTUNA_DONE best_value={optimization.best_value:.4f} params={optimization.best_params}")

    if args.apply_best_params:
        output_settings = None if args.update_settings_in_place else args.optimized_settings_out
        target_settings, applied = apply_best_params_to_settings(
            params_json_path=args.params_json,
            settings_path=args.config,
            output_path=output_settings,
            in_place=args.update_settings_in_place,
            backup=not args.no_settings_backup,
        )
        print(f"SETTINGS_UPDATED target={target_settings} keys={sorted(applied.keys())}")

    result = engine.run_backtest(strategy=strategy, data=raw_df, symbol=args.symbol)
    report = BacktestReport(result.as_dict())
    summary = report.generate_report()
    html_path = report.plot_equity_curve(args.report_html)

    os.makedirs(os.path.dirname(args.summary_json) or ".", exist_ok=True)
    with open(args.summary_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=True, indent=2)

    trades_path = os.path.splitext(args.summary_json)[0] + "_trades.csv"
    equity_path = os.path.splitext(args.summary_json)[0] + "_equity.csv"
    if result.trades is not None and not result.trades.empty:
        result.trades.to_csv(trades_path, index=False)
    if result.equity_curve is not None and not result.equity_curve.empty:
        result.equity_curve.to_csv(equity_path)

    print(
        f"RESEARCH_DONE return={summary['total_return_pct']:.2f}% "
        f"max_dd={summary['max_drawdown_pct']:.2f}% "
        f"sharpe={summary['sharpe_ratio']:.2f} "
        f"trades={summary['trades']:.0f} "
        f"report={html_path}"
    )


if __name__ == "__main__":
    main()

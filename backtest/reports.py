"""
Backtesting reports for TradePy bot.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .metrics import BacktestMetrics


class BacktestReport:
    """Generate textual and interactive reports from backtest results."""

    def __init__(self, results: Any):
        self.results = results
        if isinstance(results, dict):
            self.stats = results.get("stats")
            self.equity_curve = results.get("equity_curve", pd.DataFrame())
            self.trades = results.get("trades", pd.DataFrame())
            self.strategy_name = results.get("strategy_name", "UnknownStrategy")
            self.symbol = results.get("symbol", "BACKTEST")
        else:
            self.stats = results
            self.equity_curve = pd.DataFrame()
            self.trades = pd.DataFrame()
            self.strategy_name = "UnknownStrategy"
            self.symbol = "BACKTEST"

        self.metrics = BacktestMetrics({"stats": self.stats})

    def generate_report(self) -> Dict[str, float]:
        """Return a normalized metrics summary."""
        summary = self.metrics.to_dict()
        summary["strategy_name"] = self.strategy_name
        summary["symbol"] = self.symbol
        return summary

    def plot_equity_curve(self, output_html: str = "reports/backtest_report.html") -> str:
        """
        Create an interactive Plotly HTML report with equity and drawdown.
        Returns the generated file path.
        """
        if self.equity_curve is None or self.equity_curve.empty:
            raise ValueError("No equity curve available to plot")

        os.makedirs(os.path.dirname(output_html) or ".", exist_ok=True)

        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.7, 0.3],
            subplot_titles=("Equity Curve", "Drawdown"),
        )

        fig.add_trace(
            go.Scatter(
                x=self.equity_curve.index,
                y=self.equity_curve["Equity"],
                mode="lines",
                name="Equity",
                line=dict(width=2),
            ),
            row=1,
            col=1,
        )

        if "DrawdownPct" in self.equity_curve.columns:
            fig.add_trace(
                go.Scatter(
                    x=self.equity_curve.index,
                    y=self.equity_curve["DrawdownPct"] * 100.0,
                    mode="lines",
                    name="Drawdown %",
                    line=dict(width=1.5, color="#d62728"),
                    fill="tozeroy",
                ),
                row=2,
                col=1,
            )

        if isinstance(self.trades, pd.DataFrame) and not self.trades.empty:
            if {"EntryTime", "EntryPrice"}.issubset(self.trades.columns):
                fig.add_trace(
                    go.Scatter(
                        x=self.trades["EntryTime"],
                        y=self.trades["EntryPrice"],
                        mode="markers",
                        name="Entries",
                        marker=dict(symbol="triangle-up", size=7, color="#2ca02c"),
                    ),
                    row=1,
                    col=1,
                )
            if {"ExitTime", "ExitPrice"}.issubset(self.trades.columns):
                fig.add_trace(
                    go.Scatter(
                        x=self.trades["ExitTime"],
                        y=self.trades["ExitPrice"],
                        mode="markers",
                        name="Exits",
                        marker=dict(symbol="triangle-down", size=7, color="#ff7f0e"),
                    ),
                    row=1,
                    col=1,
                )

        summary = self.generate_report()
        fig.update_layout(
            title=(
                f"{summary['strategy_name']} | {summary['symbol']} | "
                f"Return {summary['total_return_pct']:.2f}% | "
                f"MaxDD {summary['max_drawdown_pct']:.2f}% | "
                f"Sharpe {summary['sharpe_ratio']:.2f}"
            ),
            template="plotly_white",
            height=820,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig.update_yaxes(title_text="Equity", row=1, col=1)
        fig.update_yaxes(title_text="Drawdown %", row=2, col=1)
        fig.update_xaxes(title_text="Time", row=2, col=1)

        fig.write_html(output_html, include_plotlyjs="cdn")
        return output_html

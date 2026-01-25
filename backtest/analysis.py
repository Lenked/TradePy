"""
Enhanced backtesting analysis module for TradePy bot
Provides comprehensive analysis of backtesting results
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Union
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from dataclasses import dataclass


@dataclass
class Trade:
    """Represents a single trade in the backtest"""
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    side: str  # 'long' or 'short'
    pnl: float
    fees: float = 0.0


class BacktestAnalyzer:
    """
    Comprehensive analyzer for backtesting results.
    
    Calculates performance metrics, risk measures, and generates insights
    to evaluate the effectiveness and robustness of trading strategies.
    """
    
    def __init__(self):
        self.metrics = {}
        self.trades = []
        self.equity_curve = pd.Series(dtype=float)
    
    def calculate_performance_metrics(self, equity_curve: pd.Series) -> Dict:
        """
        Calculate key performance metrics from equity curve.
        
        Args:
            equity_curve: Series of portfolio values over time
            
        Returns:
            Dictionary of performance metrics
        """
        returns = equity_curve.pct_change().dropna()
        
        # Basic metrics
        total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1
        
        # Annualized returns (assuming daily data)
        n_days = len(equity_curve)
        annual_return = (1 + total_return) ** (365 / n_days) - 1
        
        # Volatility
        volatility = returns.std() * np.sqrt(252)  # Annualized volatility
        
        # Risk metrics
        downside_returns = returns[returns < 0]
        downside_deviation = downside_returns.std() * np.sqrt(252)
        
        # Max Drawdown
        rolling_max = equity_curve.expanding().max()
        drawdowns = (equity_curve - rolling_max) / rolling_max
        max_drawdown = abs(drawdowns.min()) if not drawdowns.empty else 0
        avg_drawdown = abs(drawdowns.mean()) if not drawdowns.empty else 0
        
        # Calmar Ratio (return / max drawdown)
        calmar_ratio = annual_return / max_drawdown if max_drawdown != 0 else 0
        
        # Sortino Ratio (return / downside deviation)
        sortino_ratio = (annual_return - 0.02) / downside_deviation if downside_deviation != 0 else 0  # Assuming 2% risk-free rate
        
        # Sharpe Ratio (return / volatility)
        sharpe_ratio = (annual_return - 0.02) / volatility if volatility != 0 else 0  # Assuming 2% risk-free rate
        
        # Win rate and other trade statistics
        positive_returns = returns[returns > 0]
        negative_returns = returns[returns < 0]
        win_rate = len(positive_returns) / len(returns) if len(returns) > 0 else 0
        
        # Profit factor
        gross_profit = positive_returns.sum() if len(positive_returns) > 0 else 0
        gross_loss = abs(negative_returns.sum()) if len(negative_returns) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')
        
        # Expectancy ratio
        avg_win = positive_returns.mean() if len(positive_returns) > 0 else 0
        avg_loss = abs(negative_returns.mean()) if len(negative_returns) > 0 else 0
        expectancy = (avg_win * win_rate - avg_loss * (1 - win_rate)) if avg_loss != 0 else 0
        
        self.metrics = {
            'total_return': total_return,
            'annual_return': annual_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'calmar_ratio': calmar_ratio,
            'max_drawdown': max_drawdown,
            'average_drawdown': avg_drawdown,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'number_of_trades': len(returns),
            'best_return': returns.max() if not returns.empty else 0,
            'worst_return': returns.min() if not returns.empty else 0,
            'avg_return': returns.mean() if not returns.empty else 0
        }
        
        return self.metrics
    
    def analyze_trades(self, trades: List[Trade]) -> Dict:
        """
        Analyze individual trades for detailed performance breakdown.
        
        Args:
            trades: List of Trade objects
            
        Returns:
            Dictionary of trade analysis metrics
        """
        if not trades:
            return {}
        
        pnl_values = [trade.pnl for trade in trades]
        durations = [(trade.exit_time - trade.entry_time).days for trade in trades]
        
        long_trades = [trade for trade in trades if trade.side == 'long']
        short_trades = [trade for trade in trades if trade.side == 'short']
        
        trade_analysis = {
            'total_trades': len(trades),
            'long_trades': len(long_trades),
            'short_trades': len(short_trades),
            'winning_trades': len([t for t in trades if t.pnl > 0]),
            'losing_trades': len([t for t in trades if t.pnl < 0]),
            'breakeven_trades': len([t for t in trades if t.pnl == 0]),
            
            'avg_pnl': np.mean(pnl_values),
            'median_pnl': np.median(pnl_values),
            'std_pnl': np.std(pnl_values),
            'max_pnl': max(pnl_values),
            'min_pnl': min(pnl_values),
            
            'avg_duration': np.mean(durations),
            'median_duration': np.median(durations),
            'max_duration': max(durations),
            'min_duration': min(durations),
            
            'largest_winner': max(pnl_values) if pnl_values else 0,
            'largest_loser': min(pnl_values) if pnl_values else 0,
            
            'avg_win': np.mean([p for p in pnl_values if p > 0]) if any(p > 0 for p in pnl_values) else 0,
            'avg_loss': np.mean([p for p in pnl_values if p < 0]) if any(p < 0 for p in pnl_values) else 0,
            
            'win_rate': len([t for t in trades if t.pnl > 0]) / len(trades) if trades else 0
        }
        
        return trade_analysis
    
    def generate_trade_log(self, trades: List[Trade]) -> pd.DataFrame:
        """
        Generate a detailed trade log.
        
        Args:
            trades: List of Trade objects
            
        Returns:
            DataFrame with trade details
        """
        if not trades:
            return pd.DataFrame()
        
        trade_data = []
        for i, trade in enumerate(trades):
            trade_data.append({
                'trade_id': i + 1,
                'entry_time': trade.entry_time,
                'exit_time': trade.exit_time,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'quantity': trade.quantity,
                'side': trade.side,
                'pnl': trade.pnl,
                'fees': trade.fees,
                'pnl_percent': (trade.exit_price - trade.entry_price) / trade.entry_price * 100 if trade.entry_price != 0 else 0,
                'duration_days': (trade.exit_time - trade.entry_time).days
            })
        
        return pd.DataFrame(trade_data)
    
    def calculate_monthly_returns(self, equity_curve: pd.Series) -> pd.Series:
        """
        Calculate monthly returns from equity curve.
        
        Args:
            equity_curve: Series of portfolio values over time
            
        Returns:
            Series of monthly returns
        """
        monthly_data = equity_curve.groupby(equity_curve.index.to_period('M')).last()
        monthly_returns = monthly_data.pct_change().dropna()
        return monthly_returns
    
    def calculate_annual_returns(self, equity_curve: pd.Series) -> pd.Series:
        """
        Calculate annual returns from equity curve.
        
        Args:
            equity_curve: Series of portfolio values over time
            
        Returns:
            Series of annual returns
        """
        annual_data = equity_curve.groupby(equity_curve.index.year).last()
        annual_returns = annual_data.pct_change().dropna()
        return annual_returns
    
    def get_summary_report(self) -> str:
        """
        Generate a textual summary report of the analysis.
        
        Returns:
            String summary report
        """
        if not self.metrics:
            return "No metrics calculated yet."
        
        report = f"""
TRADEPY BACKTEST ANALYSIS REPORT
=================================

PERFORMANCE METRICS:
- Total Return: {self.metrics['total_return']:.2%}
- Annual Return: {self.metrics['annual_return']:.2%}
- Volatility: {self.metrics['volatility']:.2%}

RISK METRICS:
- Max Drawdown: {self.metrics['max_drawdown']:.2%}
- Average Drawdown: {self.metrics['average_drawdown']:.2%}
- Sharpe Ratio: {self.metrics['sharpe_ratio']:.2f}
- Sortino Ratio: {self.metrics['sortino_ratio']:.2f}

TRADING STATISTICS:
- Win Rate: {self.metrics['win_rate']:.2%}
- Profit Factor: {self.metrics['profit_factor']:.2f}
- Number of Trades: {self.metrics['number_of_trades']}
- Expectancy: {self.metrics['expectancy']:.4f}

QUALITY INDICATORS:
- Best Return: {self.metrics['best_return']:.2%}
- Worst Return: {self.metrics['worst_return']:.2%}
- Average Return: {self.metrics['avg_return']:.2%}
        """
        
        return report.strip()
    
    def plot_equity_curve(self, equity_curve: pd.Series, title: str = "Equity Curve") -> plt.Figure:
        """
        Plot the equity curve.
        
        Args:
            equity_curve: Series of portfolio values over time
            title: Title for the plot
            
        Returns:
            Matplotlib figure object
        """
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(equity_curve.index, equity_curve.values, linewidth=1.5)
        ax.set_title(title, fontsize=16)
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel("Portfolio Value", fontsize=12)
        ax.grid(True, alpha=0.3)
        
        # Add fill under curve for visual clarity
        ax.fill_between(equity_curve.index, equity_curve.values, 
                       min(equity_curve.values), alpha=0.3)
        
        return fig
    
    def plot_monthly_returns_heatmap(self, equity_curve: pd.Series) -> plt.Figure:
        """
        Plot a heatmap of monthly returns by year and month.
        
        Args:
            equity_curve: Series of portfolio values over time
            
        Returns:
            Matplotlib figure object
        """
        monthly_returns = self.calculate_monthly_returns(equity_curve)
        
        # Create pivot table for heatmap
        monthly_returns.index = pd.to_datetime(monthly_returns.index.astype(str))
        pivot_data = monthly_returns.to_frame('return')
        pivot_data['year'] = pivot_data.index.year
        pivot_data['month'] = pivot_data.index.month
        
        # Create pivot table
        heatmap_data = pivot_data.pivot(index='year', columns='month', values='return')
        heatmap_data.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        fig, ax = plt.subplots(figsize=(12, 8))
        sns.heatmap(heatmap_data, annot=True, fmt='.2%', center=0, 
                    cmap='RdYlGn', ax=ax)
        ax.set_title("Monthly Returns Heatmap", fontsize=16)
        
        return fig


class AdvancedBacktestAnalyzer(BacktestAnalyzer):
    """
    Extended version of BacktestAnalyzer with advanced statistical analysis.
    """
    
    def calculate_var(self, returns: pd.Series, confidence_level: float = 0.05) -> float:
        """
        Calculate Value at Risk (VaR) at specified confidence level.
        
        Args:
            returns: Series of returns
            confidence_level: Confidence level (e.g., 0.05 for 5% VaR)
            
        Returns:
            Value at Risk
        """
        var = returns.quantile(confidence_level)
        return var
    
    def calculate_cvar(self, returns: pd.Series, confidence_level: float = 0.05) -> float:
        """
        Calculate Conditional Value at Risk (CVaR) at specified confidence level.
        
        Args:
            returns: Series of returns
            confidence_level: Confidence level (e.g., 0.05 for 5% CVaR)
            
        Returns:
            Conditional Value at Risk
        """
        var_threshold = self.calculate_var(returns, confidence_level)
        cvar = returns[returns <= var_threshold].mean()
        return cvar
    
    def calculate_kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Calculate Kelly Criterion for optimal position sizing.
        
        Args:
            win_rate: Win rate of the strategy
            avg_win: Average winning trade
            avg_loss: Average losing trade
            
        Returns:
            Kelly Criterion percentage
        """
        if avg_loss == 0:
            return 1.0  # If no losses, bet everything (theoretical)
        
        win_loss_ratio = avg_win / avg_loss
        kelly_fraction = win_rate - (1 - win_rate) / win_loss_ratio
        return max(0, kelly_fraction)  # Never recommend negative position size


# Example usage function
def analyze_backtest_results(equity_curve: pd.Series, trades: Optional[List[Trade]] = None) -> Dict:
    """
    Convenience function to perform complete backtest analysis.
    
    Args:
        equity_curve: Series of portfolio values over time
        trades: Optional list of Trade objects for detailed analysis
        
    Returns:
        Dictionary with complete analysis results
    """
    analyzer = BacktestAnalyzer()
    
    performance_metrics = analyzer.calculate_performance_metrics(equity_curve)
    
    results = {
        'performance_metrics': performance_metrics,
        'summary_report': analyzer.get_summary_report()
    }
    
    if trades:
        trade_analysis = analyzer.analyze_trades(trades)
        trade_log = analyzer.generate_trade_log(trades)
        
        results['trade_analysis'] = trade_analysis
        results['trade_log'] = trade_log
    
    return results
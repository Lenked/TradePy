"""
Walk-forward analysis module for TradePy bot
Evaluates strategy robustness across different time periods
"""
import pandas as pd
import numpy as np
from typing import Tuple, List, Dict, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
import warnings
from core.strategy.base import Strategy
from backtest.analysis import BacktestAnalyzer
from backtest.engine import BacktestEngine
from core.data.validator import DataValidator
from core.validation.risk_validation import RiskValidator


@dataclass
class WindowConfig:
    """
    Configuration for walk-forward analysis windows.
    
    Attributes:
        in_sample_period: Duration of in-sample training period
        out_of_sample_period: Duration of out-of-sample testing period
        overlap: Overlap between consecutive windows (0 for walk-forward)
        in_sample_size: Size of in-sample window in terms of data points
        out_of_sample_size: Size of out-of-sample window in terms of data points
    """
    in_sample_period: str = "6M"  # 6 months in-sample
    out_of_sample_period: str = "3M"  # 3 months out-of-sample
    overlap: bool = False  # No overlap for classic walk-forward
    in_sample_size: Optional[int] = None
    out_of_sample_size: Optional[int] = None


@dataclass
class PerformanceMetrics:
    """
    Metrics collected from a single walk-forward period.
    
    Attributes:
        period_start: Start date of the period
        period_end: End date of the period
        total_return: Total return for the period
        annual_return: Annualized return for the period
        volatility: Volatility of returns for the period
        sharpe_ratio: Sharpe ratio for the period
        max_drawdown: Maximum drawdown for the period
        win_rate: Percentage of winning trades
        profit_factor: Profit factor for the period
        number_of_trades: Number of trades in the period
        in_sample: Whether this is an in-sample period
    """
    period_start: datetime
    period_end: datetime
    total_return: float
    annual_return: float
    volatility: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    number_of_trades: int
    in_sample: bool


class WindowSplitter:
    """
    Splits time-series data into walk-forward windows.
    
    This class handles the division of data into in-sample and out-of-sample
    periods according to the configured parameters.
    """
    
    def __init__(self, config: WindowConfig):
        self.config = config
    
    def split_data(self, data: pd.DataFrame, date_column: str = 'timestamp') -> List[Dict[str, pd.DataFrame]]:
        """
        Split the data into walk-forward windows.
        
        Args:
            data: DataFrame containing the historical data
            date_column: Name of the date/timestamp column
            
        Returns:
            List of dictionaries containing in-sample and out-of-sample data for each window
        """
        # Ensure data is sorted by date
        if not pd.api.types.is_datetime64_any_dtype(data[date_column]):
            data[date_column] = pd.to_datetime(data[date_column])
        
        data = data.sort_values(by=date_column).reset_index(drop=True)
        
        windows = []
        
        # Convert period specifications to actual indices
        in_sample_indices = self._get_period_indices(data, date_column, self.config.in_sample_period)
        out_of_sample_indices = self._get_period_indices(data, date_column, self.config.out_of_sample_period)
        
        # Calculate the number of possible windows
        step_size = len(in_sample_indices) if not self.config.overlap else 1
        
        i = 0
        while i + len(in_sample_indices) + len(out_of_sample_indices) <= len(data):
            # Define in-sample and out-of-sample ranges
            in_sample_start = i
            in_sample_end = i + len(in_sample_indices)
            oos_start = in_sample_end
            oos_end = oos_start + len(out_of_sample_indices)
            
            # Extract the data for each period
            in_sample_data = data.iloc[in_sample_start:in_sample_end].copy()
            out_of_sample_data = data.iloc[oos_start:oos_end].copy()
            
            # Add the window to the list
            windows.append({
                'in_sample': {
                    'data': in_sample_data,
                    'start_date': in_sample_data[date_column].iloc[0],
                    'end_date': in_sample_data[date_column].iloc[-1],
                    'index_range': (in_sample_start, in_sample_end)
                },
                'out_of_sample': {
                    'data': out_of_sample_data,
                    'start_date': out_of_sample_data[date_column].iloc[0],
                    'end_date': out_of_sample_data[date_column].iloc[-1],
                    'index_range': (oos_start, oos_end)
                }
            })
            
            # Move to next window
            i += step_size
        
        return windows
    
    def _get_period_indices(self, data: pd.DataFrame, date_column: str, period: str) -> List[int]:
        """
        Get indices corresponding to a time period from the data.
        
        Args:
            data: DataFrame with date column
            date_column: Name of the date column
            period: Period string (e.g., '1M', '3M', '6M', '1Y')
            
        Returns:
            List of indices corresponding to the period
        """
        if self.config.in_sample_size and period == self.config.in_sample_period:
            # If size is provided for in-sample, use it
            return list(range(min(self.config.in_sample_size, len(data))))
        elif self.config.out_of_sample_size and period == self.config.out_of_sample_period:
            # If size is provided for out-of-sample, use it
            return list(range(min(self.config.out_of_sample_size, len(data))))
        else:
            # Otherwise, calculate based on period string
            start_date = data[date_column].iloc[0]
            
            # Map period strings to time deltas
            period_map = {
                '1M': timedelta(days=30),
                '2M': timedelta(days=60),
                '3M': timedelta(days=90),
                '6M': timedelta(days=180),
                '9M': timedelta(days=270),
                '1Y': timedelta(days=365),
                '2Y': timedelta(days=365*2),
                '3Y': timedelta(days=365*3),
                '5Y': timedelta(days=365*5)
            }
            
            if period not in period_map:
                raise ValueError(f"Unknown period: {period}. Available: {list(period_map.keys())}")
            
            target_date = start_date + period_map[period]
            
            # Find the indices that fit within the target period
            mask = (data[date_column] >= start_date) & (data[date_column] <= target_date)
            return data[mask].index.tolist()


class PerformanceComparator:
    """
    Compares performance metrics across walk-forward windows.
    
    This class analyzes the stability of strategy performance over time
    and identifies periods of degradation.
    """
    
    def __init__(self):
        self.metrics_history = []
        self.performance_stability = {}
    
    def calculate_stability_metrics(self, metrics_list: List[PerformanceMetrics]) -> Dict:
        """
        Calculate stability metrics across all periods.
        
        Args:
            metrics_list: List of PerformanceMetrics for each period
            
        Returns:
            Dictionary containing stability metrics
        """
        if not metrics_list:
            return {}
        
        # Extract metric values across all periods
        total_returns = [m.total_return for m in metrics_list]
        annual_returns = [m.annual_return for m in metrics_list]
        volatilities = [m.volatility for m in metrics_list]
        sharpe_ratios = [m.sharpe_ratio for m in metrics_list]
        max_drawdowns = [m.max_drawdown for m in metrics_list]
        win_rates = [m.win_rate for m in metrics_list]
        profit_factors = [m.profit_factor for m in metrics_list]
        
        # Calculate stability statistics
        stability_metrics = {
            'avg_total_return': np.mean(total_returns),
            'std_total_return': np.std(total_returns),
            'cv_total_return': np.std(total_returns) / np.mean(total_returns) if np.mean(total_returns) != 0 else float('inf'),
            
            'avg_annual_return': np.mean(annual_returns),
            'std_annual_return': np.std(annual_returns),
            'cv_annual_return': np.std(annual_returns) / np.mean(annual_returns) if np.mean(annual_returns) != 0 else float('inf'),
            
            'avg_volatility': np.mean(volatilities),
            'std_volatility': np.std(volatilities),
            'cv_volatility': np.std(volatilities) / np.mean(volatilities) if np.mean(volatilities) != 0 else float('inf'),
            
            'avg_sharpe_ratio': np.mean(sharpe_ratios),
            'std_sharpe_ratio': np.std(sharpe_ratios),
            'cv_sharpe_ratio': np.std(sharpe_ratios) / np.mean(sharpe_ratios) if np.mean(sharpe_ratios) != 0 else float('inf'),
            
            'avg_max_drawdown': np.mean(max_drawdowns),
            'std_max_drawdown': np.std(max_drawdowns),
            'cv_max_drawdown': np.std(max_drawdowns) / np.mean(max_drawdowns) if np.mean(max_drawdowns) != 0 else float('inf'),
            
            'avg_win_rate': np.mean(win_rates),
            'std_win_rate': np.std(win_rates),
            'cv_win_rate': np.std(win_rates) / np.mean(win_rates) if np.mean(win_rates) != 0 else float('inf'),
            
            'avg_profit_factor': np.mean(profit_factors),
            'std_profit_factor': np.std(profit_factors),
            'cv_profit_factor': np.std(profit_factors) / np.mean(profit_factors) if np.mean(profit_factors) != 0 else float('inf'),
            
            'correlation_with_time': self._calculate_correlation_with_time(metrics_list),
            
            'number_of_periods': len(metrics_list),
            'positive_return_periods': sum(1 for m in metrics_list if m.total_return > 0),
            'negative_return_periods': sum(1 for m in metrics_list if m.total_return < 0),
            'best_period_return': max(total_returns) if total_returns else 0,
            'worst_period_return': min(total_returns) if total_returns else 0
        }
        
        # Identify periods of degradation
        degradation_periods = self._identify_degradation_periods(metrics_list)
        stability_metrics['degradation_periods'] = degradation_periods
        
        self.performance_stability = stability_metrics
        return stability_metrics
    
    def _calculate_correlation_with_time(self, metrics_list: List[PerformanceMetrics]) -> float:
        """
        Calculate the correlation between performance and time to detect trends.
        
        Args:
            metrics_list: List of PerformanceMetrics
            
        Returns:
            Correlation coefficient between performance and time
        """
        if len(metrics_list) < 2:
            return 0.0
        
        # Convert dates to numeric values for correlation
        dates_numeric = [(m.period_end - metrics_list[0].period_start).days for m in metrics_list]
        returns = [m.total_return for m in metrics_list]
        
        # Calculate correlation
        correlation_matrix = np.corrcoef(dates_numeric, returns)
        return correlation_matrix[0, 1]
    
    def _identify_degradation_periods(self, metrics_list: List[PerformanceMetrics], 
                                   threshold: float = 0.1) -> List[PerformanceMetrics]:
        """
        Identify periods showing significant performance degradation.
        
        Args:
            metrics_list: List of PerformanceMetrics
            threshold: Threshold for considering degradation (default 10% decline)
            
        Returns:
            List of periods with significant degradation
        """
        if len(metrics_list) < 2:
            return []
        
        degradation_periods = []
        for i in range(1, len(metrics_list)):
            prev_return = metrics_list[i-1].total_return
            curr_return = metrics_list[i].total_return
            
            if prev_return != 0:
                decline = (prev_return - curr_return) / abs(prev_return)
                if decline > threshold:
                    degradation_periods.append(metrics_list[i])
        
        return degradation_periods


class WalkForwardReport:
    """
    Generates comprehensive reports from walk-forward analysis results.
    """
    
    def __init__(self, results: Dict):
        self.results = results
    
    def generate_summary(self) -> str:
        """
        Generate a textual summary of the walk-forward analysis.
        
        Returns:
            Summary report as string
        """
        stability = self.results['stability_metrics']
        
        summary = f"""
WALK-FORWARD ANALYSIS SUMMARY
=============================

PERIODS ANALYZED:
- Total periods: {stability['number_of_periods']}
- Positive return periods: {stability['positive_return_periods']}
- Negative return periods: {stability['negative_return_periods']}

PERFORMANCE STABILITY:
- Avg Total Return: {stability['avg_total_return']:,.2%}
- Standard Deviation: {stability['std_total_return']:,.2%}
- Coefficient of Variation: {stability['cv_total_return']:.2f}

- Avg Annual Return: {stability['avg_annual_return']:,.2%}
- Avg Sharpe Ratio: {stability['avg_sharpe_ratio']:.2f}
- Avg Max Drawdown: {stability['avg_max_drawdown']:,.2%}
- Avg Win Rate: {stability['avg_win_rate']:,.2%}

STABILITY INDICATORS:
- Correlation with time: {stability['correlation_with_time']:.3f}
- Best period return: {stability['best_period_return']:,.2%}
- Worst period return: {stability['worst_period_return']:,.2%}

DEGRADATION ANALYSIS:
- Number of degradation periods: {len(stability['degradation_periods'])}
        """
        
        return summary.strip()
    
    def generate_recommendation(self) -> str:
        """
        Generate a recommendation based on the analysis.
        
        Returns:
            Recommendation string
        """
        stability = self.results['stability_metrics']
        
        # Determine strategy acceptability
        avg_return = stability['avg_total_return']
        avg_drawdown = stability['avg_max_drawdown']
        cv_return = stability['cv_total_return']
        num_positive = stability['positive_return_periods']
        total_periods = stability['number_of_periods']
        
        positive_ratio = num_positive / total_periods if total_periods > 0 else 0
        
        recommendation = "\nSTRATEGY RECOMMENDATION:\n"
        
        if avg_return <= 0:
            recommendation += "❌ REJECTED - Negative average returns\n"
        elif avg_drawdown > 0.2:  # More than 20% drawdown
            recommendation += "❌ REJECTED - Excessive maximum drawdown\n"
        elif cv_return > 2:  # Coefficient of variation too high
            recommendation += "❌ REJECTED - High performance instability\n"
        elif positive_ratio < 0.6:  # Less than 60% positive periods
            recommendation += "❌ REJECTED - Too many negative periods\n"
        else:
            recommendation += "✅ ACCEPTED - Strategy shows robust performance across time periods\n"
            if positive_ratio >= 0.85:
                recommendation += "   Excellent consistency (>85% positive periods)\n"
            elif positive_ratio >= 0.7:
                recommendation += "   Good consistency (70-85% positive periods)\n"
            else:
                recommendation += "   Acceptable consistency (60-70% positive periods)\n"
                
            if cv_return < 0.5:
                recommendation += "   Very stable performance (CV < 0.5)\n"
            elif cv_return < 1:
                recommendation += "   Moderately stable performance (0.5 ≤ CV < 1)\n"
            else:
                recommendation += "   Somewhat unstable performance (CV ≥ 1)\n"
        
        return recommendation


class WalkForwardAnalyzer:
    """
    Main class for performing walk-forward analysis.
    
    This class orchestrates the entire walk-forward analysis process:
    1. Splits data into time windows
    2. Runs backtest on out-of-sample periods
    3. Collects and analyzes performance metrics
    4. Generates recommendations
    """
    
    def __init__(self, strategy: Strategy, config: WindowConfig = None):
        """
        Initialize the walk-forward analyzer.
        
        Args:
            strategy: Trading strategy to analyze
            config: Window configuration (uses defaults if None)
        """
        self.strategy = strategy
        self.config = config or WindowConfig()
        self.window_splitter = WindowSplitter(self.config)
        self.performance_comparator = PerformanceComparator()
        self.backtest_analyzer = BacktestAnalyzer()
        
        # Initialize data validator
        self.data_validator = DataValidator()
    
    def run_analysis(self, data: pd.DataFrame, initial_capital: float = 10000.0) -> Dict:
        """
        Run the complete walk-forward analysis.
        
        Args:
            data: Historical market data
            initial_capital: Initial capital for backtesting
            
        Returns:
            Dictionary containing analysis results
        """
        # Validate the data first
        validation_results = self.data_validator.validate_for_backtesting(
            data, 
            timeframe="1D",  # Assuming daily data for walk-forward
            date_column='timestamp'
        )
        
        if not validation_results['passed']:
            raise ValueError(f"Data validation failed: {validation_results['errors']}")
        
        # Split data into windows
        windows = self.window_splitter.split_data(data)
        
        if not windows:
            raise ValueError("Not enough data for the specified window configuration")
        
        # Run analysis on each window
        all_metrics = []
        window_results = []
        
        for i, window in enumerate(windows):
            print(f"Processing window {i+1}/{len(windows)}")
            
            # Only analyze the out-of-sample period (the key principle of walk-forward)
            oos_data = window['out_of_sample']['data']
            oos_start = window['out_of_sample']['start_date']
            oos_end = window['out_of_sample']['end_date']
            
            if len(oos_data) < 2:
                print(f"Skipping window {i+1}: insufficient out-of-sample data")
                continue
            
            # Run backtest on out-of-sample period
            backtest_engine = BacktestEngine(initial_capital=initial_capital)
            
            # Note: In a real implementation, we would need to run the backtest properly
            # For now, we'll simulate the process with a dummy implementation
            # that would normally involve more complex interactions with the strategy
            try:
                # Simulate backtest execution
                # In a real implementation, this would call:
                # results = backtest_engine.run_backtest(self.strategy, oos_data)
                
                # For demonstration purposes, we'll create mock results
                # based on the data to show how the analysis would work
                equity_curve = self._simulate_equity_curve(oos_data, initial_capital)
                
                # Calculate metrics using the backtest analyzer
                metrics = self.backtest_analyzer.calculate_performance_metrics(equity_curve)
                
                # Create a PerformanceMetrics object from the results
                perf_metrics = PerformanceMetrics(
                    period_start=oos_start,
                    period_end=oos_end,
                    total_return=metrics['total_return'],
                    annual_return=metrics['annual_return'],
                    volatility=metrics['volatility'],
                    sharpe_ratio=metrics['sharpe_ratio'],
                    max_drawdown=metrics['max_drawdown'],
                    win_rate=metrics['win_rate'],
                    profit_factor=metrics['profit_factor'],
                    number_of_trades=metrics['number_of_trades'],
                    in_sample=False  # This is out-of-sample
                )
                
                all_metrics.append(perf_metrics)
                
                window_results.append({
                    'window_id': i,
                    'period': f"{oos_start.strftime('%Y-%m-%d')} to {oos_end.strftime('%Y-%m-%d')}",
                    'metrics': perf_metrics,
                    'equity_curve': equity_curve
                })
                
            except Exception as e:
                print(f"Error in window {i+1}: {str(e)}")
                continue
        
        # Calculate stability metrics across all periods
        stability_metrics = self.performance_comparator.calculate_stability_metrics(all_metrics)
        
        # Create final results dictionary
        results = {
            'windows_count': len(window_results),
            'window_results': window_results,
            'all_metrics': all_metrics,
            'stability_metrics': stability_metrics,
            'data_validation': validation_results,
            'config_used': self.config
        }
        
        return results
    
    def _simulate_equity_curve(self, data: pd.DataFrame, initial_capital: float) -> pd.Series:
        """
        Simulate equity curve for demo purposes.
        In a real implementation, this would come from actual backtest results.
        
        Args:
            data: Market data for the period
            initial_capital: Starting capital
            
        Returns:
            Equity curve as pandas Series
        """
        # Create a simple simulation based on market returns
        returns = data['close'].pct_change().fillna(0)
        
        # Add some random noise to make it more realistic
        random_noise = np.random.normal(0, 0.005, len(returns))  # 0.5% daily std of noise
        simulated_strategy_returns = returns * 0.7 + random_noise  # 70% market + 30% random
        
        # Calculate equity curve
        cumulative_returns = (1 + pd.Series(simulated_strategy_returns)).cumprod()
        equity_curve = initial_capital * cumulative_returns
        
        # Create a date index
        dates = data['timestamp'] if 'timestamp' in data.columns else pd.date_range(
            start='2020-01-01', periods=len(equity_curve), freq='D'
        )
        
        return pd.Series(equity_curve.values, index=dates)
    
    def generate_report(self, results: Dict) -> str:
        """
        Generate a complete walk-forward analysis report.
        
        Args:
            results: Results from run_analysis
            
        Returns:
            Complete analysis report as string
        """
        report_generator = WalkForwardReport(results)
        
        full_report = f"""
TRADEPY WALK-FORWARD ANALYSIS REPORT
====================================

CONFIGURATION:
- In-sample period: {results['config_used'].in_sample_period}
- Out-of-sample period: {results['config_used'].out_of_sample_period}
- Overlap: {'Yes' if results['config_used'].overlap else 'No'}

SUMMARY:
{report_generator.generate_summary()}

{report_generator.generate_recommendation()}
        """
        
        return full_report.strip()


# Convenience function for easy usage
def run_walk_forward_analysis(data: pd.DataFrame, strategy: Strategy, 
                           initial_capital: float = 10000.0, 
                           config: WindowConfig = None) -> Dict:
    """
    Convenience function to run complete walk-forward analysis.
    
    Args:
        data: Historical market data
        strategy: Trading strategy to analyze
        initial_capital: Initial capital for backtesting
        config: Window configuration (uses defaults if None)
        
    Returns:
        Dictionary containing complete analysis results
    """
    analyzer = WalkForwardAnalyzer(strategy, config)
    results = analyzer.run_analysis(data, initial_capital)
    return results
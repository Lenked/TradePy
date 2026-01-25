"""
Benchmark module for TradePy bot
Implements benchmark strategies for performance comparison
"""
import pandas as pd
from typing import Tuple


class Benchmark:
    """
    Implements benchmark strategies for comparison with main strategies.
    
    Benchmarks implemented:
    - Buy and Hold
    - Random strategy
    - Simple moving average cross
    """
    
    def __init__(self):
        self.name = "Benchmark Strategies"
    
    def buy_and_hold(self, data: pd.DataFrame, initial_capital: float = 10000.0) -> pd.DataFrame:
        """
        Implements a buy and hold strategy.
        
        Args:
            data: DataFrame with 'close' prices
            initial_capital: Initial capital to invest
            
        Returns:
            pd.DataFrame: Portfolio value over time
        """
        if 'close' not in data.columns:
            raise ValueError("Data must contain 'close' column")
        
        # Calculate returns
        returns = data['close'].pct_change().fillna(0)
        
        # Calculate cumulative value
        portfolio_values = [initial_capital]
        for ret in returns[1:]:  # Skip first since it's 0
            new_value = portfolio_values[-1] * (1 + ret)
            portfolio_values.append(new_value)
        
        result = data[['close']].copy()
        result['portfolio_value'] = portfolio_values
        result['returns'] = returns
        result['cumulative_returns'] = (1 + returns).cumprod() - 1
        
        return result
    
    def random_strategy(self, data: pd.DataFrame, initial_capital: float = 10000.0) -> pd.DataFrame:
        """
        Implements a random strategy for comparison.
        
        Args:
            data: DataFrame with 'close' prices
            initial_capital: Initial capital for trading
            
        Returns:
            pd.DataFrame: Portfolio value over time
        """
        import random
        
        if 'close' not in data.columns:
            raise ValueError("Data must contain 'close' column")
        
        # Generate random signals (0: hold, 1: buy, -1: sell)
        random.seed(42)  # For reproducible results
        signals = [random.choice([0, 1, -1]) for _ in range(len(data))]
        
        # Calculate returns based on signals
        returns = data['close'].pct_change().fillna(0)
        strategy_returns = [r * s for r, s in zip(returns, signals)]
        
        # Calculate cumulative value
        portfolio_values = [initial_capital]
        for ret in strategy_returns[1:]:  # Skip first since it's 0
            new_value = portfolio_values[-1] * (1 + ret)
            portfolio_values.append(new_value)
        
        result = data[['close']].copy()
        result['portfolio_value'] = portfolio_values
        result['returns'] = strategy_returns
        result['signals'] = signals
        result['cumulative_returns'] = (1 + pd.Series(strategy_returns)).cumprod() - 1
        
        return result
    
    def simple_ma_crossover(self, data: pd.DataFrame, short_window: int = 20, 
                           long_window: int = 50, initial_capital: float = 10000.0) -> pd.DataFrame:
        """
        Implements a simple moving average crossover strategy.
        
        Args:
            data: DataFrame with 'close' prices
            short_window: Short window for MA
            long_window: Long window for MA
            initial_capital: Initial capital for trading
            
        Returns:
            pd.DataFrame: Portfolio value over time
        """
        if 'close' not in data.columns:
            raise ValueError("Data must contain 'close' column")
        
        if len(data) < long_window:
            raise ValueError(f"Not enough data for windows {short_window}, {long_window}")
        
        # Calculate moving averages
        data['short_ma'] = data['close'].rolling(window=short_window).mean()
        data['long_ma'] = data['close'].rolling(window=long_window).mean()
        
        # Generate signals
        signals = []
        position = 0  # 0: no position, 1: long, -1: short
        for i in range(long_window, len(data)):
            if data['short_ma'].iloc[i] > data['long_ma'].iloc[i] and position <= 0:
                # Golden cross - buy signal
                position = 1
                signals.append(1)
            elif data['short_ma'].iloc[i] < data['long_ma'].iloc[i] and position >= 0:
                # Death cross - sell signal
                position = -1
                signals.append(-1)
            else:
                # Hold signal
                signals.append(0)
        
        # Fill with zeros for the initial period
        signals = [0] * long_window + signals
        
        # Calculate returns based on signals
        returns = data['close'].pct_change().fillna(0)
        strategy_returns = [r * s for r, s in zip(returns, signals)]
        
        # Calculate cumulative value
        portfolio_values = [initial_capital]
        for ret in strategy_returns[1:]:
            new_value = portfolio_values[-1] * (1 + ret)
            portfolio_values.append(new_value)
        
        result = data[['close', 'short_ma', 'long_ma']].copy()
        result['portfolio_value'] = portfolio_values
        result['returns'] = strategy_returns
        result['signals'] = signals
        result['cumulative_returns'] = (1 + pd.Series(strategy_returns)).cumprod() - 1
        
        return result


class BenchmarkAnalyzer:
    """
    Analyzes and compares benchmark results.
    """
    
    def __init__(self):
        self.benchmark = Benchmark()
    
    def calculate_metrics(self, portfolio_series: pd.Series, initial_capital: float = 10000.0) -> dict:
        """
        Calculate performance metrics for a portfolio series.
        
        Args:
            portfolio_series: Series of portfolio values over time
            initial_capital: Initial capital invested
            
        Returns:
            dict: Performance metrics
        """
        returns = portfolio_series.pct_change().fillna(0)
        
        # Calculate metrics
        total_return = (portfolio_series.iloc[-1] / portfolio_series.iloc[0]) - 1
        annual_return = (portfolio_series.iloc[-1] / portfolio_series.iloc[0]) ** (252 / len(portfolio_series)) - 1  # Assuming daily data
        
        # Volatility (annualized)
        volatility = returns.std() * (252 ** 0.5)  # Assuming daily data
        
        # Sharpe ratio (assuming risk-free rate of 0.02)
        sharpe_ratio = (annual_return - 0.02) / volatility if volatility != 0 else 0
        
        # Max drawdown
        rolling_max = portfolio_series.expanding().max()
        drawdowns = (portfolio_series - rolling_max) / rolling_max
        max_drawdown = abs(drawdowns.min())
        
        # Win rate (positive returns)
        win_rate = (returns > 0).sum() / len(returns)
        
        # Profit factor (gains/losses ratio)
        gains = returns[returns > 0].sum()
        losses = abs(returns[returns < 0].sum())
        profit_factor = gains / losses if losses != 0 else float('inf')
        
        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'profit_factor': profit_factor
        }
    
    def compare_strategies(self, data: pd.DataFrame, initial_capital: float = 10000.0) -> dict:
        """
        Compare all benchmark strategies.
        
        Args:
            data: DataFrame with 'close' prices
            initial_capital: Initial capital for comparison
            
        Returns:
            dict: Comparison of all strategies
        """
        results = {}
        
        # Buy and Hold
        bh_result = self.benchmark.buy_and_hold(data, initial_capital)
        results['buy_and_hold'] = {
            'portfolio': bh_result,
            'metrics': self.calculate_metrics(bh_result['portfolio_value'], initial_capital)
        }
        
        # Random Strategy
        random_result = self.benchmark.random_strategy(data, initial_capital)
        results['random_strategy'] = {
            'portfolio': random_result,
            'metrics': self.calculate_metrics(random_result['portfolio_value'], initial_capital)
        }
        
        # Moving Average Crossover
        ma_result = self.benchmark.simple_ma_crossover(data, initial_capital=initial_capital)
        results['ma_crossover'] = {
            'portfolio': ma_result,
            'metrics': self.calculate_metrics(ma_result['portfolio_value'], initial_capital)
        }
        
        return results
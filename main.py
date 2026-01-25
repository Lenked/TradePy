"""
Main entry point for TradePy bot
"""
import argparse
from config.config import load_config
from core.strategy.trend_following import TrendFollowingStrategy
from core.exchange.broker import Broker
from core.risk.manager import RiskManager
from backtest.engine import BacktestEngine
from live.runner import LiveRunner


def main():
    parser = argparse.ArgumentParser(description='TradePy - AI Trading Bot')
    parser.add_argument('--mode', choices=['backtest', 'paper', 'live'], 
                        default='backtest', help='Operation mode')
    parser.add_argument('--config', default='config/settings.yaml', 
                        help='Configuration file path')
    
    args = parser.parse_args()
    config = load_config(args.config)
    
    # Initialize components
    strategy = TrendFollowingStrategy()
    exchange = Broker(config)
    risk_manager = RiskManager()
    
    if args.mode == 'backtest':
        engine = BacktestEngine(initial_capital=config.get('initial_capital', 10000))
        # Backtesting would be initiated here
        print("Running backtest...")
    elif args.mode in ['paper', 'live']:
        runner = LiveRunner(strategy, exchange, risk_manager)
        # Live trading would be initiated here
        print(f"Running in {args.mode} mode...")


if __name__ == "__main__":
    main()
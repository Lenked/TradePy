"""
Main entry point for TradePy bot
"""
import argparse
import logging as py_logging  # Import as py_logging to avoid confusion with our Logger
import os
from config.config import load_config
from core.strategy.trend_following import TrendFollowingStrategy
from core.exchange.broker import Broker
from core.risk.manager import RiskManager
from backtest.engine import BacktestEngine
from live.runner import LiveRunner
from utils.logger import get_logger


def main():
    parser = argparse.ArgumentParser(description='TradePy - AI Trading Bot')
    parser.add_argument('--mode', choices=['backtest', 'paper', 'live'], 
                        default='backtest', help='Operation mode')
    parser.add_argument('--config', default='config/settings.yaml', 
                        help='Configuration file path')
    
    args = parser.parse_args()
    config = load_config(args.config)
    
    # Set up logging based on environment
    log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_levels = {
        'DEBUG': py_logging.DEBUG,
        'INFO': py_logging.INFO,
        'WARNING': py_logging.WARNING,
        'ERROR': py_logging.ERROR,
        'CRITICAL': py_logging.CRITICAL
    }
    log_level = log_levels.get(log_level_str, py_logging.INFO)
    py_logging.basicConfig(level=log_level)
    
    # Initialize logger for main process
    main_logger = get_logger("Main")
    
    # Choose exchange based on config and dry_run settings
    trading_config = config.get('trading', {})
    use_mt5 = trading_config.get('use_mt5', False)
    
    # STARTUP CHECK - Display mode, exchange name, and login details for live mode
    if use_mt5:
        # Perform sanity check for live mode - ensure MT5 credentials are present
        mt5_login = os.getenv("MT5_LOGIN")
        mt5_password = os.getenv("MT5_PASSWORD")
        mt5_server = os.getenv("MT5_SERVER")
        
        if not all([mt5_login, mt5_password, mt5_server]):
            main_logger.error("Missing MT5 credentials. Please set MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER in your environment.")
            main_logger.error("Cannot proceed with LIVE_MT5 mode without credentials.")
            raise ValueError("Missing MT5 credentials in environment variables")
        
        mode = "LIVE_MT5"
        exchange_name = "MT5Executor"
        
        # Try to parse login for display (hide partial digits for security)
        try:
            login_display = str(mt5_login)[-4:].zfill(8)  # Show only last 4 digits
        except:
            login_display = "****"
            
        main_logger.info("="*60)
        main_logger.info(f"STARTUP CHECK PASSED")
        main_logger.info(f"Mode: {mode}")
        main_logger.info(f"Exchange: {exchange_name}")
        main_logger.info(f"Login: ***{login_display}")
        main_logger.info(f"Server: {mt5_server}")
        main_logger.info(f"Account Type: {'REAL' if 'real' in mt5_server.lower() else 'DEMO'}")
        main_logger.info("="*60)
        
        from core.execution.mt5_executor import MT5Executor
        exchange = MT5Executor()
    else:
        mode = "SIMULATION"
        exchange_name = "SimulatedBroker"
        
        main_logger.info("="*60)
        main_logger.info(f"STARTUP CHECK PASSED")
        main_logger.info(f"Mode: {mode}")
        main_logger.info(f"Exchange: {exchange_name}")
        main_logger.info("="*60)
        
        # Use broker simulator
        exchange = Broker(config)
    
    # Initialize components
    strategy = TrendFollowingStrategy()
    risk_manager = RiskManager()
    
    if args.mode == 'backtest':
        engine = BacktestEngine(initial_capital=config.get('initial_capital', 10000))
        # Backtesting would be initiated here
        print("Running backtest...")
    elif args.mode in ['paper', 'live']:
        runner = LiveRunner(strategy, exchange, risk_manager)
        # Live trading would be initiated here
        print(f"Running in {args.mode} mode...")
        if args.mode == 'live':
            runner.run()


if __name__ == "__main__":
    main()
"""
Main entry point for TradePy bot
"""
import argparse
import logging as py_logging  # Import as py_logging to avoid confusion with our Logger
import os
from dotenv import load_dotenv
from config.config import load_config
from core.strategy.trend_following_strategy import TrendFollowingStrategy
from core.exchange.broker import Broker
from core.risk.manager import RiskManager
from backtest.engine import BacktestEngine
from live.runner import LiveRunner
from utils.logger import get_logger

DOTENV_LOADED = load_dotenv()


def main():
    parser = argparse.ArgumentParser(description='TradePy - AI Trading Bot')
    parser.add_argument('--mode', choices=['backtest', 'paper', 'live'], 
                        default='backtest', help='Operation mode')
    parser.add_argument('--config', default='config/settings.yaml', 
                        help='Configuration file path')
    parser.add_argument('--i-accept-live-risk', action='store_true',
                        help='Acknowledge and allow REAL MT5 trading (required for live orders)')
    
    args = parser.parse_args()
    config = load_config(args.config) or {}
    
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
    dry_run = trading_config.get('dry_run', True)
    accept_live_risk = args.i_accept_live_risk

    def _detect_server_mode(server: str, dry_run_flag: bool) -> str:
        server_lower = (server or "").lower()
        if any(key in server_lower for key in ["demo", "trial", "practice"]):
            return "DEMO"
        if any(key in server_lower for key in ["real", "live"]):
            return "REAL"
        return "DEMO" if dry_run_flag else "REAL"
    
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

        if not dry_run and not accept_live_risk:
            main_logger.error("LIVE trading is blocked. You must pass --i-accept-live-risk to enable real MT5 orders.")
            raise ValueError("Live trading blocked without --i-accept-live-risk")

        server_mode = _detect_server_mode(mt5_server, dry_run)
        mode = f"MT5_{server_mode}"
        exchange_name = "MT5Executor"
        
        # Try to parse login for display (hide partial digits for security)
        try:
            login_display = str(mt5_login)[-4:]  # Show only last 4 digits
        except Exception:
            login_display = "****"
            
        main_logger.info("="*60)
        main_logger.info(f"STARTUP CHECK PASSED")
        main_logger.info(f"dotenv loaded: {'yes' if DOTENV_LOADED else 'no'}")
        main_logger.info(f"use_mt5: {use_mt5}")
        main_logger.info(f"dry_run: {dry_run}")
        main_logger.info(f"mode final: {mode}")
        main_logger.info(f"Exchange: {exchange_name}")
        main_logger.info(f"Login: ***{login_display}")
        main_logger.info(f"Server: {mt5_server}")
        if use_mt5 and not dry_run and accept_live_risk:
            main_logger.info("TRADING ENABLED")
        main_logger.info("="*60)
        
        from core.execution.mt5_executor import MT5Executor
        exchange = MT5Executor(dry_run=dry_run)
    else:
        mode = "SIMULATION"
        exchange_name = "SimulatedBroker"
        
        main_logger.info("="*60)
        main_logger.info(f"STARTUP CHECK PASSED")
        main_logger.info(f"dotenv loaded: {'yes' if DOTENV_LOADED else 'no'}")
        main_logger.info(f"use_mt5: {use_mt5}")
        main_logger.info(f"dry_run: {dry_run}")
        main_logger.info(f"mode final: {mode}")
        main_logger.info(f"Exchange: {exchange_name}")
        main_logger.info("="*60)
        
        # Use broker simulator
        exchange = Broker(config)
    
    # Initialize components
    strategy_cfg = config.get("strategy", {}) if isinstance(config, dict) else {}
    strategy = TrendFollowingStrategy(
        ema_short_period=int(strategy_cfg.get("ema_short_period", 50)),
        ema_long_period=int(strategy_cfg.get("ema_long_period", 200)),
        rsi_period=int(strategy_cfg.get("rsi_period", 14)),
        atr_period=int(strategy_cfg.get("atr_period", 14)),
        sl_atr_multiplier=float(strategy_cfg.get("sl_atr_multiplier", 2.0)),
        tp_atr_multiplier=float(strategy_cfg.get("tp_atr_multiplier", 3.0)),
        sl_tp_overrides_by_symbol=strategy_cfg.get("sl_tp_overrides_by_symbol", {}),
    )
    risk_manager = RiskManager(config.get('risk', {}))
    
    if args.mode == 'backtest':
        engine = BacktestEngine(initial_capital=config.get('initial_capital', 10000))
        # Backtesting would be initiated here
        print("Running backtest...")
    elif args.mode in ['paper', 'live']:
        timeframe = trading_config.get('timeframe')
        timeframes_config = trading_config.get('timeframes', None)
        preferred_timeframe_cfg = trading_config.get('preferred_timeframe', None)
        poll_seconds = trading_config.get('poll_seconds', 5)

        def _as_list(value):
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return list(value)
            return [value]

        def _normalize_timeframe_key(value):
            if value is None:
                return None
            if isinstance(value, int):
                mapping = {
                    1: "M1",
                    5: "M5",
                    15: "M15",
                    30: "M30",
                    60: "H1",
                    240: "H4",
                    1440: "D1",
                }
                return mapping.get(value, f"M{value}")
            if isinstance(value, str):
                v = value.strip().upper()
                if v.isdigit():
                    return _normalize_timeframe_key(int(v))
                if v in ("D1", "1D", "D"):
                    return "D1"
                if v.startswith("M") and v[1:].isdigit():
                    return f"M{int(v[1:])}"
                if v.startswith("H") and v[1:].isdigit():
                    return f"H{int(v[1:])}"
            return None

        def _minutes_from_key(key):
            mapping = {
                "M1": 1,
                "M5": 5,
                "M15": 15,
                "M30": 30,
                "H1": 60,
                "H4": 240,
                "D1": 1440,
            }
            return mapping.get(key)

        timeframes_list = _as_list(timeframes_config if timeframes_config is not None else timeframe)
        preferred_timeframe_key = _normalize_timeframe_key(preferred_timeframe_cfg) if preferred_timeframe_cfg else None

        timeframes_meta = []
        if use_mt5:
            try:
                import MetaTrader5 as mt5
                mt5_timeframes_by_key = {
                    "M1": mt5.TIMEFRAME_M1,
                    "M5": mt5.TIMEFRAME_M5,
                    "M15": mt5.TIMEFRAME_M15,
                    "M30": mt5.TIMEFRAME_M30,
                    "H1": mt5.TIMEFRAME_H1,
                    "H4": mt5.TIMEFRAME_H4,
                    "D1": mt5.TIMEFRAME_D1,
                }
                for item in timeframes_list:
                    key = _normalize_timeframe_key(item)
                    if key is None:
                        continue
                    tf_value = mt5_timeframes_by_key.get(key)
                    if tf_value is None:
                        continue
                    timeframes_meta.append({"key": key, "value": tf_value})
                if not timeframes_meta:
                    timeframes_meta = [{"key": "M5", "value": mt5.TIMEFRAME_M5}]
            except Exception:
                pass
        else:
            for item in timeframes_list:
                key = _normalize_timeframe_key(item)
                minutes = _minutes_from_key(key)
                if minutes is None and isinstance(item, int):
                    minutes = item
                    key = f"M{item}"
                if minutes is None:
                    continue
                timeframes_meta.append({"key": key, "value": minutes})
            if not timeframes_meta:
                timeframes_meta = [{"key": "M5", "value": 5}]

        # Keep a single timeframe for backwards compatibility (first entry)
        if timeframes_meta:
            timeframe = timeframes_meta[0]["value"]

        runner = LiveRunner(
            strategy,
            exchange,
            risk_manager,
            timeframe=timeframe,
            timeframes=timeframes_meta,
            preferred_timeframe=preferred_timeframe_key,
            poll_seconds=poll_seconds
        )
        # Live trading would be initiated here
        print(f"Running in {args.mode} mode...")
        if args.mode == 'live':
            runner.run()


if __name__ == "__main__":
    main()

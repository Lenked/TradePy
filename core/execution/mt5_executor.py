import os
from typing import Optional
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv
from ..exchange.live_interface import LiveExchangeInterface
from ..models import AccountSnapshot
try:
    from ..utils.logger import get_logger
except ImportError:
    # Fallback for when running directly
    from utils.logger import get_logger

# Load environment variables from .env file
# NOTE: This should be handled by the calling code, not here (avoid side effects at import)
# load_dotenv()


class MT5Executor(LiveExchangeInterface):
    def __init__(self, login: Optional[int] = None, password: Optional[str] = None, server: Optional[str] = None):
        # Load environment variables only when needed, not at import time
        load_dotenv()
        self.login = login or int(os.getenv("MT5_LOGIN", "0"))
        self.password = password or os.getenv("MT5_PASSWORD", "")
        self.server = server or os.getenv("MT5_SERVER", "")

        # Initialize logger
        self.logger = get_logger("MT5Executor")

    def connect(self) -> None:
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if not mt5.login(self.login, self.password, self.server):
            err = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(f"MT5 login failed: {err}")

    def shutdown(self) -> None:
        mt5.shutdown()

    def account_info(self) -> AccountSnapshot:
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("MT5 account_info() returned None")
        return AccountSnapshot(
            balance=float(info.balance),
            equity=float(info.equity),
            margin=float(info.margin),
            free_margin=float(info.margin_free),
        )

    def get_rates(self, symbol: str, timeframe: int, count: int = 300) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.sort_index(inplace=True)
        return df

    def positions(self, symbol: Optional[str] = None):
        return mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()

    def has_open_position(self, symbol: str) -> bool:
        pos = self.positions(symbol=symbol)
        return pos is not None and len(pos) > 0

    def floating_pnl(self, symbol: Optional[str] = None) -> float:
        pos = self.positions(symbol=symbol)
        if pos is None:
            return 0.0
        return float(sum(p.profit for p in pos))

    def connect(self) -> bool:
        """Connect to MT5"""
        try:
            if not mt5.initialize():
                error_msg = f"MT5 initialize failed: {mt5.last_error()}"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            if not mt5.login(self.login, self.password, self.server):
                err = mt5.last_error()
                mt5.shutdown()
                error_msg = f"MT5 login failed: {err}"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info("MT5 connection established successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to MT5: {str(e)}")
            return False

    def shutdown(self) -> None:
        """Shutdown MT5 connection"""
        mt5.shutdown()
        self.logger.info("MT5 connection shut down successfully")

    def account_info(self) -> AccountSnapshot:
        """Get account snapshot information"""
        info = mt5.account_info()
        if info is None:
            error_msg = "MT5 account_info() returned None"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        account_snapshot = AccountSnapshot(
            balance=float(info.balance),
            equity=float(info.equity),
            margin=float(info.margin),
            free_margin=float(info.margin_free),
        )

        self.logger.debug(f"Account info retrieved - Balance: {account_snapshot.balance}, Equity: {account_snapshot.equity}")
        return account_snapshot

    def get_rates(self, symbol: str, timeframe: int, count: int = 300) -> pd.DataFrame:
        """Get market rates for a symbol and timeframe"""
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            self.logger.warning(f"No rates data returned for symbol {symbol} with timeframe {timeframe}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.sort_index(inplace=True)

        self.logger.debug(f"Retrieved {len(df)} rates for symbol {symbol}")
        return df

    def positions(self, symbol: Optional[str] = None):
        """Get open positions, optionally filtered by symbol"""
        pos = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if pos is None:
            pos = []

        if symbol:
            self.logger.debug(f"Retrieved {len(pos)} positions for symbol {symbol}")
        else:
            self.logger.debug(f"Retrieved {len(pos)} total positions")

        return pos

    def floating_pnl(self, symbol: Optional[str] = None) -> float:
        """Get floating PnL for a symbol or all positions"""
        pos = self.positions(symbol=symbol)
        if pos is None:
            self.logger.warning(f"No positions found for symbol {symbol}" if symbol else "No positions found")
            return 0.0

        total_pnl = float(sum(p.profit for p in pos))
        if symbol:
            self.logger.info(f"Floating PnL for {symbol}: {total_pnl}")
        else:
            self.logger.info(f"Total floating PnL: {total_pnl}")

        return total_pnl

    def place_market_order(self, symbol: str, side: str, volume: float, sl: float, tp: float,
                          comment: str = "TradePy Live") -> bool:
        """
        Place a market order with mandatory stop loss and take profit.
        This is safe-by-default: both SL and TP are required.
        """
        # Validate inputs comprehensively
        if sl is None or tp is None:
            self.logger.error(f"Both stop loss and take profit are required for safe trading. Order rejected for {symbol}")
            return False

        # Validate side
        side_upper = side.upper()
        if side_upper not in ["BUY", "SELL"]:
            self.logger.error(f"Invalid side '{side}'. Must be 'BUY' or 'SELL'. Order rejected for {symbol}")
            return False

        # Validate volume
        if volume <= 0:
            self.logger.error(f"Invalid volume {volume} for {symbol}. Must be greater than 0.")
            return False

        # Validate symbol
        if symbol is None or symbol.strip() == "":
            self.logger.error(f"Invalid symbol. Cannot be None or empty.")
            return False

        # Get tick data
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            self.logger.error(f"Could not get tick data for {symbol}")
            return False

        # Determine price and validate SL/TP consistency
        if side_upper == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = float(tick.ask)

            # For BUY: SL should be below current price, TP should be above current price
            # And SL should be below TP
            if sl >= price:
                self.logger.error(f"For BUY order, SL ({sl}) must be below current price ({price}). Order rejected for {symbol}")
                return False
            if tp <= price:
                self.logger.error(f"For BUY order, TP ({tp}) must be above current price ({price}). Order rejected for {symbol}")
                return False
            if sl >= tp:
                self.logger.error(f"For BUY order, SL ({sl}) must be below TP ({tp}). Order rejected for {symbol}")
                return False
        else:  # SELL
            order_type = mt5.ORDER_TYPE_SELL
            price = float(tick.bid)

            # For SELL: SL should be above current price, TP should be below current price
            # And TP should be below SL
            if sl <= price:
                self.logger.error(f"For SELL order, SL ({sl}) must be above current price ({price}). Order rejected for {symbol}")
                return False
            if tp >= price:
                self.logger.error(f"For SELL order, TP ({tp}) must be below current price ({price}). Order rejected for {symbol}")
                return False
            if tp >= sl:
                self.logger.error(f"For SELL order, TP ({tp}) must be below SL ({sl}). Order rejected for {symbol}")
                return False

        # Validate SL and TP are positive
        if sl <= 0:
            self.logger.error(f"Stop loss ({sl}) must be positive. Order rejected for {symbol}")
            return False
        if tp <= 0:
            self.logger.error(f"Take profit ({tp}) must be positive. Order rejected for {symbol}")
            return False

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,  # Default deviation
            "magic": 234000,  # Default magic number
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        success = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

        if success:
            self.logger.info(f"Order placed for {symbol} - Side: {side}, Volume: {volume}, SL: {sl}, TP: {tp}")
        else:
            self.logger.error(f"Order failed for {symbol} - Result: {result}")

        return success
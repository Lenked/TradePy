import os
from typing import Optional
import pandas as pd
import MetaTrader5 as mt5
from ..exchange.live_interface import LiveExchangeInterface
from ..models import AccountSnapshot, OrderResult
try:
    from ..utils.logger import get_logger
except ImportError:
    from utils.logger import get_logger


class MT5Executor(LiveExchangeInterface):
    def __init__(self, login: Optional[int] = None, password: Optional[str] = None,
                 server: Optional[str] = None, dry_run: bool = True):
        self.login = login or int(os.getenv("MT5_LOGIN", "0"))
        self.password = password or os.getenv("MT5_PASSWORD", "")
        self.server = server or os.getenv("MT5_SERVER", "")
        self.dry_run = dry_run
        self.account_mode = None
        self.logger = get_logger("MT5Executor")

    def _detect_account_mode(self, account_info) -> str:
        server_lower = (self.server or "").lower()
        if any(key in server_lower for key in ["demo", "trial", "practice"]):
            return "DEMO"
        if any(key in server_lower for key in ["real", "live"]):
            return "REAL"
        trade_mode = getattr(account_info, "trade_mode", None)
        if trade_mode is not None:
            try:
                trade_mode = int(trade_mode)
                if trade_mode == 0:
                    return "DEMO"
                if trade_mode == 2:
                    return "REAL"
            except (TypeError, ValueError):
                pass
        return "DEMO" if self.dry_run else "REAL"

    def connect(self) -> bool:
        if not mt5.initialize():
            self.logger.error(f"MT5 initialize failed: {mt5.last_error()}")
            return False
        if not mt5.login(self.login, self.password, self.server):
            err = mt5.last_error()
            mt5.shutdown()
            self.logger.error(f"MT5 login failed: {err}")
            return False

        info = mt5.account_info()
        if info is None:
            self.logger.error("MT5 account_info() returned None")
            mt5.shutdown()
            return False

        if hasattr(info, "trade_allowed") and not info.trade_allowed:
            self.logger.error("MT5 trading disabled or investor account detected (trade_allowed=False)")
            mt5.shutdown()
            return False

        if hasattr(info, "trade_expert") and not info.trade_expert:
            self.logger.error("MT5 trading disabled for expert advisors (trade_expert=False)")
            mt5.shutdown()
            return False

        self.account_mode = self._detect_account_mode(info)
        self.logger.info(f"MT5 connection established - Mode={self.account_mode}")
        return True

    def shutdown(self) -> None:
        mt5.shutdown()
        self.logger.info("MT5 connection shut down successfully")

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
        if timeframe is None:
            timeframe = mt5.TIMEFRAME_M5
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.sort_index(inplace=True)
        return df

    def positions(self, symbol: Optional[str] = None):
        pos = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        return pos if pos is not None else []

    def floating_pnl(self, symbol: Optional[str] = None) -> float:
        pos = self.positions(symbol=symbol)
        return float(sum(p.profit for p in pos)) if pos else 0.0

    def place_market_order(self, symbol: str, side: str, volume: float, sl: float, tp: float,
                          comment: str = "TradePy Live") -> OrderResult:
        if not symbol or not symbol.strip():
            return OrderResult(success=False, message="invalid_symbol")

        if not mt5.symbol_select(symbol, True):
            return OrderResult(success=False, message=f"symbol_select_failed: {mt5.last_error()}")

        side_upper = side.upper()
        if side_upper not in ["BUY", "SELL"]:
            return OrderResult(success=False, message="invalid_side")

        if volume <= 0:
            return OrderResult(success=False, message="invalid_volume")

        if sl is None or tp is None or sl <= 0 or tp <= 0:
            return OrderResult(success=False, message="invalid_sl_tp")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(success=False, message="missing_tick")

        if side_upper == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = float(tick.ask)
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = float(tick.bid)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": 234000,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        if self.dry_run:
            self.logger.info(f"MT5_DRY_RUN_ORDER_SIMULATED - {side_upper} {volume} {symbol} | SL: {sl} | TP: {tp} | Comment: {comment}")
            return OrderResult(
                success=True,
                retcode=None,
                order_id=None,
                comment=comment,
                request=request,
                message="dry_run_simulated",
            )

        result = mt5.order_send(request)
        if result is None:
            self.logger.error(f"MT5_ORDER_FAILED - Symbol: {symbol} - Retcode: N/A - Comment: order_send returned None")
            return OrderResult(success=False, retcode=None, comment="order_send returned None", request=request, message="order_send_none")

        retcode = getattr(result, "retcode", None)
        order_id = getattr(result, "order", None) or getattr(result, "ticket", None)
        result_comment = getattr(result, "comment", "")
        success = retcode == mt5.TRADE_RETCODE_DONE

        if success:
            self.logger.info(
                f"MT5_ORDER_SENT - Ticket: {order_id} - {side_upper} {volume} {symbol} | SL: {sl} | TP: {tp} | Retcode: {retcode}"
            )
        else:
            self.logger.error(
                f"MT5_ORDER_FAILED - Symbol: {symbol} - Retcode: {retcode} - Comment: {result_comment}"
            )

        return OrderResult(
            success=success,
            order_id=str(order_id) if order_id is not None else None,
            retcode=retcode,
            comment=result_comment or comment,
            request=request,
            message="order_sent" if success else "order_failed",
            details={"result": result},
        )

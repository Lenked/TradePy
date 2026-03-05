import os
import logging
from typing import Optional
import pandas as pd
import MetaTrader5 as mt5
try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
except ImportError:  # pragma: no cover - allows graceful startup before deps install
    def retry(*args, **kwargs):
        def _decorator(func):
            return func
        return _decorator

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

    def retry_if_exception_type(*args, **kwargs):
        return None

    def before_sleep_log(*args, **kwargs):
        return None
from ..exchange.live_interface import LiveExchangeInterface
from ..models import AccountSnapshot, OrderResult
try:
    from ..utils.logger import get_logger
except ImportError:
    from utils.logger import get_logger


class MT5TransientError(RuntimeError):
    """Transient MT5 API error that can be retried."""


class MT5Executor(LiveExchangeInterface):
    def __init__(self, login: Optional[int] = None, password: Optional[str] = None,
                 server: Optional[str] = None, dry_run: bool = True):
        self.login = login or int(os.getenv("MT5_LOGIN", "0"))
        self.password = password or os.getenv("MT5_PASSWORD", "")
        self.server = server or os.getenv("MT5_SERVER", "")
        self.dry_run = dry_run
        self.account_mode = None
        self.logger = get_logger("MT5Executor")

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(MT5TransientError),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    def _initialize_with_retry(self) -> None:
        if not mt5.initialize():
            raise MT5TransientError(f"MT5 initialize failed: {mt5.last_error()}")

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(MT5TransientError),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    def _login_with_retry(self) -> None:
        if not mt5.login(self.login, self.password, self.server):
            raise MT5TransientError(f"MT5 login failed: {mt5.last_error()}")

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(MT5TransientError),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    def _account_info_with_retry(self):
        info = mt5.account_info()
        if info is None:
            raise MT5TransientError(f"MT5 account_info failed: {mt5.last_error()}")
        return info

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(MT5TransientError),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    def _copy_rates_with_retry(self, symbol: str, timeframe: int, count: int):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None:
            raise MT5TransientError(f"MT5 copy_rates_from_pos failed for {symbol}: {mt5.last_error()}")
        return rates

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(MT5TransientError),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    def _positions_get_with_retry(self, symbol: Optional[str] = None):
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if positions is None:
            raise MT5TransientError(f"MT5 positions_get failed: {mt5.last_error()}")
        return positions

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(MT5TransientError),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    def _order_send_with_retry(self, request: dict):
        result = mt5.order_send(request)
        if result is None:
            raise MT5TransientError(f"MT5 order_send returned None: {mt5.last_error()}")
        return result

    def _resolve_symbol(self, symbol: str) -> Optional[str]:
        if not symbol:
            return None
        if mt5.symbol_select(symbol, True):
            return symbol
        if not symbol.endswith("m"):
            symbol_m = f"{symbol}m"
            if mt5.symbol_select(symbol_m, True):
                return symbol_m
        return None

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
        try:
            self._initialize_with_retry()
            self._login_with_retry()
            info = self._account_info_with_retry()
        except MT5TransientError as exc:
            self.logger.error(str(exc))
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
        
        # Perform startup check for symbol volume constraints
        self._log_symbol_constraints()
        return True

    def _log_symbol_constraints(self):
        """Log symbol volume constraints for commonly traded symbols"""
        # Common forex symbols to check
        common_symbols = [
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", 
            "USDCHF", "EURGBP", "EURJPY", "GBPJPY", "XAUUSD", "XAGUSD"
        ]
        
        self.logger.info("=" * 60)
        self.logger.info("MT5 SYMBOL VOLUME CONSTRAINTS CHECK:")
        self.logger.info("=" * 60)
        self.logger.info(f"{'Symbol':<10} {'Min Lot':<10} {'Max Lot':<12} {'Step':<10} {'Contract Size':<15}")
        self.logger.info("-" * 60)
        
        for symbol in common_symbols:
            resolved = self._resolve_symbol(symbol)
            if resolved:
                symbol_info = mt5.symbol_info(resolved)
                if symbol_info is not None:
                    # Extract volume constraints
                    min_lot = symbol_info.volume_min
                    max_lot = symbol_info.volume_max
                    step = symbol_info.volume_step
                    contract_size = getattr(symbol_info, 'trade_contract_size', 'N/A')
                    
                    self.logger.info(f"{resolved:<10} {min_lot:<10.2f} {max_lot:<12.2f} {step:<10.2f} {contract_size:<15}")
                else:
                    self.logger.info(f"{resolved:<10} {'N/A':<10} {'N/A':<12} {'N/A':<10} {'N/A':<15}")
            else:
                self.logger.info(f"{symbol:<10} {'Not Found':<10} {'Not Found':<12} {'Not Found':<10} {'Not Found':<15}")
        
        self.logger.info("-" * 60)
        self.logger.info("Volume constraints will be automatically applied to all orders")
        self.logger.info("=" * 60)

    def shutdown(self) -> None:
        mt5.shutdown()
        self.logger.info("MT5 connection shut down successfully")

    def account_info(self) -> AccountSnapshot:
        try:
            info = self._account_info_with_retry()
        except MT5TransientError as exc:
            raise RuntimeError(str(exc)) from exc
        return AccountSnapshot(
            balance=float(info.balance),
            equity=float(info.equity),
            margin=float(info.margin),
            free_margin=float(info.margin_free),
        )

    def get_rates(self, symbol: str, timeframe: int, count: int = 300) -> pd.DataFrame:
        if timeframe is None:
            timeframe = mt5.TIMEFRAME_M5
        resolved = self._resolve_symbol(symbol)
        if not resolved:
            return pd.DataFrame()
        try:
            rates = self._copy_rates_with_retry(resolved, timeframe, count)
        except MT5TransientError as exc:
            self.logger.warning(str(exc))
            return pd.DataFrame()
        if len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.sort_index(inplace=True)
        return df

    def positions(self, symbol: Optional[str] = None):
        resolved = self._resolve_symbol(symbol) if symbol else None
        try:
            return self._positions_get_with_retry(symbol=resolved)
        except MT5TransientError as exc:
            self.logger.warning(str(exc))
            return []

    def floating_pnl(self, symbol: Optional[str] = None) -> float:
        pos = self.positions(symbol=symbol)
        return float(sum(p.profit for p in pos)) if pos else 0.0

    def get_tick(self, symbol: str):
        resolved = self._resolve_symbol(symbol)
        return mt5.symbol_info_tick(resolved) if resolved else None

    def get_symbol_point(self, symbol: str) -> Optional[float]:
        resolved = self._resolve_symbol(symbol)
        info = mt5.symbol_info(resolved) if resolved else None
        return float(info.point) if info and info.point else None

    def estimate_spread_points(self, symbol: str) -> Optional[float]:
        tick = self.get_tick(symbol)
        point = self.get_symbol_point(symbol)
        if tick is None or point is None or point == 0:
            return None
        return float((tick.ask - tick.bid) / point)

    def estimate_slippage_points(self, symbol: str, reference_price: Optional[float], side: Optional[str] = None) -> Optional[float]:
        if reference_price is None:
            return None
        tick = self.get_tick(symbol)
        point = self.get_symbol_point(symbol)
        if tick is None or point is None or point == 0:
            return None
        side_upper = (side or "").upper()
        if side_upper == "BUY":
            price = float(tick.ask)
        elif side_upper == "SELL":
            price = float(tick.bid)
        else:
            price = float((tick.ask + tick.bid) / 2.0)
        return float(abs(price - reference_price) / point)

    def _normalize_volume(self, volume: float, symbol_info) -> float:
        """
        Normalize volume based on symbol's volume constraints.
        
        Args:
            volume: Original volume to normalize
            symbol_info: Symbol info object from mt5.symbol_info()
            
        Returns:
            float: Normalized volume that meets symbol requirements
        """
        if symbol_info is None:
            self.logger.error("_normalize_volume called with None symbol_info")
            return max(volume, 0.01)  # Return minimum default if no symbol info
        
        min_lot = symbol_info.volume_min
        max_lot = symbol_info.volume_max
        step = symbol_info.volume_step
        
        # Log original volume for debugging
        self.logger.debug(f"VOLUME_NORMALIZATION - Symbol: {symbol_info.name} | "
                         f"ORIGINAL_VOLUME: {volume} | MIN: {min_lot} | MAX: {max_lot} | STEP: {step}")
        
        # First clamp the volume between min and max
        adjusted_volume = max(min_lot, min(volume, max_lot))
        
        # Then align with step increment
        if step > 0:
            # Calculate how many steps fit in the adjusted volume
            steps = adjusted_volume / step
            # Round down to nearest integer number of steps to ensure we don't exceed constraints
            steps = int(steps)
            # Recalculate the volume
            adjusted_volume = steps * step
            
            # Ensure we don't go below min_lot after step adjustment
            if adjusted_volume < min_lot:
                adjusted_volume = min_lot
        
        # Round to avoid floating point precision issues
        # Determine the appropriate number of decimal places based on step size
        if step > 0:
            # Count decimal places in step
            step_str = str(step)
            if '.' in step_str:
                decimals = len(step_str.split('.')[1])
            else:
                decimals = 0
            adjusted_volume = round(adjusted_volume, decimals)
        else:
            # If step is 0 (shouldn't happen normally), round to 2 decimal places as fallback
            adjusted_volume = round(adjusted_volume, 2)
        
        # Final check to ensure volume is within bounds
        adjusted_volume = max(min_lot, min(adjusted_volume, max_lot))
        
        self.logger.debug(f"VOLUME_NORMALIZED - Symbol: {symbol_info.name} | "
                         f"ORIGINAL: {volume} | NORMALIZED: {adjusted_volume} | "
                         f"MIN: {min_lot} | MAX: {max_lot} | STEP: {step}")
        
        return adjusted_volume
    
    def place_market_order(self, symbol: str, side: str, volume: float, sl: float, tp: float,
                          comment: str = "TradePy Live") -> OrderResult:
        if not symbol or not symbol.strip():
            return OrderResult(success=False, message="invalid_symbol")

        # Ensure the symbol is selected
        resolved = self._resolve_symbol(symbol)
        if not resolved:
            return OrderResult(success=False, message=f"symbol_select_failed: {mt5.last_error()}")

        side_upper = side.upper()
        if side_upper not in ["BUY", "SELL"]:
            return OrderResult(success=False, message="invalid_side")

        if volume <= 0:
            return OrderResult(success=False, message="invalid_volume")

        if sl is None or tp is None or sl <= 0 or tp <= 0:
            return OrderResult(success=False, message="invalid_sl_tp")

        tick = mt5.symbol_info_tick(resolved)
        if tick is None:
            return OrderResult(success=False, message="missing_tick")

        if side_upper == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = float(tick.ask)
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = float(tick.bid)

        # Normalize volume based on symbol constraints when available.
        # In dry-run tests we tolerate missing symbol_info and keep raw volume.
        normalized_volume = float(volume)
        symbol_info = mt5.symbol_info(resolved) if hasattr(mt5, "symbol_info") else None
        if symbol_info is not None:
            normalized_volume = self._normalize_volume(volume, symbol_info)
        elif not self.dry_run:
            if not hasattr(mt5, "symbol_info"):
                self.logger.error("MT5_SYMBOL_INFO_UNAVAILABLE - MetaTrader5 symbol_info API not available")
                return OrderResult(success=False, message="symbol_info_unavailable")
            self.logger.error(f"MT5_SYMBOL_INFO_FAILED - Could not get symbol info for {resolved}")
            return OrderResult(success=False, message=f"symbol_info_failed: {resolved}")
        else:
            self.logger.warning(f"MT5_SYMBOL_INFO_MISSING_DRY_RUN - Using raw volume for {resolved}")
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": resolved,
            "volume": float(normalized_volume),  # Use normalized volume here
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
            self.logger.info(f"MT5_DRY_RUN_ORDER_SIMULATED - {side_upper} {normalized_volume} {resolved} | SL: {sl} | TP: {tp} | Comment: {comment}")
            return OrderResult(
                success=True,
                retcode=None,
                order_id=None,
                comment=comment,
                request=request,
                message="dry_run_simulated",
            )

        try:
            result = self._order_send_with_retry(request)
        except MT5TransientError as exc:
            self.logger.error(f"MT5_ORDER_FAILED - Symbol: {resolved} - Retcode: N/A - Comment: {exc}")
            return OrderResult(success=False, retcode=None, comment=str(exc), request=request, message="order_send_retry_exhausted")

        retcode = getattr(result, "retcode", None)
        order_id = getattr(result, "order", None) or getattr(result, "ticket", None)
        result_comment = getattr(result, "comment", "")
        success = retcode == mt5.TRADE_RETCODE_DONE

        if success:
            self.logger.info(
                f"MT5_ORDER_SENT - Ticket: {order_id} - {side_upper} {normalized_volume} {resolved} | SL: {sl} | TP: {tp} | Retcode: {retcode}"
            )
        else:
            self.logger.error(
                f"MT5_ORDER_FAILED - Symbol: {resolved} - Retcode: {retcode} - Comment: {result_comment}"
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

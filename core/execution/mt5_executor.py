import os
from typing import Optional
import pandas as pd
import MetaTrader5 as mt5
from ..exchange.live_interface import LiveExchangeInterface
from ..models import AccountSnapshot, OrderResult, SymbolTradeConstraints
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
        resolved = self._resolve_symbol(symbol)
        if not resolved:
            return pd.DataFrame()
        rates = mt5.copy_rates_from_pos(resolved, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.sort_index(inplace=True)
        return df

    def positions(self, symbol: Optional[str] = None):
        resolved = self._resolve_symbol(symbol) if symbol else None
        pos = mt5.positions_get(symbol=resolved) if resolved else mt5.positions_get()
        return pos if pos is not None else []

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

    def get_symbol_trade_constraints(self, symbol: str) -> Optional[SymbolTradeConstraints]:
        resolved = self._resolve_symbol(symbol)
        info = mt5.symbol_info(resolved) if resolved else None
        if info is None:
            return None

        tick_size = getattr(info, "trade_tick_size", None) or getattr(info, "point", None)
        tick_value = (
            getattr(info, "trade_tick_value", None)
            or getattr(info, "trade_tick_value_profit", None)
            or getattr(info, "trade_tick_value_loss", None)
        )
        contract_size = getattr(info, "trade_contract_size", None)

        return SymbolTradeConstraints(
            symbol=resolved,
            min_lot=float(info.volume_min),
            max_lot=float(info.volume_max),
            lot_step=float(info.volume_step),
            point=float(info.point) if getattr(info, "point", None) else None,
            tick_size=float(tick_size) if tick_size else None,
            tick_value=float(tick_value) if tick_value else None,
            contract_size=float(contract_size) if contract_size else None,
        )

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

    def close_position(
        self,
        ticket: str,
        symbol: str,
        volume: float,
        side: str,
        comment: str = "TradePy Session End",
    ) -> OrderResult:
        if not ticket:
            return OrderResult(success=False, message="invalid_ticket")

        resolved = self._resolve_symbol(symbol)
        if not resolved:
            return OrderResult(success=False, order_id=str(ticket), message=f"symbol_select_failed: {mt5.last_error()}")

        symbol_info = mt5.symbol_info(resolved)
        if symbol_info is None:
            self.logger.error(f"MT5_SYMBOL_INFO_FAILED - Could not get symbol info for {resolved}")
            return OrderResult(success=False, order_id=str(ticket), message=f"symbol_info_failed: {resolved}")

        side_upper = (side or "").upper()
        if side_upper == "BUY":
            order_type = mt5.ORDER_TYPE_SELL
        elif side_upper == "SELL":
            order_type = mt5.ORDER_TYPE_BUY
        else:
            return OrderResult(success=False, order_id=str(ticket), message="invalid_side")

        tick_info = mt5.symbol_info_tick(resolved)
        if tick_info is None:
            return OrderResult(success=False, order_id=str(ticket), message="missing_tick")

        price = float(tick_info.bid) if side_upper == "BUY" else float(tick_info.ask)
        normalized_volume = self._normalize_volume(volume, symbol_info)
        try:
            position_id = int(ticket)
        except (TypeError, ValueError):
            return OrderResult(success=False, order_id=str(ticket), message="invalid_ticket")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": resolved,
            "volume": float(normalized_volume),
            "type": order_type,
            "position": position_id,
            "price": price,
            "deviation": 20,
            "magic": 234000,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        if self.dry_run:
            self.logger.info(
                f"MT5_DRY_RUN_CLOSE_SIMULATED - Ticket: {ticket} - {resolved} | "
                f"CloseSide: {order_type} | Volume: {normalized_volume} | Comment: {comment}"
            )
            return OrderResult(
                success=True,
                order_id=str(ticket),
                retcode=None,
                comment=comment,
                request=request,
                message="dry_run_close_simulated",
            )

        result = mt5.order_send(request)
        if result is None:
            self.logger.error(
                f"MT5_CLOSE_FAILED - Ticket: {ticket} - Symbol: {resolved} - Retcode: N/A - "
                f"Comment: order_send returned None"
            )
            return OrderResult(
                success=False,
                order_id=str(ticket),
                retcode=None,
                comment="order_send returned None",
                request=request,
                message="order_send_none",
            )

        retcode = getattr(result, "retcode", None)
        deal_id = getattr(result, "deal", None) or getattr(result, "order", None) or getattr(result, "ticket", None)
        result_comment = getattr(result, "comment", "")
        success_codes = {getattr(mt5, "TRADE_RETCODE_DONE", None), getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", None)}
        success = retcode in success_codes

        if success:
            self.logger.info(
                f"MT5_CLOSE_SENT - Ticket: {ticket} - {resolved} | Volume: {normalized_volume} | "
                f"Retcode: {retcode} | Deal: {deal_id}"
            )
        else:
            self.logger.error(
                f"MT5_CLOSE_FAILED - Ticket: {ticket} - Symbol: {resolved} - "
                f"Retcode: {retcode} - Comment: {result_comment}"
            )

        return OrderResult(
            success=success,
            order_id=str(deal_id) if deal_id is not None else str(ticket),
            retcode=retcode,
            comment=result_comment or comment,
            request=request,
            message="position_closed" if success else "position_close_failed",
            details={"result": result},
        )

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
            epsilon = step * 1e-9
            steps = int((adjusted_volume + epsilon) / step)
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

        # Get symbol info to normalize volume
        symbol_info = mt5.symbol_info(resolved)
        if symbol_info is None:
            self.logger.error(f"MT5_SYMBOL_INFO_FAILED - Could not get symbol info for {resolved}")
            return OrderResult(success=False, message=f"symbol_info_failed: {resolved}")

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

        # Normalize volume based on symbol constraints
        normalized_volume = self._normalize_volume(volume, symbol_info)
        
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

        result = mt5.order_send(request)
        if result is None:
            self.logger.error(f"MT5_ORDER_FAILED - Symbol: {resolved} - Retcode: N/A - Comment: order_send returned None")
            return OrderResult(success=False, retcode=None, comment="order_send returned None", request=request, message="order_send_none")

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

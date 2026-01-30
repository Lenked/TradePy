import sys
import types


def test_mt5_executor_dry_run_skips_order_send(monkeypatch):
    dummy = types.SimpleNamespace()
    dummy.ORDER_TYPE_BUY = 0
    dummy.ORDER_TYPE_SELL = 1
    dummy.ORDER_TIME_GTC = 0
    dummy.ORDER_FILLING_FOK = 0
    dummy.TRADE_ACTION_DEAL = 1
    dummy.TRADE_RETCODE_DONE = 10009
    dummy._order_send_called = 0

    def symbol_select(symbol, _):
        return True

    def symbol_info_tick(symbol):
        return types.SimpleNamespace(ask=1.2345, bid=1.2340)

    def order_send(_):
        dummy._order_send_called += 1
        return None

    dummy.symbol_select = symbol_select
    dummy.symbol_info_tick = symbol_info_tick
    dummy.order_send = order_send

    sys.modules["MetaTrader5"] = dummy
    sys.modules.pop("core.execution.mt5_executor", None)

    from core.execution.mt5_executor import MT5Executor

    executor = MT5Executor(dry_run=True)
    result = executor.place_market_order("EURUSD", "BUY", 0.1, 1.2, 1.4)

    assert result.success is True
    assert dummy._order_send_called == 0

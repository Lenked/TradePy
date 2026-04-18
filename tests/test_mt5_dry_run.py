import sys
import types


def _build_dummy_mt5():
    dummy = types.SimpleNamespace()
    dummy.ORDER_TYPE_BUY = 0
    dummy.ORDER_TYPE_SELL = 1
    dummy.ORDER_TIME_GTC = 0
    dummy.ORDER_FILLING_FOK = 0
    dummy.TRADE_ACTION_DEAL = 1
    dummy.TRADE_ACTION_SLTP = 2
    dummy.TRADE_RETCODE_DONE = 10009
    dummy.TRADE_RETCODE_DONE_PARTIAL = 10010
    dummy._order_send_called = 0

    def symbol_select(symbol, _):
        return True

    def symbol_info(_symbol):
        return types.SimpleNamespace(
            name="EURUSDm",
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
        )

    def symbol_info_tick(_symbol):
        return types.SimpleNamespace(ask=1.2345, bid=1.2340)

    def order_send(_):
        dummy._order_send_called += 1
        return None

    dummy.symbol_select = symbol_select
    dummy.symbol_info = symbol_info
    dummy.symbol_info_tick = symbol_info_tick
    dummy.order_send = order_send
    return dummy


def test_mt5_executor_dry_run_skips_order_send(monkeypatch):
    dummy = _build_dummy_mt5()

    sys.modules["MetaTrader5"] = dummy
    sys.modules.pop("core.execution.mt5_executor", None)

    from core.execution.mt5_executor import MT5Executor

    executor = MT5Executor(dry_run=True)
    result = executor.place_market_order("EURUSD", "BUY", 0.1, 1.2, 1.4)

    assert result.success is True
    assert dummy._order_send_called == 0


def test_mt5_executor_dry_run_close_skips_order_send(monkeypatch):
    dummy = _build_dummy_mt5()

    sys.modules["MetaTrader5"] = dummy
    sys.modules.pop("core.execution.mt5_executor", None)

    from core.execution.mt5_executor import MT5Executor

    executor = MT5Executor(dry_run=True)
    result = executor.close_position("123456", "EURUSD", 0.1, "BUY")

    assert result.success is True
    assert result.message == "dry_run_close_simulated"
    assert dummy._order_send_called == 0


def test_mt5_executor_dry_run_protection_update_skips_order_send(monkeypatch):
    dummy = _build_dummy_mt5()

    sys.modules["MetaTrader5"] = dummy
    sys.modules.pop("core.execution.mt5_executor", None)

    from core.execution.mt5_executor import MT5Executor

    executor = MT5Executor(dry_run=True)
    result = executor.update_position_protection("123456", "EURUSD", 1.22, 1.30)

    assert result.success is True
    assert result.message == "dry_run_protection_update"
    assert dummy._order_send_called == 0

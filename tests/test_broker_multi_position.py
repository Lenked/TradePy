import pandas as pd

from core.exchange.broker import Broker


def test_broker_allows_multiple_positions_for_same_symbol_when_not_duplicate_bar():
    broker = Broker({"initial_capital": 10000, "trading": {"dry_run": False}})
    broker.connect()
    broker.get_rates = lambda symbol, timeframe, count=300: pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
        }
    )

    first = broker.place_market_order("BTCUSDm", "BUY", 0.01, 1.0, 2.0)
    broker._last_order_times["BTCUSDm"] = pd.Timestamp.now() - pd.Timedelta(seconds=11)
    second = broker.place_market_order("BTCUSDm", "BUY", 0.01, 1.0, 2.0)

    assert first.success is True
    assert second.success is True
    assert len(broker.positions("BTCUSDm")) == 2

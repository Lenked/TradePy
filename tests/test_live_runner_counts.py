from live.runner import LiveRunner


class DummyExchange:
    dry_run = True


def test_count_open_positions_global_and_symbol():
    runner = LiveRunner(strategy=None, exchange=DummyExchange())
    positions = [
        {"symbol": "XAUUSDm", "ticket": "1"},
        {"symbol": "BTCUSDm", "ticket": "2"},
        {"symbol": "BTCUSDm", "ticket": "3"},
    ]
    assert runner._count_open_positions(positions) == 3
    assert runner._count_open_positions(positions, "BTCUSDm") == 2


def test_global_open_positions_active_ignores_inactive_symbols():
    runner = LiveRunner(strategy=None, exchange=DummyExchange())
    positions = [{"symbol": "XAUUSDm", "ticket": "1"}]
    active_symbols = ["BTCUSDm"]
    global_open_active = 0
    for symbol in active_symbols:
        global_open_active += runner._count_open_positions(positions, symbol)
    assert global_open_active == 0

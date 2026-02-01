from live.runner import LiveRunner


class DummyExchange:
    dry_run = True


def test_symbol_position_lock_counts_only_same_symbol():
    runner = LiveRunner(strategy=None, exchange=DummyExchange())
    positions = [
        {"symbol": "XAUUSDm", "ticket": "1"},
        {"symbol": "BTCUSDm", "ticket": "2"},
        {"symbol": "BTCUSDm", "ticket": "3"},
    ]

    assert runner._count_open_positions_for_symbol(positions, "XAUUSDm") == 1
    assert runner._count_open_positions_for_symbol(positions, "BTCUSDm") == 2
    assert runner._count_open_positions_for_symbol(positions, "EURUSDm") == 0

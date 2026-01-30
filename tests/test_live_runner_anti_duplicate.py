import pandas as pd

from live.runner import LiveRunner


class DummyExchange:
    dry_run = True


def test_live_runner_anti_duplicate_bar_lock():
    runner = LiveRunner(strategy=None, exchange=DummyExchange())
    bar_time = pd.Timestamp("2024-01-01 00:00:00")

    assert runner._already_traded_on_bar("EURUSD", bar_time) is False
    runner._mark_traded_on_bar("EURUSD", bar_time)
    assert runner._already_traded_on_bar("EURUSD", bar_time) is True
    assert runner._already_traded_on_bar("EURUSD", bar_time + pd.Timedelta(minutes=1)) is False

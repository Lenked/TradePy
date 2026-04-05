import pandas as pd

from live.runner import LiveRunner


class DummyExchange:
    dry_run = True


def _build_rates(start: str = "2026-04-06 00:00:00", periods: int = 5, freq: str = "5min") -> pd.DataFrame:
    index = pd.date_range(start=start, periods=periods, freq=freq)
    values = [100.0 + i for i in range(periods)]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 0.5 for value in values],
            "low": [value - 0.5 for value in values],
            "close": values,
        },
        index=index,
    )


def test_first_seen_closed_bar_establishes_baseline_without_signal():
    runner = LiveRunner(strategy=None, exchange=DummyExchange())
    df = _build_rates()

    assert runner._is_new_closed_bar(df, "BTCUSDm", "M5") is False


def test_new_closed_bar_after_baseline_returns_true():
    runner = LiveRunner(strategy=None, exchange=DummyExchange())
    first = _build_rates(start="2026-04-06 00:00:00")
    second = _build_rates(start="2026-04-06 00:05:00")

    assert runner._is_new_closed_bar(first, "BTCUSDm", "M5") is False
    assert runner._is_new_closed_bar(second, "BTCUSDm", "M5") is True

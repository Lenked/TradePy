import numpy as np
import pandas as pd

from core.strategy.signal import SignalType
from core.strategy.trend_following_strategy import TrendFollowingStrategy


def _make_trending_df(rows: int = 320) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=rows, freq="min")
    base = 1800 + np.linspace(0, 35, rows)
    noise = 0.15 * np.sin(np.linspace(0, 25, rows))
    close = base + noise
    open_ = close - 0.05
    high = close + 0.20
    low = close - 0.20
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        },
        index=idx,
    )


def test_generate_signal_buy_without_regime_filters():
    df = _make_trending_df()
    strategy = TrendFollowingStrategy(
        use_pandas_ta=False,
        use_adx_filter=False,
        use_arch_volatility_filter=False,
    )

    signal = strategy.generate_signal(df)

    assert signal == SignalType.BUY


def test_adx_filter_can_block_trade_with_high_threshold():
    df = _make_trending_df()
    strategy = TrendFollowingStrategy(
        use_pandas_ta=False,
        use_adx_filter=True,
        adx_threshold=101.0,
        use_arch_volatility_filter=False,
    )

    signal = strategy.generate_signal(df)

    assert signal == SignalType.HOLD
    assert strategy.hold_reason(df).startswith("weak_trend_adx")


def test_arch_filter_blocks_high_conditional_volatility(monkeypatch):
    df = _make_trending_df()
    strategy = TrendFollowingStrategy(
        use_pandas_ta=False,
        use_adx_filter=False,
        use_arch_volatility_filter=True,
        max_conditional_volatility=0.01,
    )

    monkeypatch.setattr(strategy, "_estimate_conditional_volatility", lambda _close: 0.05)
    signal = strategy.generate_signal(df)

    assert signal == SignalType.HOLD
    assert strategy.hold_reason(df).startswith("high_conditional_volatility")

import numpy as np
import pandas as pd
import pytest

from ai.decision import HybridDecisionEngine
from core.strategy.signal import SignalType
from core.strategy.trend_following_strategy import TrendFollowingStrategy


def _build_trend_df(direction: str = "up", periods: int = 260) -> pd.DataFrame:
    base = np.linspace(100.0, 130.0, periods) if direction == "up" else np.linspace(130.0, 100.0, periods)
    noise = np.sin(np.linspace(0, 12, periods)) * 0.2
    close = base + noise
    open_ = close * (0.999 if direction == "up" else 1.001)
    high = np.maximum(open_, close) + 0.3
    low = np.minimum(open_, close) - 0.3
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        }
    )


def test_hybrid_engine_confirms_buy_signal():
    engine = HybridDecisionEngine({"enabled": True})
    decision = engine.evaluate(
        {
            "trend_bias": 1.2,
            "momentum_bias": 0.8,
            "alignment_bias": 0.6,
            "breakout_bias": 0.5,
            "volatility_penalty": 0.1,
        },
        base_signal=SignalType.BUY,
    )

    assert decision["signal"] == SignalType.BUY
    assert decision["confidence"] >= 0.58
    assert decision["reason"] == "ai_confirmed_base_signal"


def test_hybrid_engine_rejects_conflicting_base_signal_without_override():
    engine = HybridDecisionEngine({"enabled": True, "allow_ai_override": False})
    decision = engine.evaluate(
        {
            "trend_bias": -1.1,
            "momentum_bias": -0.8,
            "alignment_bias": -0.7,
            "breakout_bias": -0.6,
            "volatility_penalty": 0.1,
        },
        base_signal=SignalType.BUY,
    )

    assert decision["signal"] == SignalType.HOLD
    assert decision["reason"] == "ai_rejected_conflicting_base_signal"


def test_strategy_generate_decision_returns_buy_on_strong_uptrend():
    strategy = TrendFollowingStrategy(
        ai_decision_config={
            "enabled": True,
            "allow_ai_override": False,
        },
        rsi_buy_max=None,
        rsi_sell_min=None,
    )

    decision = strategy.generate_decision(_build_trend_df("up"), symbol="XAUUSDm")

    assert decision["signal"] == SignalType.BUY
    assert decision["confidence"] > 0.0


def test_compute_sl_tp_enforces_min_reward_risk_ratio_for_scalping():
    df = _build_trend_df("up", periods=120)
    strategy = TrendFollowingStrategy(
        sl_atr_multiplier=2.0,
        tp_atr_multiplier=3.0,
        scalping_config={
            "enabled": True,
            "tp_multiplier": 0.35,
            "min_reward_risk_ratio": 1.1,
        },
    )

    sl, tp = strategy.compute_sl_tp(df, SignalType.BUY)
    entry_price = float(df["close"].iloc[-1])
    risk = entry_price - sl
    reward = tp - entry_price

    assert risk > 0
    assert reward / risk == pytest.approx(1.1, rel=1e-6)

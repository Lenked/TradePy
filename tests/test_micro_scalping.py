from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core.reporting.trade_reporter import TradeReporter
from core.strategy.trend_following_strategy import TrendFollowingStrategy
from live.runner import LiveRunner


class DummyExchange:
    dry_run = True

    def __init__(self, df: pd.DataFrame, current_price: float):
        self.df = df
        self.current_price = current_price
        self.protection_updates = []
        self.closed_positions = []

    def get_rates(self, symbol, timeframe, count=300):
        return self.df.copy()

    def get_tick(self, symbol):
        return SimpleNamespace(bid=self.current_price, ask=self.current_price + 0.1)

    def update_position_protection(self, ticket, symbol, sl, tp, comment="TradePy Protection Update"):
        self.protection_updates.append(
            {"ticket": ticket, "symbol": symbol, "sl": sl, "tp": tp, "comment": comment}
        )
        return SimpleNamespace(success=True, message="protection_updated", details={"sl": sl, "tp": tp})

    def close_position(self, ticket, symbol, volume, side, comment="TradePy Session End"):
        self.closed_positions.append(
            {"ticket": ticket, "symbol": symbol, "volume": volume, "side": side, "comment": comment}
        )
        return SimpleNamespace(
            success=True,
            message="position_closed",
            details={"profit": 0.0, "exit_price": self.current_price},
        )


def _make_df(last_close: float = 100.0, count: int = 120) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=count, freq="min")
    closes = np.linspace(last_close - 10.0, last_close, count)
    opens = closes - 0.15
    highs = closes + 1.0
    lows = closes - 1.0
    volumes = np.linspace(1000, 1400, count)
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def _runner(df: pd.DataFrame, current_price: float, scalping_overrides=None, intra_bar_overrides=None):
    scalping_config = {
        "enabled": True,
        "break_even_trigger_pct": 0.25,
        "break_even_offset_usd": 0.10,
        "secure_profit_trigger_pct": 0.50,
        "secure_profit_lock_pct": 0.40,
        "trailing_stop_enabled": True,
        "trailing_stop_distance_atr_multiplier": 0.45,
        "fast_exit_on_reversal": False,
        "reversal_candles_required": 1,
    }
    intra_bar_config = {
        "enabled": True,
        "max_trades_per_bar": 5,
        "min_seconds_between_trades": 5,
        "allow_reentry_same_direction": True,
        "allow_reentry_after_tp": True,
        "allow_reverse_trade_same_bar": False,
        "require_price_move_pct_between_entries": 0.08,
        "require_new_high_low_breakout": True,
        "cooldown_after_loss_seconds": 30,
    }
    if scalping_overrides:
        scalping_config.update(scalping_overrides)
    if intra_bar_overrides:
        intra_bar_config.update(intra_bar_overrides)

    strategy = TrendFollowingStrategy()
    exchange = DummyExchange(df=df, current_price=current_price)
    return LiveRunner(
        strategy=strategy,
        exchange=exchange,
        scalping_config=scalping_config,
        intra_bar_config=intra_bar_config,
        timeframe=5,
        timeframes=[{"key": "M5", "value": 5}],
    )


def _position(entry_price=100.0, sl=95.0, tp=120.0):
    return [
        {
            "ticket": "1",
            "symbol": "BTCUSDm",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "open_time": datetime(2024, 1, 1, 0, 0, 0),
            "pnl": 0.0,
        }
    ]


def test_break_even_trigger():
    df = _make_df(last_close=105.0)
    runner = _runner(df=df, current_price=105.1, scalping_overrides={"trailing_stop_enabled": False})

    assert runner._apply_scalping_management(_position(), now=datetime(2024, 1, 1, 0, 5, 0)) is True
    assert runner.exchange.protection_updates[-1]["sl"] == pytest.approx(100.1, rel=1e-6)
    assert runner._open_trades["1"]["touched_break_even"] is True


def test_profit_lock():
    df = _make_df(last_close=110.0)
    runner = _runner(df=df, current_price=110.2, scalping_overrides={"trailing_stop_enabled": False})

    assert runner._apply_scalping_management(_position(), now=datetime(2024, 1, 1, 0, 6, 0)) is True
    assert runner.exchange.protection_updates[-1]["sl"] == pytest.approx(108.0, rel=1e-6)
    assert runner._open_trades["1"]["profit_locked"] is True


def test_trailing_stop_ultra_aggressive():
    df = _make_df(last_close=115.0)
    runner = _runner(df=df, current_price=115.0)
    atr = runner._build_indicator_snapshot(df)["atr"]

    assert runner._apply_scalping_management(_position(), now=datetime(2024, 1, 1, 0, 7, 0)) is True
    assert runner.exchange.protection_updates[-1]["sl"] == pytest.approx(115.0 - (atr * 0.45), rel=1e-6)
    assert runner._open_trades["1"]["used_trailing"] is True


def test_intra_bar_multiple_reentries():
    df = _make_df(last_close=101.0)
    runner = _runner(df=df, current_price=101.0)
    bar_time = pd.Timestamp("2024-01-01 00:10:00")
    now = datetime(2024, 1, 1, 0, 10, 0)

    first_allowed, first_reason = runner._can_trade_on_bar("BTCUSDm", "BUY", bar_time, now, 100.0, breakout_ok=True)
    assert first_allowed is True
    assert first_reason in {"intra_bar_allowed", "bar_trade_allowed"}

    runner._mark_trade_attempt("BTCUSDm", bar_time, "BUY", now, 100.0)
    second_allowed, second_reason = runner._can_trade_on_bar(
        "BTCUSDm",
        "BUY",
        bar_time,
        now + timedelta(seconds=6),
        100.2,
        breakout_ok=True,
    )
    assert second_allowed is True
    assert second_reason == "intra_bar_allowed"


def test_trade_score_calculation():
    score = TradeReporter.calculate_trade_score(
        {
            "profit_final": 80.0,
            "max_profit_reached": 100.0,
            "max_drawdown": 10.0,
            "signal_confidence": 0.9,
            "trend_alignment_score": 0.8,
            "sl_tp_quality_score": 0.7,
        }
    )

    assert score["normalized_profit"] == 0.8
    assert score["drawdown_penalty"] == 0.1
    assert score["trade_score"] == pytest.approx(0.76, rel=1e-6)


def test_max_trades_per_bar_enforcement():
    df = _make_df(last_close=101.0)
    runner = _runner(
        df=df,
        current_price=101.0,
        intra_bar_overrides={"max_trades_per_bar": 2, "min_seconds_between_trades": 0},
    )
    bar_time = pd.Timestamp("2024-01-01 00:10:00")
    now = datetime(2024, 1, 1, 0, 10, 0)

    runner._mark_trade_attempt("BTCUSDm", bar_time, "BUY", now, 100.0)
    runner._mark_trade_attempt("BTCUSDm", bar_time, "BUY", now + timedelta(seconds=6), 100.2)
    allowed, reason = runner._can_trade_on_bar(
        "BTCUSDm",
        "BUY",
        bar_time,
        now + timedelta(seconds=12),
        100.4,
        breakout_ok=True,
    )

    assert allowed is False
    assert reason == "max_trades_per_bar"

from datetime import datetime, timedelta

from core.risk.manager import RiskManager


def test_symbol_day_lock_blocks_same_day(tmp_path):
    state_path = tmp_path / "state.json"
    rm = RiskManager({
        "one_trade_per_symbol_per_day": True,
        "state_path": str(state_path),
        "trading_timezone": "UTC",
        "daily_reset_hour": 0,
    })
    now = datetime(2026, 1, 30, 10, 0, 0)
    rm.record_trade_open(now, "XAUUSDm")
    allowed, reason = rm.allow_trade("BUY", 1.0, 2.0, None, now=now, symbol="XAUUSDm")
    assert allowed is False
    assert reason == "symbol_day_lock"


def test_symbol_day_lock_resets_next_day(tmp_path):
    state_path = tmp_path / "state.json"
    rm = RiskManager({
        "one_trade_per_symbol_per_day": True,
        "state_path": str(state_path),
        "trading_timezone": "UTC",
        "daily_reset_hour": 0,
    })
    day1 = datetime(2026, 1, 30, 10, 0, 0)
    rm.record_trade_open(day1, "XAUUSDm")
    day2 = day1 + timedelta(days=1, hours=1)
    allowed, reason = rm.allow_trade("BUY", 1.0, 2.0, None, now=day2, symbol="XAUUSDm")
    assert allowed is True


def test_daily_profit_lock_blocks_until_unlock(tmp_path):
    state_path = tmp_path / "state.json"
    rm = RiskManager({
        "daily_profit_target_usd": 30,
        "profit_lock_mode": "cooldown_hours",
        "profit_lock_hours": 6,
        "state_path": str(state_path),
        "trading_timezone": "UTC",
        "daily_reset_hour": 0,
    })
    now = datetime(2026, 1, 30, 10, 0, 0)
    rm.record_trade_close(40, now)
    allowed, reason = rm.allow_trade("BUY", 1.0, 2.0, None, now=now + timedelta(hours=1), symbol="EURUSDm")
    assert allowed is False
    assert reason == "daily_profit_lock"
    allowed2, reason2 = rm.allow_trade("BUY", 1.0, 2.0, None, now=now + timedelta(hours=7), symbol="EURUSDm")
    assert allowed2 is True

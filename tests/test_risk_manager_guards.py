from datetime import datetime, timedelta

from core.risk.manager import RiskManager


def test_daily_loss_blocks_trade():
    rm = RiskManager({"max_daily_loss_pct": 0.03})
    now = datetime(2026, 1, 30, 10, 0, 0)
    rm.update_daily(daily_pnl=-400, daily_pnl_pct=-0.04, now=now)
    allowed, reason = rm.allow_trade("BUY", 1.0, 2.0, None, now=now)
    assert allowed is False
    assert reason == "max_daily_loss_pct"


def test_consecutive_losses_block_trade():
    rm = RiskManager({"max_consecutive_losses": 2})
    now = datetime(2026, 1, 30, 10, 0, 0)
    rm.record_trade_close(-10, now)
    rm.record_trade_close(-5, now + timedelta(minutes=1))
    allowed, reason = rm.allow_trade("SELL", 1.0, 2.0, None, now=now)
    assert allowed is False
    assert reason == "max_consecutive_losses"


def test_cooldown_after_loss_blocks_trade():
    rm = RiskManager({"cooldown_minutes_after_loss": 45})
    now = datetime(2026, 1, 30, 10, 0, 0)
    rm.record_trade_close(-10, now)
    allowed, reason = rm.allow_trade("BUY", 1.0, 2.0, None, now=now + timedelta(minutes=30))
    assert allowed is False
    assert reason == "cooldown_after_loss"

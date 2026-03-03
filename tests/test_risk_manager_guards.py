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
    rm.record_trade_close(-10, now, "TESTSYM")
    rm.record_trade_close(-5, now + timedelta(minutes=1), "TESTSYM")
    allowed, reason = rm.allow_trade("SELL", 1.0, 2.0, None, now=now, symbol="TESTSYM")
    assert allowed is False
    assert reason == "max_consecutive_losses"


def test_cooldown_after_loss_blocks_trade():
    rm = RiskManager({"cooldown_minutes_after_loss": 45})
    now = datetime(2026, 1, 30, 10, 0, 0)
    rm.record_trade_close(-10, now, "TESTSYM")
    allowed, reason = rm.allow_trade("BUY", 1.0, 2.0, None, now=now + timedelta(minutes=30), symbol="TESTSYM")
    assert allowed is False
    assert reason == "symbol_cooldown_after_loss"


def test_global_open_positions_allows_other_symbol():
    rm = RiskManager({"max_global_open_positions": 2, "max_open_trades_per_symbol": 1})
    now = datetime(2026, 1, 30, 10, 0, 0)
    allowed, reason = rm.allow_trade(
        "BUY", 1.0, 2.0, None, now=now,
        symbol="BTCUSDm",
        symbol_open_positions_count=0,
        global_open_positions_count=1,
    )
    assert allowed is True


def test_global_open_positions_blocks_when_limit_reached():
    rm = RiskManager({"max_global_open_positions": 1})
    now = datetime(2026, 1, 30, 10, 0, 0)
    allowed, reason = rm.allow_trade(
        "BUY", 1.0, 2.0, None, now=now,
        symbol="BTCUSDm",
        symbol_open_positions_count=0,
        global_open_positions_count=1,
    )
    assert allowed is False
    assert reason == "blocked_by_max_global_open_positions"


def test_global_open_active_ignores_inactive_symbol_positions():
    rm = RiskManager({"max_global_open_positions": 1})
    now = datetime(2026, 1, 30, 10, 0, 0)
    allowed, reason = rm.allow_trade(
        "BUY", 1.0, 2.0, None, now=now,
        symbol="BTCUSDm",
        symbol_open_positions_count=0,
        global_open_positions_count=0,
    )
    assert allowed is True


def test_symbol_daily_loss_limit_blocks_trade():
    rm = RiskManager({
        "symbol_daily_loss_limit_usd_by_symbol": {"XAUUSDm": 20},
    })
    now = datetime(2026, 2, 24, 10, 0, 0)
    rm.record_trade_close(-12, now, "XAUUSDm")
    rm.record_trade_close(-9, now + timedelta(minutes=5), "XAUUSDm")
    allowed, reason = rm.allow_trade("BUY", 1.0, 2.0, None, now=now + timedelta(minutes=10), symbol="XAUUSDm")
    assert allowed is False
    assert reason == "symbol_daily_loss_limit_usd"


def test_safe_mode_tightens_symbol_trade_limit():
    rm = RiskManager({
        "max_trades_per_day_by_symbol": {"XAUUSDm": 4},
        "symbol_safe_mode_by_symbol": {
            "XAUUSDm": {
                "enabled_until": "2026-03-10",
                "max_trades_per_day": 2,
            }
        },
    })
    now = datetime(2026, 3, 3, 10, 0, 0)
    rm.record_trade_open(now, "XAUUSDm")
    rm.record_trade_open(now + timedelta(minutes=1), "XAUUSDm")
    allowed, reason = rm.allow_trade("BUY", 1.0, 2.0, None, now=now + timedelta(minutes=2), symbol="XAUUSDm")
    assert allowed is False
    assert reason == "max_trades_per_day_symbol"


def test_safe_mode_volume_multiplier_applies_with_base_multiplier():
    rm = RiskManager({
        "position_sizing": {
            "per_symbol": {"XAUUSDm": {"multiplier": 1.3}},
        },
        "symbol_safe_mode_by_symbol": {
            "XAUUSDm": {
                "enabled_until": "2026-03-10",
                "volume_multiplier": 0.5,
            }
        },
    })
    now = datetime(2026, 3, 3, 10, 0, 0)
    multiplier = rm.get_effective_volume_multiplier("XAUUSDm", now=now)
    assert abs(multiplier - 0.65) < 1e-9

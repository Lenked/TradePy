from datetime import datetime

from core.models import AccountSnapshot, SymbolTradeConstraints
from core.risk.manager import RiskManager


class FakeExchange:
    def get_symbol_trade_constraints(self, symbol: str):
        return SymbolTradeConstraints(
            symbol=symbol,
            min_lot=0.01,
            max_lot=10.0,
            lot_step=0.01,
            point=0.01,
            tick_size=0.01,
            tick_value=1.0,
            contract_size=1.0,
        )


def _snapshot(equity: float) -> AccountSnapshot:
    return AccountSnapshot(
        balance=equity,
        equity=equity,
        margin=0.0,
        free_margin=equity,
    )


def test_position_size_scales_with_equity():
    rm = RiskManager(
        {
            "position_sizing": {
                "defaults": {
                    "base_lot": 0.01,
                    "risk_per_trade_pct": 0.01,
                    "confidence_floor": 1.0,
                    "confidence_ceiling": 1.0,
                },
                "max_lot": 10.0,
            }
        }
    )
    exchange = FakeExchange()

    small_volume = rm.compute_position_size(
        "XAUUSDm",
        _snapshot(1000.0),
        entry_price=2000.0,
        sl_price=1990.0,
        exchange=exchange,
        confidence=1.0,
    )
    large_volume = rm.compute_position_size(
        "XAUUSDm",
        _snapshot(10000.0),
        entry_price=2000.0,
        sl_price=1990.0,
        exchange=exchange,
        confidence=1.0,
    )

    assert small_volume == 0.01
    assert large_volume == 0.10
    assert large_volume > small_volume


def test_position_size_uses_confidence_and_symbol_multiplier():
    rm = RiskManager(
        {
            "position_sizing": {
                "defaults": {
                    "base_lot": 0.01,
                    "risk_per_trade_pct": 0.01,
                    "confidence_floor": 0.80,
                    "confidence_ceiling": 1.20,
                },
                "per_symbol": {
                    "BTCUSDm": {
                        "multiplier": 1.5,
                    }
                },
                "max_lot": 10.0,
            }
        }
    )
    exchange = FakeExchange()

    low_conf_volume = rm.compute_position_size(
        "BTCUSDm",
        _snapshot(10000.0),
        entry_price=100.0,
        sl_price=99.0,
        exchange=exchange,
        confidence=0.0,
    )
    high_conf_volume = rm.compute_position_size(
        "BTCUSDm",
        _snapshot(10000.0),
        entry_price=100.0,
        sl_price=99.0,
        exchange=exchange,
        confidence=1.0,
    )

    assert low_conf_volume == 1.20
    assert high_conf_volume == 1.80
    assert high_conf_volume > low_conf_volume


def test_position_size_respects_safe_mode_multiplier_and_max_lot():
    rm = RiskManager(
        {
            "position_sizing": {
                "defaults": {
                    "base_lot": 0.01,
                    "risk_per_trade_pct": 0.05,
                    "confidence_floor": 1.0,
                    "confidence_ceiling": 1.0,
                },
                "per_symbol": {
                    "XAUUSDm": {
                        "multiplier": 2.0,
                    }
                },
                "max_lot": 0.30,
            },
            "symbol_safe_mode_by_symbol": {
                "XAUUSDm": {
                    "enabled_until": "2026-03-10",
                    "volume_multiplier": 0.5,
                }
            },
        }
    )
    exchange = FakeExchange()

    volume = rm.compute_position_size(
        "XAUUSDm",
        _snapshot(50000.0),
        entry_price=2000.0,
        sl_price=1999.0,
        exchange=exchange,
        now=datetime(2026, 3, 3, 10, 0, 0),
        confidence=1.0,
    )

    assert volume == 0.30


def test_wide_setup_reduces_position_size():
    rm = RiskManager(
        {
            "position_sizing": {
                "defaults": {
                    "base_lot": 0.01,
                    "risk_per_trade_pct": 0.01,
                    "confidence_floor": 1.0,
                    "confidence_ceiling": 1.0,
                    "soft_max_sl_distance_pct": 0.02,
                    "soft_max_tp_distance_pct": 0.02,
                    "hard_max_sl_distance_pct": 0.10,
                    "hard_max_tp_distance_pct": 0.10,
                    "wide_distance_min_factor": 0.20,
                },
                "max_lot": 10.0,
            }
        }
    )
    exchange = FakeExchange()

    narrow_volume = rm.compute_position_size(
        "BTCUSDm",
        _snapshot(10000.0),
        entry_price=100.0,
        sl_price=99.0,
        tp_price=101.0,
        exchange=exchange,
        confidence=1.0,
    )
    wide_volume = rm.compute_position_size(
        "BTCUSDm",
        _snapshot(10000.0),
        entry_price=100.0,
        sl_price=97.0,
        tp_price=104.0,
        exchange=exchange,
        confidence=1.0,
    )

    assert narrow_volume == 1.00
    assert wide_volume == 0.11
    assert wide_volume < narrow_volume


def test_hard_wide_setup_limit_blocks_trade_volume():
    rm = RiskManager(
        {
            "position_sizing": {
                "defaults": {
                    "base_lot": 0.01,
                    "risk_per_trade_pct": 0.01,
                    "confidence_floor": 1.0,
                    "confidence_ceiling": 1.0,
                    "soft_max_sl_distance_pct": 0.02,
                    "soft_max_tp_distance_pct": 0.03,
                    "hard_max_sl_distance_pct": 0.04,
                    "hard_max_tp_distance_pct": 0.05,
                    "wide_distance_min_factor": 0.20,
                },
                "max_lot": 10.0,
            }
        }
    )
    exchange = FakeExchange()

    volume = rm.compute_position_size(
        "BTCUSDm",
        _snapshot(10000.0),
        entry_price=100.0,
        sl_price=97.0,
        tp_price=107.0,
        exchange=exchange,
        confidence=1.0,
    )

    assert volume == 0.0

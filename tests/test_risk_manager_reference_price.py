from datetime import datetime

from core.risk.manager import RiskManager


class Snapshot:
    balance = 10000.0
    equity = 10000.0


def test_allow_trade_prefers_explicit_reference_price_for_wide_setup_checks():
    rm = RiskManager(
        {
            "position_sizing": {
                "defaults": {
                    "hard_max_sl_distance_pct": 0.03,
                    "hard_max_tp_distance_pct": 0.06,
                }
            }
        }
    )

    allowed, reason = rm.allow_trade(
        "BUY",
        sl=97.0,
        tp=106.0,
        account_snapshot=Snapshot(),
        symbol="BTCUSDm",
        reference_price=100.0,
        now=datetime(2026, 4, 6, 0, 5, 0),
    )

    assert allowed is True
    assert reason in {"No risk rules configured", "Trade allowed by risk management"}

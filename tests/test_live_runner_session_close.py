from datetime import datetime

from core.models import OrderResult
from live.runner import LiveRunner


class DummyExchange:
    dry_run = False

    def __init__(self):
        self.close_calls = []

    def close_position(self, ticket, symbol, volume, side, comment="TradePy Session End"):
        self.close_calls.append(
            {
                "ticket": ticket,
                "symbol": symbol,
                "volume": volume,
                "side": side,
                "comment": comment,
            }
        )
        return OrderResult(
            success=True,
            order_id=str(ticket),
            message="position_closed",
            details={"profit": 12.5},
        )


class ClosedSessionRiskManager:
    def get_effective_trading_session(self, symbol=None):
        return {
            "enabled": True,
            "start_hour": 16,
            "start_minute": 0,
            "end_hour": 23,
            "end_minute": 0,
        }

    def is_within_trading_session(self, now, symbol=None):
        return False


class OpenSessionRiskManager(ClosedSessionRiskManager):
    def is_within_trading_session(self, now, symbol=None):
        return True


def _position(ticket="1", symbol="XAUUSDm", side="BUY", volume=0.1):
    return {
        "ticket": ticket,
        "symbol": symbol,
        "side": side,
        "volume": volume,
        "profit": 0.0,
        "open_time": datetime(2026, 4, 12, 18, 0, 0),
    }


def test_close_positions_outside_session_triggers_market_close():
    exchange = DummyExchange()
    runner = LiveRunner(strategy=None, exchange=exchange, risk_manager=ClosedSessionRiskManager())
    positions = [_position()]
    runner._sync_positions(positions)

    closed = runner._close_positions_outside_session(positions, now=datetime(2026, 4, 12, 23, 30, 0))

    assert closed is True
    assert len(exchange.close_calls) == 1
    assert exchange.close_calls[0]["ticket"] == "1"
    assert runner._open_positions_snapshot["1"]["profit"] == 12.5


def test_close_positions_outside_session_skips_when_session_still_open():
    exchange = DummyExchange()
    runner = LiveRunner(strategy=None, exchange=exchange, risk_manager=OpenSessionRiskManager())
    positions = [_position()]
    runner._sync_positions(positions)

    closed = runner._close_positions_outside_session(positions, now=datetime(2026, 4, 12, 21, 0, 0))

    assert closed is False
    assert exchange.close_calls == []

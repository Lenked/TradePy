from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Optional, Dict
import os
import csv

try:
    from ..utils.logger import get_logger
except ImportError:
    from utils.logger import get_logger


@dataclass
class ClosedTrade:
    trade_id: str
    symbol: str
    side: str
    volume: float
    open_time: Optional[datetime]
    close_time: datetime
    pnl: float


class TradeReporter:
    def __init__(self, reports_dir: str = "reports"):
        self.reports_dir = reports_dir
        self._closed_trades: List[ClosedTrade] = []
        self.logger = get_logger("TradeReporter")

    def record_trade_close(self, trade_id: str, symbol: str, side: str, volume: float,
                           open_time: Optional[datetime], close_time: datetime, pnl: float):
        self._closed_trades.append(
            ClosedTrade(
                trade_id=str(trade_id),
                symbol=str(symbol),
                side=str(side),
                volume=float(volume),
                open_time=open_time,
                close_time=close_time,
                pnl=float(pnl),
            )
        )

    def _get_trades_for_day(self, day: date) -> List[ClosedTrade]:
        return [t for t in self._closed_trades if t.close_time.date() == day]

    def build_daily_summary(self, day: date) -> Dict[str, float]:
        trades = self._get_trades_for_day(day)
        total_trades = len(trades)
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        net_pnl = sum(t.pnl for t in trades)

        winrate = (len(wins) / total_trades) if total_trades else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
        expectancy = (net_pnl / total_trades) if total_trades else 0.0
        avg_win = (gross_profit / len(wins)) if wins else 0.0
        avg_loss = (-gross_loss / len(losses)) if losses else 0.0

        # Max drawdown from cumulative pnl
        max_drawdown = 0.0
        peak = 0.0
        cumulative = 0.0
        for trade in sorted(trades, key=lambda t: t.close_time):
            cumulative += trade.pnl
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        pnl_by_symbol: Dict[str, float] = {}
        pnl_by_hour: Dict[int, float] = {}
        for trade in trades:
            pnl_by_symbol[trade.symbol] = pnl_by_symbol.get(trade.symbol, 0.0) + trade.pnl
            hour = trade.close_time.hour
            pnl_by_hour[hour] = pnl_by_hour.get(hour, 0.0) + trade.pnl

        summary = {
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "winrate": winrate,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_drawdown": max_drawdown,
            "net_pnl": net_pnl,
        }

        for symbol, pnl in pnl_by_symbol.items():
            summary[f"pnl_symbol_{symbol}"] = pnl
        for hour, pnl in pnl_by_hour.items():
            summary[f"pnl_hour_{hour:02d}"] = pnl

        return summary

    def export_daily_report(self, day: date):
        trades = self._get_trades_for_day(day)
        summary = self.build_daily_summary(day)

        os.makedirs(self.reports_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = os.path.join(self.reports_dir, f"report_summary_{day}_{ts}.csv")
        trades_path = os.path.join(self.reports_dir, f"report_trades_{day}_{ts}.csv")

        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            for key, value in summary.items():
                writer.writerow([key, value])

        with open(trades_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["trade_id", "symbol", "side", "volume", "open_time", "close_time", "pnl"])
            for trade in trades:
                writer.writerow([
                    trade.trade_id,
                    trade.symbol,
                    trade.side,
                    trade.volume,
                    trade.open_time,
                    trade.close_time,
                    trade.pnl,
                ])

        self.logger.info(f"REPORT_DAILY_SUMMARY - day={day} trades={len(trades)} file={summary_path}")
        return summary, summary_path, trades_path

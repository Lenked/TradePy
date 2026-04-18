from dataclasses import asdict, dataclass
from datetime import datetime, date
from typing import Any, Dict, List, Optional
import csv
import json
import os

try:
    from ..utils.logger import get_logger
except ImportError:
    from utils.logger import get_logger


@dataclass
class TradeHistory:
    trade_id: str
    symbol: str
    side: str
    volume: float
    open_time: Optional[datetime]
    close_time: datetime
    pnl: float
    spread: float = 0.0
    atr: float = 0.0
    rsi: float = 0.0
    volume_ratio: float = 0.0
    signal_force: float = 0.0
    signal_confidence: float = 0.0
    trend_alignment_score: float = 0.0
    sl_tp_quality_score: float = 0.0
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    max_drawdown: float = 0.0
    max_profit_reached: float = 0.0
    profit_final: float = 0.0
    duration_seconds: float = 0.0
    exit_reason: str = ""
    touched_be: bool = False
    profit_locked: bool = False
    used_trailing: bool = False
    momentum_reversal: bool = False
    bars_held: int = 0
    reentry_count_same_bar: int = 0
    normalized_profit: float = 0.0
    drawdown_penalty: float = 0.0
    trade_score: float = 0.0
    timeframe_key: str = "default"
    signal_bucket: str = ""


ClosedTrade = TradeHistory


class TradeReporter:
    def __init__(self, reports_dir: str = "reports"):
        self.reports_dir = reports_dir
        self.history_jsonl_path = os.path.join(reports_dir, "trade_history.jsonl")
        self.history_csv_path = os.path.join(reports_dir, "trade_history.csv")
        self._closed_trades: List[TradeHistory] = []
        self.logger = get_logger("TradeReporter")

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @staticmethod
    def _signal_bucket(signal_force: float) -> str:
        force = float(signal_force or 0.0)
        if force >= 0.75:
            return "ultra"
        if force >= 0.55:
            return "strong"
        if force >= 0.35:
            return "medium"
        return "weak"

    @classmethod
    def calculate_trade_score(cls, payload: Dict[str, Any]) -> Dict[str, float]:
        profit_final = cls._safe_float(payload.get("profit_final", payload.get("pnl", 0.0)))
        max_profit_reached = max(cls._safe_float(payload.get("max_profit_reached", 0.0)), abs(profit_final), 1e-6)
        max_drawdown = max(0.0, cls._safe_float(payload.get("max_drawdown", 0.0)))
        signal_confidence = max(0.0, min(1.0, cls._safe_float(payload.get("signal_confidence", 0.0))))
        trend_alignment_score = max(0.0, min(1.0, cls._safe_float(payload.get("trend_alignment_score", 0.0))))
        sl_tp_quality_score = max(0.0, min(1.0, cls._safe_float(payload.get("sl_tp_quality_score", 0.0))))
        normalized_profit = max(-1.0, min(1.0, profit_final / max_profit_reached))
        drawdown_penalty = max(0.0, min(1.0, max_drawdown / max_profit_reached))

        trade_score = (
            normalized_profit * 0.60
            + signal_confidence * 0.15
            + trend_alignment_score * 0.10
            + sl_tp_quality_score * 0.10
            - drawdown_penalty * 0.05
        )
        return {
            "normalized_profit": float(normalized_profit),
            "drawdown_penalty": float(drawdown_penalty),
            "trade_score": float(trade_score),
        }

    def _ensure_reports_dir(self) -> None:
        os.makedirs(self.reports_dir, exist_ok=True)

    def _append_history_files(self, trade: TradeHistory) -> None:
        self._ensure_reports_dir()
        row = asdict(trade)
        serialized = {key: self._serialize_value(value) for key, value in row.items()}

        with open(self.history_jsonl_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(serialized, ensure_ascii=True) + "\n")

        write_header = not os.path.exists(self.history_csv_path) or os.path.getsize(self.history_csv_path) == 0
        with open(self.history_csv_path, "a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(serialized.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(serialized)

    def record_trade_close(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        volume: float,
        open_time: Optional[datetime],
        close_time: datetime,
        pnl: float,
        **metadata: Any,
    ):
        profit_final = self._safe_float(metadata.get("profit_final", pnl))
        duration_seconds = self._safe_float(metadata.get("duration_seconds"))
        if duration_seconds <= 0 and open_time is not None:
            duration_seconds = max(0.0, (close_time - open_time).total_seconds())

        payload: Dict[str, Any] = {
            "trade_id": str(trade_id),
            "symbol": str(symbol),
            "side": str(side),
            "volume": self._safe_float(volume),
            "open_time": open_time,
            "close_time": close_time,
            "pnl": self._safe_float(pnl),
            "spread": self._safe_float(metadata.get("spread")),
            "atr": self._safe_float(metadata.get("atr")),
            "rsi": self._safe_float(metadata.get("rsi")),
            "volume_ratio": self._safe_float(metadata.get("volume_ratio"), 1.0),
            "signal_force": self._safe_float(metadata.get("signal_force")),
            "signal_confidence": self._safe_float(metadata.get("signal_confidence")),
            "trend_alignment_score": self._safe_float(metadata.get("trend_alignment_score")),
            "sl_tp_quality_score": self._safe_float(metadata.get("sl_tp_quality_score")),
            "entry_price": self._safe_float(metadata.get("entry_price")),
            "exit_price": self._safe_float(metadata.get("exit_price")),
            "sl": self._safe_float(metadata.get("sl")),
            "tp": self._safe_float(metadata.get("tp")),
            "max_drawdown": max(0.0, self._safe_float(metadata.get("max_drawdown"))),
            "max_profit_reached": max(0.0, self._safe_float(metadata.get("max_profit_reached"))),
            "profit_final": profit_final,
            "duration_seconds": duration_seconds,
            "exit_reason": str(metadata.get("exit_reason", "")),
            "touched_be": bool(metadata.get("touched_be", False)),
            "profit_locked": bool(metadata.get("profit_locked", False)),
            "used_trailing": bool(metadata.get("used_trailing", False)),
            "momentum_reversal": bool(metadata.get("momentum_reversal", False)),
            "bars_held": int(metadata.get("bars_held", 0) or 0),
            "reentry_count_same_bar": int(metadata.get("reentry_count_same_bar", 0) or 0),
            "timeframe_key": str(metadata.get("timeframe_key", "default")),
        }

        payload.update(self.calculate_trade_score(payload))
        payload["signal_bucket"] = self._signal_bucket(payload["signal_force"])
        trade = TradeHistory(**payload)
        self._closed_trades.append(trade)
        self._append_history_files(trade)

        self.logger.info(
            f"TRADE_SCORE_CALCULATED - TradeID: {trade.trade_id} | Symbol: {trade.symbol} | "
            f"Score: {trade.trade_score:.4f} | NormalizedProfit: {trade.normalized_profit:.4f} | "
            f"DrawdownPenalty: {trade.drawdown_penalty:.4f}"
        )
        if trade.trade_score >= 0.70:
            self.logger.info(
                f"BEST_SETUP_DETECTED - Symbol: {trade.symbol} | Side: {trade.side} | "
                f"Hour: {trade.close_time.hour:02d} | Score: {trade.trade_score:.4f} | Exit: {trade.exit_reason}"
            )
        elif trade.trade_score <= 0.20:
            self.logger.info(
                f"WEAK_SETUP_DETECTED - Symbol: {trade.symbol} | Side: {trade.side} | "
                f"Hour: {trade.close_time.hour:02d} | Score: {trade.trade_score:.4f} | Exit: {trade.exit_reason}"
            )

    def _get_trades_for_day(self, day: date) -> List[TradeHistory]:
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

        for symbol, pnl_value in pnl_by_symbol.items():
            summary[f"pnl_symbol_{symbol}"] = pnl_value
        for hour, pnl_value in pnl_by_hour.items():
            summary[f"pnl_hour_{hour:02d}"] = pnl_value

        return summary

    def export_daily_report(self, day: date):
        trades = self._get_trades_for_day(day)
        summary = self.build_daily_summary(day)

        self._ensure_reports_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = os.path.join(self.reports_dir, f"report_summary_{day}_{ts}.csv")
        trades_path = os.path.join(self.reports_dir, f"report_trades_{day}_{ts}.csv")

        with open(summary_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["metric", "value"])
            for key, value in summary.items():
                writer.writerow([key, value])

        with open(trades_path, "w", newline="", encoding="utf-8") as handle:
            rows = [asdict(trade) for trade in trades]
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: self._serialize_value(v) for k, v in row.items()})

        self.logger.info(f"REPORT_DAILY_SUMMARY - day={day} trades={len(trades)} file={summary_path}")
        return summary, summary_path, trades_path

    def analyze_best_setups(self, history_path: Optional[str] = None, top_n: int = 10) -> List[Dict[str, Any]]:
        source = history_path or (self.history_jsonl_path if os.path.exists(self.history_jsonl_path) else self.history_csv_path)
        if not source or not os.path.exists(source):
            return []

        try:
            import pandas as pd
        except Exception:
            return []

        if source.endswith(".jsonl"):
            rows: List[Dict[str, Any]] = []
            with open(source, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    rows.append(json.loads(line))
            if not rows:
                return []
            df = pd.DataFrame(rows)
        else:
            df = pd.read_csv(source)

        if df.empty:
            return []

        df["close_time"] = pd.to_datetime(df["close_time"], errors="coerce")
        df["entry_hour"] = df["close_time"].dt.hour.fillna(-1).astype(int)
        for column in (
            "trade_score",
            "pnl",
            "duration_seconds",
            "signal_force",
            "max_drawdown",
            "signal_confidence",
        ):
            if column in df.columns:
                df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)

        group_cols = ["symbol", "entry_hour", "signal_bucket", "side"]
        grouped = (
            df.groupby(group_cols, dropna=False)
            .agg(
                trades=("trade_id", "count"),
                avg_score=("trade_score", "mean"),
                avg_profit=("pnl", "mean"),
                win_rate=("pnl", lambda values: float((values > 0).mean())),
                avg_duration_seconds=("duration_seconds", "mean"),
                avg_signal_force=("signal_force", "mean"),
                avg_max_drawdown=("max_drawdown", "mean"),
            )
            .reset_index()
            .sort_values(["avg_score", "avg_profit", "win_rate"], ascending=[False, False, False])
        )

        top = grouped.head(top_n)
        weak = grouped.tail(min(3, len(grouped)))
        results = top.to_dict(orient="records")

        for row in results:
            self.logger.info(
                f"BEST_SETUP_DETECTED - Symbol: {row['symbol']} | Hour: {int(row['entry_hour']):02d} | "
                f"Bucket: {row['signal_bucket']} | AvgScore: {row['avg_score']:.4f} | "
                f"WinRate: {row['win_rate']:.2%} | Trades: {int(row['trades'])}"
            )
        for row in weak.to_dict(orient="records"):
            self.logger.info(
                f"WEAK_SETUP_DETECTED - Symbol: {row['symbol']} | Hour: {int(row['entry_hour']):02d} | "
                f"Bucket: {row['signal_bucket']} | AvgScore: {row['avg_score']:.4f} | "
                f"WinRate: {row['win_rate']:.2%} | Trades: {int(row['trades'])}"
            )

        return results

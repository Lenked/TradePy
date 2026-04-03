"""
Build an offline phase-A training dataset from dashboard API payloads.

This builder creates a "trade regime" dataset:
- One row per realized closed trade.
- Features use only information available before that trade outcome.
- Labels describe the realized result of the trade.

The source payload is expected to be the JSON response saved from the dashboard API,
for example ``data/dashboard.json``.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd


WINDOWS: Sequence[int] = (5, 10, 20, 50)
PROFIT_FACTOR_CAP = 10.0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _profit_factor(values: Iterable[float]) -> float:
    profits = 0.0
    losses = 0.0
    count = 0
    for value in values:
        pnl = _safe_float(value)
        count += 1
        if pnl > 0:
            profits += pnl
        elif pnl < 0:
            losses += abs(pnl)

    if count == 0:
        return 0.0
    if losses == 0:
        return PROFIT_FACTOR_CAP if profits > 0 else 0.0
    return min(profits / losses, PROFIT_FACTOR_CAP)


def _stdev(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    series = pd.Series(values, dtype=float)
    return float(series.std(ddof=0))


@dataclass
class PerformanceTracker:
    """Track realized performance before the current trade."""

    windows: Sequence[int]
    history: List[float]
    trade_count: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    breakeven_count: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    equity: float = 0.0
    equity_peak: float = 0.0
    current_drawdown: float = 0.0
    max_drawdown: float = 0.0

    def __init__(self, windows: Sequence[int]):
        self.windows = windows
        self.history = []

    def snapshot(self, prefix: str) -> Dict[str, float]:
        features = {
            f"{prefix}trade_count_before": float(self.trade_count),
            f"{prefix}total_pnl_before": round(self.total_pnl, 6),
            f"{prefix}avg_pnl_before": round(self.total_pnl / self.trade_count, 6) if self.trade_count else 0.0,
            f"{prefix}win_rate_before": round(self.win_count / self.trade_count, 6) if self.trade_count else 0.0,
            f"{prefix}profit_factor_before": round(_profit_factor(self.history), 6),
            f"{prefix}consecutive_wins_before": float(self.consecutive_wins),
            f"{prefix}consecutive_losses_before": float(self.consecutive_losses),
            f"{prefix}current_drawdown_before": round(self.current_drawdown, 6),
            f"{prefix}max_drawdown_before": round(self.max_drawdown, 6),
        }

        for window in self.windows:
            recent = self.history[-window:]
            count = len(recent)
            wins = sum(1 for value in recent if value > 0)
            losses = sum(1 for value in recent if value < 0)
            features[f"{prefix}pnl_{window}_before"] = round(sum(recent), 6) if recent else 0.0
            features[f"{prefix}avg_pnl_{window}_before"] = round(sum(recent) / count, 6) if count else 0.0
            features[f"{prefix}win_rate_{window}_before"] = round(wins / count, 6) if count else 0.0
            features[f"{prefix}loss_rate_{window}_before"] = round(losses / count, 6) if count else 0.0
            features[f"{prefix}profit_factor_{window}_before"] = round(_profit_factor(recent), 6)
            features[f"{prefix}pnl_std_{window}_before"] = round(_stdev(recent), 6)

        return features

    def update(self, pnl: float) -> None:
        pnl = _safe_float(pnl)
        self.history.append(pnl)
        self.trade_count += 1
        self.total_pnl += pnl

        if pnl > 0:
            self.gross_profit += pnl
            self.win_count += 1
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.gross_loss += abs(pnl)
            self.loss_count += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0
        else:
            self.breakeven_count += 1
            self.consecutive_wins = 0
            self.consecutive_losses = 0

        self.equity += pnl
        self.equity_peak = max(self.equity_peak, self.equity)
        self.current_drawdown = self.equity - self.equity_peak
        self.max_drawdown = min(self.max_drawdown, self.current_drawdown)


def load_dashboard_payload(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_dashboard_deals(payload: Dict[str, Any]) -> pd.DataFrame:
    history = payload.get("history", {})
    deals = history.get("deals", [])
    if not isinstance(deals, list):
        raise ValueError("dashboard payload is missing history.deals list")
    if not deals:
        return pd.DataFrame()

    df = pd.DataFrame(deals).copy()
    required = {"time", "symbol", "type", "volume", "profit"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"dashboard deals missing required fields: {sorted(missing)}")

    for column in ("volume", "profit", "commission", "swap", "price", "magic", "entry_type", "order", "ticket"):
        if column not in df.columns:
            df[column] = 0

    df["close_time"] = pd.to_datetime(df["time"], errors="coerce", utc=False)
    df = df[df["close_time"].notna()].copy()
    df.sort_values(["close_time", "ticket", "order"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    df["symbol"] = df["symbol"].astype(str)
    df["side"] = df["type"].astype(str).str.upper()
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    df["profit"] = pd.to_numeric(df["profit"], errors="coerce").fillna(0.0)
    df["commission"] = pd.to_numeric(df["commission"], errors="coerce").fillna(0.0)
    df["swap"] = pd.to_numeric(df["swap"], errors="coerce").fillna(0.0)
    df["net_profit"] = df["profit"] + df["commission"] + df["swap"]
    df["abs_net_profit"] = df["net_profit"].abs()
    df["net_profit_per_lot"] = df.apply(
        lambda row: row["net_profit"] / row["volume"] if row["volume"] else 0.0,
        axis=1,
    )

    df["is_buy"] = (df["side"] == "BUY").astype(int)
    df["is_sell"] = (df["side"] == "SELL").astype(int)
    df["volume_log"] = df["volume"].apply(lambda value: math.log(value) if value and value > 0 else 0.0)
    df["magic_is_tradepy"] = (pd.to_numeric(df["magic"], errors="coerce").fillna(0).astype(int) == 234000).astype(int)
    df["close_date"] = df["close_time"].dt.strftime("%Y-%m-%d")
    df["close_hour"] = df["close_time"].dt.hour
    df["close_weekday"] = df["close_time"].dt.weekday
    df["close_month"] = df["close_time"].dt.month
    df["comment"] = df.get("comment", "").fillna("").astype(str)
    df["comment_has_tp_tag"] = df["comment"].str.contains(r"\[tp", case=False, regex=True).astype(int)
    df["comment_has_sl_tag"] = df["comment"].str.contains(r"\[sl", case=False, regex=True).astype(int)
    df["label_win"] = (df["net_profit"] > 0).astype(int)
    df["label_loss"] = (df["net_profit"] < 0).astype(int)
    df["label_big_win"] = (df["net_profit"] >= 10.0).astype(int)
    df["label_big_loss"] = (df["net_profit"] <= -10.0).astype(int)
    return df


def build_trade_regime_dataset(deals_df: pd.DataFrame) -> pd.DataFrame:
    if deals_df.empty:
        return pd.DataFrame()

    global_tracker = PerformanceTracker(WINDOWS)
    symbol_trackers: Dict[str, PerformanceTracker] = defaultdict(lambda: PerformanceTracker(WINDOWS))
    side_trackers: Dict[str, PerformanceTracker] = defaultdict(lambda: PerformanceTracker(WINDOWS))

    rows: List[Dict[str, Any]] = []
    for index, row in deals_df.iterrows():
        symbol = str(row["symbol"])
        side = str(row["side"])
        net_profit = _safe_float(row["net_profit"])

        feature_row: Dict[str, Any] = {
            "dataset_row_id": int(index),
            "meta_close_time": row["close_time"].isoformat(),
            "meta_close_date": row["close_date"],
            "meta_ticket": int(_safe_float(row["ticket"])),
            "meta_order": int(_safe_float(row["order"])),
            "meta_comment": row["comment"],
            "symbol": symbol,
            "side": side,
            "volume": _safe_float(row["volume"]),
            "volume_log": _safe_float(row["volume_log"]),
            "magic_is_tradepy": int(row["magic_is_tradepy"]),
            "trade_count_before": float(global_tracker.trade_count),
        }

        feature_row.update(global_tracker.snapshot("global_"))
        feature_row.update(symbol_trackers[symbol].snapshot("symbol_"))
        feature_row.update(side_trackers[side].snapshot("side_"))

        feature_row.update(
            {
                "label_win": int(row["label_win"]),
                "label_loss": int(row["label_loss"]),
                "label_big_win": int(row["label_big_win"]),
                "label_big_loss": int(row["label_big_loss"]),
                "target_net_profit": round(net_profit, 6),
                "target_abs_net_profit": round(_safe_float(row["abs_net_profit"]), 6),
                "target_net_profit_per_lot": round(_safe_float(row["net_profit_per_lot"]), 6),
                "meta_close_hour": int(row["close_hour"]),
                "meta_close_weekday": int(row["close_weekday"]),
                "meta_close_month": int(row["close_month"]),
                "meta_price": round(_safe_float(row["price"]), 6),
                "meta_comment_has_tp_tag": int(row["comment_has_tp_tag"]),
                "meta_comment_has_sl_tag": int(row["comment_has_sl_tag"]),
                "meta_profit": round(_safe_float(row["profit"]), 6),
                "meta_commission": round(_safe_float(row["commission"]), 6),
                "meta_swap": round(_safe_float(row["swap"]), 6),
                "meta_entry_type": int(_safe_float(row["entry_type"])),
            }
        )
        rows.append(feature_row)

        global_tracker.update(net_profit)
        symbol_trackers[symbol].update(net_profit)
        side_trackers[side].update(net_profit)

    return pd.DataFrame(rows)


def build_dataset_summary(dataset_df: pd.DataFrame, payload: Dict[str, Any]) -> Dict[str, Any]:
    if dataset_df.empty:
        return {
            "row_count": 0,
            "feature_columns": [],
            "label_columns": [],
            "meta_columns": [],
            "categorical_columns": [],
        }

    label_columns = [
        "label_win",
        "label_loss",
        "label_big_win",
        "label_big_loss",
        "target_net_profit",
        "target_abs_net_profit",
        "target_net_profit_per_lot",
    ]
    meta_columns = [column for column in dataset_df.columns if column.startswith("meta_")]
    feature_columns = [column for column in dataset_df.columns if column not in set(label_columns + meta_columns)]
    categorical_columns = ["symbol", "side"]

    label_win_rate = float(dataset_df["label_win"].mean()) if "label_win" in dataset_df else 0.0
    label_big_loss_rate = float(dataset_df["label_big_loss"].mean()) if "label_big_loss" in dataset_df else 0.0

    return {
        "source": "dashboard.json",
        "payload_generated_at": payload.get("generated_at"),
        "period_days": payload.get("period_days") or payload.get("history", {}).get("period_days"),
        "row_count": int(len(dataset_df)),
        "feature_columns": feature_columns,
        "label_columns": label_columns,
        "meta_columns": meta_columns,
        "categorical_columns": categorical_columns,
        "notes": [
            "Dataset phase A built from realized dashboard deals only.",
            "Time-of-close and exit comment columns are stored as meta, not intended as training features.",
            "Features are computed from prior realized trades to avoid direct outcome leakage.",
            "This v1 dataset is best suited for a meta-model that filters or throttles trades.",
        ],
        "class_balance": {
            "label_win_rate": round(label_win_rate, 6),
            "label_big_loss_rate": round(label_big_loss_rate, 6),
        },
        "payload_metrics": payload.get("metrics", {}),
    }


def build_and_save_dashboard_dataset(
    input_path: Path,
    dataset_csv_path: Path,
    summary_json_path: Path,
    normalized_csv_path: Path | None = None,
) -> Dict[str, Any]:
    payload = load_dashboard_payload(input_path)
    normalized_df = normalize_dashboard_deals(payload)
    dataset_df = build_trade_regime_dataset(normalized_df)
    summary = build_dataset_summary(dataset_df, payload)

    dataset_csv_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_df.to_csv(dataset_csv_path, index=False)

    if normalized_csv_path is not None:
        normalized_csv_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_df.to_csv(normalized_csv_path, index=False)

    with summary_json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=True, indent=2)

    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build training dataset from dashboard.json")
    parser.add_argument("--input", default="data/dashboard.json", help="Path to dashboard payload JSON")
    parser.add_argument(
        "--dataset-output",
        default="data/processed/dashboard_trade_regime_dataset.csv",
        help="Output CSV path for the training dataset",
    )
    parser.add_argument(
        "--summary-output",
        default="data/processed/dashboard_trade_regime_dataset_summary.json",
        help="Output JSON path for dataset summary metadata",
    )
    parser.add_argument(
        "--normalized-output",
        default="data/processed/dashboard_deals_normalized.csv",
        help="Optional CSV path for normalized raw deals",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = build_and_save_dashboard_dataset(
        input_path=Path(args.input),
        dataset_csv_path=Path(args.dataset_output),
        summary_json_path=Path(args.summary_output),
        normalized_csv_path=Path(args.normalized_output) if args.normalized_output else None,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

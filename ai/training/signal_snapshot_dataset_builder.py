"""
Build a dataset from live signal snapshot JSONL events.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


def load_snapshot_events(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def build_signal_snapshot_dataset(events: List[Dict[str, Any]]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()

    signal_rows = [event for event in events if event.get("event_type") == "signal_snapshot"]
    opened_by_snapshot = {
        event.get("snapshot_id"): event
        for event in events
        if event.get("event_type") == "trade_opened" and event.get("snapshot_id")
    }
    closed_by_snapshot = {
        event.get("snapshot_id"): event
        for event in events
        if event.get("event_type") == "trade_closed" and event.get("snapshot_id")
    }

    rows: List[Dict[str, Any]] = []
    for event in signal_rows:
        snapshot_id = event.get("snapshot_id")
        opened = opened_by_snapshot.get(snapshot_id, {})
        closed = closed_by_snapshot.get(snapshot_id, {})

        row = dict(event)
        row["trade_opened"] = bool(opened)
        row["trade_closed"] = bool(closed)
        row["trade_id"] = opened.get("trade_id") or closed.get("trade_id")
        row["trade_open_time"] = opened.get("open_time")
        row["trade_close_time"] = closed.get("close_time")
        row["trade_pnl"] = float(closed.get("pnl", 0.0) or 0.0) if closed else 0.0
        row["label_trade_win"] = int(row["trade_closed"] and row["trade_pnl"] > 0)
        row["label_trade_loss"] = int(row["trade_closed"] and row["trade_pnl"] < 0)
        row["label_trade_big_loss"] = int(row["trade_closed"] and row["trade_pnl"] <= -10.0)
        rows.append(row)

    dataset = pd.DataFrame(rows)
    if dataset.empty:
        return dataset

    dataset.sort_values(["event_time", "snapshot_id"], inplace=True, ignore_index=True)
    return dataset


def build_snapshot_summary(dataset: pd.DataFrame) -> Dict[str, Any]:
    if dataset.empty:
        return {
            "row_count": 0,
            "trade_opened_rate": 0.0,
            "trade_closed_rate": 0.0,
            "win_rate_on_closed": 0.0,
        }

    closed = dataset[dataset["trade_closed"] == True].copy()
    closed_win_rate = float(closed["label_trade_win"].mean()) if not closed.empty else 0.0
    return {
        "row_count": int(len(dataset)),
        "trade_opened_rate": round(float(dataset["trade_opened"].mean()), 6),
        "trade_closed_rate": round(float(dataset["trade_closed"].mean()), 6),
        "win_rate_on_closed": round(closed_win_rate, 6),
        "feature_columns": [column for column in dataset.columns if column not in {"event_type"}],
    }


def build_and_save_signal_snapshot_dataset(input_path: Path, dataset_path: Path, summary_path: Path) -> Dict[str, Any]:
    events = load_snapshot_events(input_path)
    dataset = build_signal_snapshot_dataset(events)
    summary = build_snapshot_summary(dataset)

    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(dataset_path, index=False)

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=True, indent=2)

    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a dataset from live signal snapshot JSONL events")
    parser.add_argument("--input", default="runtime/ai_signal_snapshots.jsonl", help="Input JSONL event log")
    parser.add_argument(
        "--dataset-output",
        default="data/processed/signal_snapshot_dataset.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--summary-output",
        default="data/processed/signal_snapshot_dataset_summary.json",
        help="Output summary JSON path",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = build_and_save_signal_snapshot_dataset(
        input_path=Path(args.input),
        dataset_path=Path(args.dataset_output),
        summary_path=Path(args.summary_output),
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

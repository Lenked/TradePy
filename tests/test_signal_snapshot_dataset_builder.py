import json
from pathlib import Path

from ai.training.signal_snapshot_dataset_builder import (
    build_and_save_signal_snapshot_dataset,
    build_signal_snapshot_dataset,
)


def test_build_signal_snapshot_dataset_joins_trade_events():
    events = [
        {
            "event_type": "signal_snapshot",
            "snapshot_id": "snap_1",
            "event_time": "2026-04-03T12:00:00",
            "symbol": "BTCUSDm",
            "signal": "BUY",
        },
        {
            "event_type": "trade_opened",
            "snapshot_id": "snap_1",
            "trade_id": "trade_1",
            "open_time": "2026-04-03T12:01:00",
        },
        {
            "event_type": "trade_closed",
            "snapshot_id": "snap_1",
            "trade_id": "trade_1",
            "close_time": "2026-04-03T12:10:00",
            "pnl": -12.5,
        },
    ]

    dataset = build_signal_snapshot_dataset(events)

    assert len(dataset) == 1
    assert dataset.loc[0, "trade_opened"] == True
    assert dataset.loc[0, "trade_closed"] == True
    assert dataset.loc[0, "trade_pnl"] == -12.5
    assert dataset.loc[0, "label_trade_big_loss"] == 1


def test_build_and_save_signal_snapshot_dataset_writes_outputs(tmp_path: Path):
    input_path = tmp_path / "snapshots.jsonl"
    dataset_path = tmp_path / "dataset.csv"
    summary_path = tmp_path / "summary.json"

    input_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_type": "signal_snapshot",
                        "snapshot_id": "snap_1",
                        "event_time": "2026-04-03T12:00:00",
                        "symbol": "BTCUSDm",
                        "signal": "BUY",
                    }
                ),
                json.dumps(
                    {
                        "event_type": "trade_opened",
                        "snapshot_id": "snap_1",
                        "trade_id": "trade_1",
                        "open_time": "2026-04-03T12:01:00",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    summary = build_and_save_signal_snapshot_dataset(input_path, dataset_path, summary_path)

    assert dataset_path.exists()
    assert summary_path.exists()
    assert summary["row_count"] == 1
    assert summary["trade_opened_rate"] == 1.0

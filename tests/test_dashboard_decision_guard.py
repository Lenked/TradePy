import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np

from ai.decision import DashboardDecisionGuard, SignalSnapshotStore, TradeRegimeTracker
from ai.training.dashboard_dataset_builder import (
    build_dataset_summary,
    build_trade_regime_dataset,
    normalize_dashboard_deals,
)


class ThresholdPipeline:
    def predict_proba(self, frame):
        row = frame.iloc[0]
        score = 0.8 if str(row.get("symbol")) == "BTCUSDm" and float(row.get("global_trade_count_before", 0.0)) >= 3 else 0.2
        return np.array([[1.0 - score, score]], dtype=float)


def _sample_payload():
    return {
        "generated_at": "2026-04-03T12:00:00",
        "period_days": 180,
        "metrics": {
            "total_trades": 3,
            "total_pnl": 4.5,
        },
        "history": {
            "period_days": 180,
            "generated_at": "2026-04-03T12:00:00",
            "deals": [
                {
                    "ticket": 1,
                    "order": 10,
                    "time": "2026-03-01T10:00:00",
                    "symbol": "BTCUSDm",
                    "type": "BUY",
                    "volume": 0.02,
                    "price": 90000.0,
                    "profit": 12.0,
                    "commission": 0.0,
                    "swap": 0.0,
                    "magic": 234000,
                    "entry_type": 1,
                    "comment": "",
                },
                {
                    "ticket": 2,
                    "order": 11,
                    "time": "2026-03-01T12:00:00",
                    "symbol": "BTCUSDm",
                    "type": "SELL",
                    "volume": 0.02,
                    "price": 90100.0,
                    "profit": -5.0,
                    "commission": 0.0,
                    "swap": 0.0,
                    "magic": 234000,
                    "entry_type": 1,
                    "comment": "",
                },
                {
                    "ticket": 3,
                    "order": 12,
                    "time": "2026-03-02T09:00:00",
                    "symbol": "XAUUSDm",
                    "type": "BUY",
                    "volume": 0.01,
                    "price": 2100.0,
                    "profit": -2.0,
                    "commission": -0.5,
                    "swap": 0.0,
                    "magic": 234000,
                    "entry_type": 1,
                    "comment": "[tp 2105.00000]",
                },
            ],
            "positions": [],
        },
    }


def test_trade_regime_tracker_seeds_from_dashboard(tmp_path: Path):
    payload_path = tmp_path / "dashboard.json"
    payload_path.write_text(json.dumps(_sample_payload()), encoding="utf-8")

    tracker = TradeRegimeTracker()
    seeded = tracker.seed_from_dashboard(payload_path)
    feature_row = tracker.build_feature_row(symbol="BTCUSDm", side="BUY", volume=0.03)

    assert seeded == 3
    assert tracker.seed_trade_count == 3
    assert feature_row["trade_count_before"] == 3.0
    assert feature_row["global_total_pnl_before"] == 4.5
    assert feature_row["symbol_total_pnl_before"] == 7.0
    assert feature_row["side_total_pnl_before"] == 9.5


def test_dashboard_decision_guard_scores_shadow_block_candidate(tmp_path: Path):
    payload = _sample_payload()
    normalized = normalize_dashboard_deals(payload)
    dataset = build_trade_regime_dataset(normalized)
    summary = build_dataset_summary(dataset, payload)

    payload_path = tmp_path / "dashboard.json"
    model_path = tmp_path / "model.joblib"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    bundle = {
        "feature_columns": summary["feature_columns"],
        "targets": {
            "label_big_loss": {
                "pipeline": ThresholdPipeline(),
            }
        },
    }
    joblib.dump(bundle, model_path)

    guard = DashboardDecisionGuard(
        {
            "enabled": True,
            "mode": "shadow",
            "target": "label_big_loss",
            "model_path": str(model_path),
            "seed_dashboard_path": str(payload_path),
            "block_threshold": 0.7,
            "throttle_threshold": 0.55,
            "throttle_factor": 0.65,
        }
    )

    result = guard.evaluate(symbol="BTCUSDm", side="BUY", volume=0.03)

    assert guard.active is True
    assert result["score"] == 0.8
    assert result["would_block"] is True
    assert result["reason"] == "shadow_block_candidate"
    assert result["feature_row"]["global_trade_count_before"] == 3.0


def test_signal_snapshot_store_writes_jsonl(tmp_path: Path):
    snapshot_path = tmp_path / "runtime" / "snapshots.jsonl"
    store = SignalSnapshotStore(str(snapshot_path))
    snapshot_id = store.next_snapshot_id("BTCUSDm", datetime(2026, 4, 3, 12, 0, 0))

    store.append_event(
        "signal_snapshot",
        {
            "snapshot_id": snapshot_id,
            "event_time": datetime(2026, 4, 3, 12, 0, 0),
            "symbol": "BTCUSDm",
            "score": np.float64(0.8),
        },
    )

    lines = snapshot_path.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])

    assert len(lines) == 1
    assert payload["event_type"] == "signal_snapshot"
    assert payload["snapshot_id"] == snapshot_id
    assert payload["event_time"] == "2026-04-03T12:00:00"
    assert payload["score"] == 0.8

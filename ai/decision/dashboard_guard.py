"""
Runtime guard and snapshot logging for dashboard-trained decision models.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import joblib
import pandas as pd

from ai.training.dashboard_dataset_builder import (
    WINDOWS,
    PerformanceTracker,
    load_dashboard_payload,
    normalize_dashboard_deals,
)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class TradeRegimeTracker:
    """Maintain pre-trade realized performance features for live inference."""

    def __init__(self, windows: Sequence[int] = WINDOWS):
        self.windows = tuple(windows)
        self.global_tracker = PerformanceTracker(self.windows)
        self.symbol_trackers = defaultdict(lambda: PerformanceTracker(self.windows))
        self.side_trackers = defaultdict(lambda: PerformanceTracker(self.windows))
        self.seed_trade_count = 0
        self.seed_source: Optional[str] = None

    def seed_from_dashboard(self, path: str | Path) -> int:
        dashboard_path = Path(path)
        if not dashboard_path.exists():
            return 0

        payload = load_dashboard_payload(dashboard_path)
        deals_df = normalize_dashboard_deals(payload)
        if deals_df.empty:
            return 0

        deals_df = deals_df.sort_values(["close_time", "ticket", "order"]).reset_index(drop=True)
        seeded = 0
        for _, row in deals_df.iterrows():
            self.record_closed_trade(
                symbol=row.get("symbol"),
                side=row.get("side"),
                volume=row.get("volume"),
                pnl=row.get("net_profit"),
            )
            seeded += 1

        self.seed_trade_count += seeded
        self.seed_source = str(dashboard_path)
        return seeded

    def build_feature_row(self, symbol: str, side: str, volume: float, magic_is_tradepy: int = 1) -> Dict[str, Any]:
        symbol = str(symbol or "")
        side = str(side or "").upper()
        volume_value = max(_safe_float(volume), 0.0)
        feature_row: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "volume": volume_value,
            "volume_log": math.log(volume_value) if volume_value > 0 else 0.0,
            "magic_is_tradepy": int(bool(magic_is_tradepy)),
            "trade_count_before": float(self.global_tracker.trade_count),
        }
        feature_row.update(self.global_tracker.snapshot("global_"))
        feature_row.update(self.symbol_trackers[symbol].snapshot("symbol_"))
        feature_row.update(self.side_trackers[side].snapshot("side_"))
        return feature_row

    def record_closed_trade(self, symbol: str, side: str, volume: float, pnl: float) -> None:
        del volume
        symbol = str(symbol or "")
        side = str(side or "").upper()
        pnl_value = _safe_float(pnl)

        self.global_tracker.update(pnl_value)
        self.symbol_trackers[symbol].update(pnl_value)
        self.side_trackers[side].update(pnl_value)


class DashboardDecisionGuard:
    """Load a trained dashboard model and score live trade candidates."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.mode = str(cfg.get("mode", "shadow")).strip().lower()
        self.target = str(cfg.get("target", "label_big_loss")).strip() or "label_big_loss"
        self.model_path = Path(cfg.get("model_path", "artifacts/models/dashboard_decision_model_bundle.joblib"))
        self.seed_dashboard_path = cfg.get("seed_dashboard_path")
        self.block_threshold = float(cfg.get("block_threshold", 0.68))
        self.throttle_threshold = float(cfg.get("throttle_threshold", 0.55))
        self.throttle_factor = float(cfg.get("throttle_factor", 0.65))

        self.tracker = TradeRegimeTracker()
        self.bundle: Dict[str, Any] = {}
        self.pipeline = None
        self.feature_columns = []
        self.load_error: Optional[str] = None

        if self.seed_dashboard_path:
            try:
                self.tracker.seed_from_dashboard(self.seed_dashboard_path)
            except Exception as exc:
                self.load_error = f"seed_dashboard_error: {exc}"

        if self.enabled:
            self._load_bundle()

    @property
    def active(self) -> bool:
        return bool(self.enabled and self.pipeline is not None and not self.load_error)

    def _load_bundle(self) -> None:
        if not self.model_path.exists():
            self.load_error = f"model_not_found: {self.model_path}"
            return

        try:
            bundle = joblib.load(self.model_path)
        except Exception as exc:
            self.load_error = f"model_load_error: {exc}"
            return

        if not isinstance(bundle, dict):
            self.load_error = "invalid_model_bundle"
            return

        target_cfg = bundle.get("targets", {}).get(self.target)
        if not isinstance(target_cfg, dict):
            self.load_error = f"target_not_found: {self.target}"
            return

        pipeline = target_cfg.get("pipeline")
        if pipeline is None:
            self.load_error = f"pipeline_missing_for_target: {self.target}"
            return

        self.bundle = bundle
        self.pipeline = pipeline
        self.feature_columns = list(bundle.get("feature_columns", []))

    def evaluate(self, symbol: str, side: str, volume: float) -> Dict[str, Any]:
        feature_row = self.tracker.build_feature_row(symbol=symbol, side=side, volume=volume)
        result: Dict[str, Any] = {
            "enabled": self.enabled,
            "active": self.active,
            "mode": self.mode,
            "target": self.target,
            "score": None,
            "would_block": False,
            "should_throttle": False,
            "recommended_volume_factor": 1.0,
            "reason": "guard_disabled" if not self.enabled else "guard_not_ready",
            "feature_row": feature_row,
            "seed_trade_count": self.tracker.seed_trade_count,
            "seed_source": self.tracker.seed_source,
        }

        if not self.enabled:
            return result

        if not self.active:
            if self.load_error:
                result["reason"] = self.load_error
            return result

        model_row = {column: feature_row.get(column) for column in self.feature_columns}
        frame = pd.DataFrame([model_row], columns=self.feature_columns)
        score = float(self.pipeline.predict_proba(frame)[:, 1][0])
        would_block = score >= self.block_threshold
        should_throttle = score >= self.throttle_threshold

        result.update(
            {
                "score": round(score, 6),
                "would_block": bool(would_block),
                "should_throttle": bool(should_throttle),
                "recommended_volume_factor": float(self.throttle_factor) if should_throttle else 1.0,
                "reason": (
                    "shadow_block_candidate"
                    if would_block and self.mode == "shadow"
                    else "enforced_block_candidate"
                    if would_block and self.mode == "enforce"
                    else "throttle_candidate"
                    if should_throttle
                    else "guard_clear"
                ),
            }
        )
        return result

    def record_trade_close(self, symbol: str, side: str, volume: float, pnl: float) -> None:
        self.tracker.record_closed_trade(symbol=symbol, side=side, volume=volume, pnl=pnl)


class SignalSnapshotStore:
    """Append runtime signal and trade lifecycle events to JSONL."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else None
        self.enabled = self.path is not None
        self._sequence = 0

    def next_snapshot_id(self, symbol: str, when: Optional[datetime] = None) -> str:
        self._sequence += 1
        timestamp = (when or datetime.now()).strftime("%Y%m%dT%H%M%S")
        symbol_part = str(symbol or "UNKNOWN").replace(" ", "_")
        return f"{timestamp}_{symbol_part}_{self._sequence:06d}"

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.enabled or self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"event_type": event_type}
        record.update(_sanitize_for_json(payload))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True))
            handle.write("\n")


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_for_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat") and callable(getattr(value, "isoformat")):
        try:
            return value.isoformat()
        except Exception:
            pass
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return value.item()
        except Exception:
            pass
    return value

"""
Hybrid decision engine used to score trading opportunities.
"""
from typing import Any, Dict, Optional

from core.strategy.signal import SignalType


class HybridDecisionEngine:
    """Score directional market features and return a confidence-aware decision."""

    DEFAULT_WEIGHTS = {
        "trend": 0.35,
        "momentum": 0.25,
        "alignment": 0.20,
        "breakout": 0.20,
        "volatility": 0.15,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.allow_ai_override = bool(cfg.get("allow_ai_override", False))
        self.buy_threshold = float(cfg.get("buy_threshold", 0.58))
        self.sell_threshold = float(cfg.get("sell_threshold", 0.58))
        self.override_threshold = float(cfg.get("override_threshold", 0.64))
        self.min_signal_gap = float(cfg.get("min_signal_gap", 0.05))
        self.base_signal_bonus = float(cfg.get("base_signal_bonus", 0.08))
        self.conflict_penalty = float(cfg.get("conflict_penalty", 0.10))

        weights = cfg.get("weights", {})
        merged_weights = dict(self.DEFAULT_WEIGHTS)
        if isinstance(weights, dict):
            for key, value in weights.items():
                try:
                    merged_weights[key] = float(value)
                except (TypeError, ValueError):
                    continue
        self.weights = merged_weights

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, float(value)))

    @classmethod
    def _bias_to_score(cls, bias: float, scale: float = 1.0) -> float:
        return cls._clamp(0.5 + (bias * scale))

    def evaluate(self, snapshot: Dict[str, Any], base_signal: str = SignalType.HOLD) -> Dict[str, Any]:
        trend_bias = float(snapshot.get("trend_bias", 0.0))
        momentum_bias = float(snapshot.get("momentum_bias", 0.0))
        alignment_bias = float(snapshot.get("alignment_bias", 0.0))
        breakout_bias = float(snapshot.get("breakout_bias", 0.0))
        volatility_penalty = self._clamp(snapshot.get("volatility_penalty", 0.0))

        feature_weights = {
            "trend": self.weights.get("trend", 0.0),
            "momentum": self.weights.get("momentum", 0.0),
            "alignment": self.weights.get("alignment", 0.0),
            "breakout": self.weights.get("breakout", 0.0),
        }

        buy_components = {
            "trend": self._bias_to_score(trend_bias, scale=0.45),
            "momentum": self._bias_to_score(momentum_bias, scale=0.40),
            "alignment": self._bias_to_score(alignment_bias, scale=0.35),
            "breakout": self._bias_to_score(breakout_bias, scale=0.30),
        }
        sell_components = {
            "trend": self._bias_to_score(-trend_bias, scale=0.45),
            "momentum": self._bias_to_score(-momentum_bias, scale=0.40),
            "alignment": self._bias_to_score(-alignment_bias, scale=0.35),
            "breakout": self._bias_to_score(-breakout_bias, scale=0.30),
        }

        positive_weight_sum = sum(feature_weights.values()) + self.base_signal_bonus + self.weights.get("volatility", 0.0)
        positive_weight_sum = positive_weight_sum if positive_weight_sum > 0 else 1.0

        buy_raw = sum(feature_weights[name] * buy_components[name] for name in feature_weights)
        sell_raw = sum(feature_weights[name] * sell_components[name] for name in feature_weights)

        if base_signal == SignalType.BUY:
            buy_raw += self.base_signal_bonus
            sell_raw = max(0.0, sell_raw - self.conflict_penalty)
        elif base_signal == SignalType.SELL:
            sell_raw += self.base_signal_bonus
            buy_raw = max(0.0, buy_raw - self.conflict_penalty)

        volatility_cost = volatility_penalty * self.weights.get("volatility", 0.0)
        buy_score = self._clamp((buy_raw - volatility_cost) / positive_weight_sum)
        sell_score = self._clamp((sell_raw - volatility_cost) / positive_weight_sum)

        best_signal = SignalType.BUY if buy_score >= sell_score else SignalType.SELL
        best_score = buy_score if best_signal == SignalType.BUY else sell_score
        opposing_score = sell_score if best_signal == SignalType.BUY else buy_score
        score_gap = abs(buy_score - sell_score)

        threshold = self.buy_threshold if best_signal == SignalType.BUY else self.sell_threshold
        selected_signal = SignalType.HOLD
        reason = "confidence_below_threshold"
        source = "hybrid_ai_filter"

        if best_score >= threshold and score_gap >= self.min_signal_gap:
            if base_signal == SignalType.HOLD:
                if self.allow_ai_override and best_score >= self.override_threshold:
                    selected_signal = best_signal
                    reason = "ai_override_from_hold"
                    source = "hybrid_ai_override"
                else:
                    reason = "base_signal_hold"
            elif base_signal == best_signal:
                selected_signal = best_signal
                reason = "ai_confirmed_base_signal"
            elif self.allow_ai_override and best_score >= self.override_threshold:
                selected_signal = best_signal
                reason = "ai_override_base_signal"
                source = "hybrid_ai_override"
            else:
                reason = "ai_rejected_conflicting_base_signal"
        elif score_gap < self.min_signal_gap:
            reason = "directional_conflict"

        if selected_signal == SignalType.HOLD and base_signal == SignalType.HOLD:
            source = "hybrid_ai_hold"

        return {
            "signal": selected_signal,
            "confidence": round(best_score, 4),
            "buy_score": round(buy_score, 4),
            "sell_score": round(sell_score, 4),
            "score_gap": round(score_gap, 4),
            "reason": reason,
            "source": source,
            "base_signal": base_signal,
            "opposing_score": round(opposing_score, 4),
            "features": {
                "trend_bias": round(trend_bias, 4),
                "momentum_bias": round(momentum_bias, 4),
                "alignment_bias": round(alignment_bias, 4),
                "breakout_bias": round(breakout_bias, 4),
                "volatility_penalty": round(volatility_penalty, 4),
            },
        }

"""
Apply Optuna best params to TradePy settings.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from typing import Dict, Tuple

import yaml


INT_KEYS = {
    "ema_short_period",
    "ema_long_period",
    "rsi_period",
    "atr_period",
    "adx_period",
    "arch_lookback",
}

FLOAT_KEYS = {
    "sl_atr_multiplier",
    "tp_atr_multiplier",
    "adx_threshold",
    "max_conditional_volatility",
}

BOOL_KEYS = {
    "use_pandas_ta",
    "use_adx_filter",
    "use_arch_volatility_filter",
}

ALLOWED_KEYS = INT_KEYS | FLOAT_KEYS | BOOL_KEYS


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _coerce_value(key: str, value):
    if key in INT_KEYS:
        return int(value)
    if key in FLOAT_KEYS:
        if value is None:
            return None
        return float(value)
    if key in BOOL_KEYS:
        return _as_bool(value)
    return value


def load_best_params(params_json_path: str) -> Dict[str, object]:
    with open(params_json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    params = payload.get("best_params", payload) if isinstance(payload, dict) else {}
    if not isinstance(params, dict):
        raise ValueError("best_params payload must be a dict")
    return {k: v for k, v in params.items() if k in ALLOWED_KEYS}


def apply_best_params_to_settings(
    params_json_path: str,
    settings_path: str = "config/settings.yaml",
    output_path: str = None,
    in_place: bool = False,
    backup: bool = True,
) -> Tuple[str, Dict[str, object]]:
    if not os.path.exists(params_json_path):
        raise FileNotFoundError(f"best params file not found: {params_json_path}")
    if not os.path.exists(settings_path):
        raise FileNotFoundError(f"settings file not found: {settings_path}")

    params = load_best_params(params_json_path)

    with open(settings_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"settings root must be a mapping: {settings_path}")

    strategy_cfg = cfg.get("strategy")
    if not isinstance(strategy_cfg, dict):
        strategy_cfg = {}
        cfg["strategy"] = strategy_cfg

    applied = {}
    for key, raw_value in params.items():
        value = _coerce_value(key, raw_value)
        strategy_cfg[key] = value
        applied[key] = value

    target_path = settings_path if in_place else (
        output_path or os.path.join(os.path.dirname(settings_path), "settings.optimized.yaml")
    )
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)

    if in_place and backup:
        backup_path = f"{settings_path}.bak"
        shutil.copyfile(settings_path, backup_path)

    with open(target_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=False)

    return target_path, applied


def main():
    parser = argparse.ArgumentParser(description="Apply Optuna best params to TradePy settings file")
    parser.add_argument("--params-json", default="reports/best_params.json")
    parser.add_argument("--settings", default="config/settings.yaml")
    parser.add_argument("--output", default=None, help="Output settings path when not in-place")
    parser.add_argument("--in-place", action="store_true", help="Overwrite input settings file")
    parser.add_argument("--no-backup", action="store_true", help="Disable .bak creation for in-place mode")
    args = parser.parse_args()

    target, applied = apply_best_params_to_settings(
        params_json_path=args.params_json,
        settings_path=args.settings,
        output_path=args.output,
        in_place=args.in_place,
        backup=not args.no_backup,
    )
    print(f"APPLY_DONE target={target} keys={sorted(applied.keys())}")


if __name__ == "__main__":
    main()

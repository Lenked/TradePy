import json

import yaml

from backtest.apply_best_params import apply_best_params_to_settings


def test_apply_best_params_writes_optimized_settings(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    output_path = tmp_path / "settings.optimized.yaml"
    params_path = tmp_path / "best_params.json"

    settings_payload = {
        "initial_capital": 10000,
        "strategy": {
            "ema_short_period": 20,
            "ema_long_period": 120,
            "use_adx_filter": False,
            "sl_atr_multiplier": 1.5,
        },
        "risk": {"max_trades_per_day": 5},
    }
    params_payload = {
        "best_params": {
            "ema_short_period": "55",
            "adx_threshold": "19.5",
            "use_adx_filter": "true",
            "max_conditional_volatility": None,
            "unknown_key": 999,
        }
    }

    with open(settings_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(settings_payload, f, sort_keys=False, allow_unicode=False)
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump(params_payload, f, ensure_ascii=True, indent=2)

    target, applied = apply_best_params_to_settings(
        params_json_path=str(params_path),
        settings_path=str(settings_path),
        output_path=str(output_path),
        in_place=False,
    )

    assert target == str(output_path)
    assert "unknown_key" not in applied
    assert applied["ema_short_period"] == 55
    assert applied["adx_threshold"] == 19.5
    assert applied["use_adx_filter"] is True
    assert applied["max_conditional_volatility"] is None

    with open(output_path, "r", encoding="utf-8") as f:
        saved = yaml.safe_load(f)

    assert saved["strategy"]["ema_short_period"] == 55
    assert saved["strategy"]["adx_threshold"] == 19.5
    assert saved["strategy"]["use_adx_filter"] is True
    assert saved["strategy"]["max_conditional_volatility"] is None
    assert saved["risk"]["max_trades_per_day"] == 5


def test_apply_best_params_in_place_creates_backup(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    params_path = tmp_path / "best_params.json"

    with open(settings_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"strategy": {"ema_short_period": 21}}, f, sort_keys=False, allow_unicode=False)
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({"best_params": {"ema_short_period": 50}}, f, ensure_ascii=True)

    target, applied = apply_best_params_to_settings(
        params_json_path=str(params_path),
        settings_path=str(settings_path),
        in_place=True,
        backup=True,
    )

    assert target == str(settings_path)
    assert applied["ema_short_period"] == 50
    assert (tmp_path / "settings.yaml.bak").exists()


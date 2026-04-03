import json
from pathlib import Path

from ai.training.dashboard_dataset_builder import (
    build_and_save_dashboard_dataset,
    build_trade_regime_dataset,
    normalize_dashboard_deals,
)


def _sample_payload():
    return {
        "generated_at": "2026-04-03T12:00:00",
        "period_days": 180,
        "metrics": {
            "total_trades": 3,
            "total_pnl": 5.0,
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


def test_normalize_dashboard_deals_builds_expected_fields():
    df = normalize_dashboard_deals(_sample_payload())

    assert len(df) == 3
    assert list(df["symbol"]) == ["BTCUSDm", "BTCUSDm", "XAUUSDm"]
    assert "net_profit" in df.columns
    assert df.loc[2, "net_profit"] == -2.5
    assert df.loc[2, "comment_has_tp_tag"] == 1
    assert df.loc[0, "label_win"] == 1
    assert df.loc[1, "label_loss"] == 1


def test_trade_regime_dataset_uses_prior_history_only():
    normalized = normalize_dashboard_deals(_sample_payload())
    dataset = build_trade_regime_dataset(normalized)

    assert len(dataset) == 3

    first = dataset.iloc[0]
    second = dataset.iloc[1]
    third = dataset.iloc[2]

    assert first["global_trade_count_before"] == 0
    assert first["symbol_trade_count_before"] == 0

    assert second["global_trade_count_before"] == 1
    assert second["global_total_pnl_before"] == 12.0
    assert second["global_win_rate_before"] == 1.0
    assert second["symbol_trade_count_before"] == 1
    assert second["side_trade_count_before"] == 0

    assert third["global_trade_count_before"] == 2
    assert third["global_total_pnl_before"] == 7.0
    assert third["global_consecutive_losses_before"] == 1
    assert third["symbol_trade_count_before"] == 0
    assert third["label_loss"] == 1
    assert third["target_net_profit"] == -2.5


def test_build_and_save_dashboard_dataset_writes_outputs(tmp_path: Path):
    payload_path = tmp_path / "dashboard.json"
    dataset_path = tmp_path / "dataset.csv"
    summary_path = tmp_path / "summary.json"
    normalized_path = tmp_path / "normalized.csv"

    payload_path.write_text(json.dumps(_sample_payload()), encoding="utf-8")
    summary = build_and_save_dashboard_dataset(
        input_path=payload_path,
        dataset_csv_path=dataset_path,
        summary_json_path=summary_path,
        normalized_csv_path=normalized_path,
    )

    assert dataset_path.exists()
    assert summary_path.exists()
    assert normalized_path.exists()
    assert summary["row_count"] == 3
    assert "symbol" in summary["feature_columns"]
    assert "label_win" in summary["label_columns"]
    assert "meta_close_time" in summary["meta_columns"]

import json
from pathlib import Path

import joblib
import pandas as pd

from ai.training.dashboard_model_trainer import TrainingSpec, train_dashboard_decision_models


def _make_training_files(tmp_path: Path) -> tuple[Path, Path]:
    rows = []
    for i in range(60):
        symbol = "BTCUSDm" if i % 2 == 0 else "XAUUSDm"
        side = "BUY" if i % 3 else "SELL"
        win = 1 if (i % 5 in (1, 2, 4)) else 0
        big_loss = 1 if (i % 11 == 0) else 0
        rows.append(
            {
                "symbol": symbol,
                "side": side,
                "volume": 0.01 if symbol == "BTCUSDm" else 0.02,
                "magic_is_tradepy": 1,
                "global_total_pnl_before": float(i * 2 - 30),
                "global_win_rate_before": round(0.35 + (i / 200.0), 6),
                "global_profit_factor_before": round(0.9 + (i / 80.0), 6),
                "symbol_profit_factor_before": round(0.8 + ((i % 10) / 10.0), 6),
                "symbol_consecutive_losses_before": float(i % 4),
                "side_win_rate_before": round(0.3 + ((i % 7) / 20.0), 6),
                "label_win": win,
                "label_loss": 1 - win,
                "label_big_win": 1 if win and i % 6 == 0 else 0,
                "label_big_loss": big_loss,
                "target_net_profit": float(10 if win else -8),
                "target_abs_net_profit": float(10 if win else 8),
                "target_net_profit_per_lot": float(1000 if win else -800),
                "meta_close_time": f"2026-03-{(i % 28) + 1:02d}T{(i % 23):02d}:00:00",
            }
        )

    dataset_df = pd.DataFrame(rows)
    dataset_path = tmp_path / "dataset.csv"
    dataset_df.to_csv(dataset_path, index=False)

    summary = {
        "feature_columns": [
            "symbol",
            "side",
            "volume",
            "magic_is_tradepy",
            "global_total_pnl_before",
            "global_win_rate_before",
            "global_profit_factor_before",
            "symbol_profit_factor_before",
            "symbol_consecutive_losses_before",
            "side_win_rate_before",
        ],
        "categorical_columns": ["symbol", "side"],
        "label_columns": [
            "label_win",
            "label_loss",
            "label_big_win",
            "label_big_loss",
            "target_net_profit",
            "target_abs_net_profit",
            "target_net_profit_per_lot",
        ],
        "meta_columns": ["meta_close_time"],
    }
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return dataset_path, summary_path


def test_train_dashboard_decision_models_writes_artifacts(tmp_path: Path):
    dataset_path, summary_path = _make_training_files(tmp_path)
    model_path = tmp_path / "bundle.joblib"
    report_path = tmp_path / "report.json"
    predictions_path = tmp_path / "predictions.csv"

    report = train_dashboard_decision_models(
        TrainingSpec(
            dataset_path=dataset_path,
            summary_path=summary_path,
            model_output_path=model_path,
            report_output_path=report_path,
            predictions_output_path=predictions_path,
            validation_ratio=0.2,
            random_state=7,
        )
    )

    assert model_path.exists()
    assert report_path.exists()
    assert predictions_path.exists()
    assert set(report["targets"].keys()) == {"label_win", "label_big_loss"}

    bundle = joblib.load(model_path)
    assert bundle["model_family"] == "sklearn_hist_gradient_boosting"
    assert set(bundle["targets"].keys()) == {"label_win", "label_big_loss"}

    predictions_df = pd.read_csv(predictions_path)
    assert "label_win_score" in predictions_df.columns
    assert "label_big_loss_score" in predictions_df.columns

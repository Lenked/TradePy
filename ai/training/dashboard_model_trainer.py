"""
Phase-B trainer for dashboard-based decision models.

This module trains offline models from the phase-A dataset generated from
``data/dashboard.json``. The objective is not to replace the strategy, but to
learn a meta-decision filter that can answer:

- How likely is a trade to end positive? (``label_win``)
- How likely is a trade to become a significant loss? (``label_big_loss``)
"""
from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


DEFAULT_TARGETS: Sequence[str] = ("label_win", "label_big_loss")


@dataclass
class TrainingSpec:
    dataset_path: Path
    summary_path: Path
    model_output_path: Path
    report_output_path: Path
    predictions_output_path: Path | None = None
    validation_ratio: float = 0.2
    random_state: int = 42


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_dataset_and_summary(dataset_path: Path, summary_path: Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    dataset_df = pd.read_csv(dataset_path)
    with summary_path.open("r", encoding="utf-8") as handle:
        summary = json.load(handle)
    if dataset_df.empty:
        raise ValueError("training dataset is empty")
    return dataset_df, summary


def _select_feature_columns(summary: Dict[str, Any]) -> List[str]:
    feature_columns = list(summary.get("feature_columns", []))
    excluded = {"dataset_row_id"}
    return [column for column in feature_columns if column not in excluded]


def _build_preprocessor(feature_columns: Sequence[str], categorical_columns: Sequence[str]) -> Tuple[ColumnTransformer, List[str]]:
    categorical = [column for column in categorical_columns if column in feature_columns]
    numeric = [column for column in feature_columns if column not in categorical]

    encoder_kwargs = {"handle_unknown": "ignore"}
    if "sparse_output" in inspect.signature(OneHotEncoder).parameters:
        encoder_kwargs["sparse_output"] = False
    else:
        encoder_kwargs["sparse"] = False

    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(**encoder_kwargs)),
        ]
    )
    numeric_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, numeric),
            ("cat", categorical_transformer, categorical),
        ],
        remainder="drop",
    )
    return preprocessor, numeric


def _make_pipeline(feature_columns: Sequence[str], categorical_columns: Sequence[str], random_state: int) -> Pipeline:
    preprocessor, _ = _build_preprocessor(feature_columns, categorical_columns)
    model = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_depth=4,
        min_samples_leaf=10,
        l2_regularization=0.1,
        random_state=random_state,
    )
    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", model),
        ]
    )


def _balanced_sample_weight(y: pd.Series) -> np.ndarray:
    counts = y.value_counts().to_dict()
    total = int(len(y))
    weights = {}
    for klass, count in counts.items():
        weights[klass] = total / (len(counts) * count) if count else 1.0
    return y.map(weights).astype(float).to_numpy()


def _time_split(df: pd.DataFrame, validation_ratio: float) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if "meta_close_time" in df.columns:
        ordered = df.sort_values("meta_close_time").reset_index(drop=True)
    else:
        ordered = df.reset_index(drop=True)

    validation_size = max(1, int(len(ordered) * validation_ratio))
    validation_size = min(validation_size, len(ordered) - 1)
    split_idx = len(ordered) - validation_size
    train_df = ordered.iloc[:split_idx].copy()
    valid_df = ordered.iloc[split_idx:].copy()
    if train_df.empty or valid_df.empty:
        raise ValueError("time split produced an empty train or validation set")
    return train_df, valid_df


def _classification_metrics(y_true: pd.Series, y_pred: np.ndarray, y_score: np.ndarray) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "accuracy": round(_safe_float(accuracy_score(y_true, y_pred)), 6),
        "balanced_accuracy": round(_safe_float(balanced_accuracy_score(y_true, y_pred)), 6),
        "precision": round(_safe_float(precision_score(y_true, y_pred, zero_division=0)), 6),
        "recall": round(_safe_float(recall_score(y_true, y_pred, zero_division=0)), 6),
        "f1": round(_safe_float(f1_score(y_true, y_pred, zero_division=0)), 6),
        "average_precision": round(_safe_float(average_precision_score(y_true, y_score)), 6),
        "positive_rate_true": round(_safe_float(np.mean(y_true)), 6),
        "positive_rate_pred": round(_safe_float(np.mean(y_pred)), 6),
        "positive_rate_score": round(_safe_float(np.mean(y_score)), 6),
    }
    unique_classes = set(pd.Series(y_true).astype(int).unique().tolist())
    if len(unique_classes) > 1:
        metrics["roc_auc"] = round(_safe_float(roc_auc_score(y_true, y_score)), 6)
    else:
        metrics["roc_auc"] = None

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    metrics["confusion_matrix"] = {
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }
    return metrics


def train_dashboard_decision_models(spec: TrainingSpec) -> Dict[str, Any]:
    dataset_df, summary = load_dataset_and_summary(spec.dataset_path, spec.summary_path)
    feature_columns = _select_feature_columns(summary)
    categorical_columns = list(summary.get("categorical_columns", []))

    train_df, valid_df = _time_split(dataset_df, spec.validation_ratio)
    X_train = train_df[feature_columns]
    X_valid = valid_df[feature_columns]

    bundle: Dict[str, Any] = {
        "version": 1,
        "model_family": "sklearn_hist_gradient_boosting",
        "feature_columns": feature_columns,
        "categorical_columns": [column for column in categorical_columns if column in feature_columns],
        "targets": {},
        "summary": summary,
        "train_rows": int(len(train_df)),
        "validation_rows": int(len(valid_df)),
    }
    report: Dict[str, Any] = {
        "dataset_path": str(spec.dataset_path),
        "summary_path": str(spec.summary_path),
        "model_family": bundle["model_family"],
        "train_rows": int(len(train_df)),
        "validation_rows": int(len(valid_df)),
        "targets": {},
    }

    prediction_frame = valid_df[["meta_close_time", "symbol", "side"]].copy() if spec.predictions_output_path else None

    for target in DEFAULT_TARGETS:
        if target not in dataset_df.columns:
            raise ValueError(f"target column missing from dataset: {target}")

        y_train = train_df[target].astype(int)
        y_valid = valid_df[target].astype(int)
        if y_train.nunique() < 2:
            raise ValueError(f"target {target} has only one class in train split")
        if y_valid.nunique() < 2:
            raise ValueError(f"target {target} has only one class in validation split")

        pipeline = _make_pipeline(feature_columns, categorical_columns, spec.random_state)
        sample_weight = _balanced_sample_weight(y_train)
        pipeline.fit(X_train, y_train, model__sample_weight=sample_weight)

        valid_scores = pipeline.predict_proba(X_valid)[:, 1]
        valid_pred = (valid_scores >= 0.5).astype(int)
        metrics = _classification_metrics(y_valid, valid_pred, valid_scores)

        bundle["targets"][target] = {
            "pipeline": pipeline,
            "train_positive_rate": round(_safe_float(y_train.mean()), 6),
            "validation_positive_rate": round(_safe_float(y_valid.mean()), 6),
        }
        report["targets"][target] = metrics

        if prediction_frame is not None:
            prediction_frame[f"{target}_true"] = y_valid.to_numpy()
            prediction_frame[f"{target}_score"] = valid_scores
            prediction_frame[f"{target}_pred"] = valid_pred

    spec.model_output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, spec.model_output_path)

    spec.report_output_path.parent.mkdir(parents=True, exist_ok=True)
    with spec.report_output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=True, indent=2)

    if prediction_frame is not None and spec.predictions_output_path is not None:
        spec.predictions_output_path.parent.mkdir(parents=True, exist_ok=True)
        prediction_frame.to_csv(spec.predictions_output_path, index=False)

    return report


def _parse_args() -> TrainingSpec:
    parser = argparse.ArgumentParser(description="Train dashboard decision models from phase-A dataset")
    parser.add_argument(
        "--dataset",
        default="data/processed/dashboard_trade_regime_dataset.csv",
        help="Path to the phase-A dataset CSV",
    )
    parser.add_argument(
        "--summary",
        default="data/processed/dashboard_trade_regime_dataset_summary.json",
        help="Path to the phase-A dataset summary JSON",
    )
    parser.add_argument(
        "--model-output",
        default="artifacts/models/dashboard_decision_model_bundle.joblib",
        help="Path to save the trained model bundle",
    )
    parser.add_argument(
        "--report-output",
        default="artifacts/reports/dashboard_decision_model_report.json",
        help="Path to save the validation report",
    )
    parser.add_argument(
        "--predictions-output",
        default="artifacts/reports/dashboard_decision_validation_predictions.csv",
        help="Path to save validation predictions CSV",
    )
    parser.add_argument(
        "--validation-ratio",
        type=float,
        default=0.2,
        help="Chronological holdout ratio for validation",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed for deterministic training",
    )
    args = parser.parse_args()

    return TrainingSpec(
        dataset_path=Path(args.dataset),
        summary_path=Path(args.summary),
        model_output_path=Path(args.model_output),
        report_output_path=Path(args.report_output),
        predictions_output_path=Path(args.predictions_output) if args.predictions_output else None,
        validation_ratio=float(args.validation_ratio),
        random_state=int(args.random_state),
    )


def main() -> None:
    spec = _parse_args()
    report = train_dashboard_decision_models(spec)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

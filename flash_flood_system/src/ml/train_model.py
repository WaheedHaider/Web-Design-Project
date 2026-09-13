"""
Phase 4: train the flash-flood probability classifier (XGBoost) on the
historical feature table from feature_engineering.py, with probability
calibration since alerting decisions depend on well-calibrated probabilities,
not just ranking.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src.ml.feature_engineering import FEATURE_COLUMNS, build_training_table, prepare_features

MODEL_OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "outputs" / "flood_risk_model.joblib"


def train(start_date: str, end_date: str, test_size: float = 0.2, random_state: int = 42) -> dict:
    raw = build_training_table(start_date, end_date)
    X, y = prepare_features(raw)

    if y.nunique() < 2:
        raise ValueError(
            "Training data has only one class present. Historical flood_event_cells "
            "coverage is likely too small — this is expected until Phase 4's historical "
            "dataset work is complete."
        )

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    base_model = XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="aucpr",
        random_state=random_state,
    )
    calibrated_model = CalibratedClassifierCV(base_model, method="isotonic", cv=3)
    calibrated_model.fit(X_train, y_train)

    probabilities = calibrated_model.predict_proba(X_test)[:, 1]
    metrics = {
        "roc_auc": roc_auc_score(y_test, probabilities),
        "average_precision": average_precision_score(y_test, probabilities),
        "brier_score": brier_score_loss(y_test, probabilities),
        "n_train": len(X_train),
        "n_test": len(X_test),
    }

    MODEL_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": calibrated_model, "feature_columns": FEATURE_COLUMNS}, MODEL_OUTPUT_PATH)

    return metrics


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()

    results = train(args.start_date, args.end_date)
    print(json.dumps(results, indent=2))
    print(f"Model saved to {MODEL_OUTPUT_PATH}")

"""
Phase 4/5: score the current feature snapshot for every grid cell with the
trained model, combine with the hydrological threat into a single risk
value, and write the result to risk_predictions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from database.db_utils import get_engine, query_df
from src.ml.train_model import MODEL_OUTPUT_PATH

# Weight given to the ML probability vs. the hydrological threat when forming
# combined_risk. Calibrate in Phase 7 backtesting rather than treating as final.
ML_WEIGHT = 0.6
HYDRO_WEIGHT = 0.4


def load_model():
    bundle = joblib.load(MODEL_OUTPUT_PATH)
    return bundle["model"], bundle["feature_columns"]


def score_current_conditions(valid_for: pd.Timestamp) -> pd.DataFrame:
    model, feature_columns = load_model()

    sql = """
        SELECT
            r.cell_id,
            r.rain_mm_1h, r.rain_mm_3h, r.rain_mm_6h, r.rain_mm_12h, r.rain_mm_24h, r.rain_mm_72h,
            sm.soil_moisture_pct, sm.antecedent_wetness_index,
            tf.elevation_m, tf.slope_deg, tf.flow_accumulation, tf.twi, tf.distance_to_stream_m,
            rp.hydrological_threat
        FROM rainfall r
        JOIN soil_moisture sm ON sm.cell_id = r.cell_id AND sm.observed_at = r.observed_at
        JOIN terrain_features tf ON tf.cell_id = r.cell_id
        LEFT JOIN risk_predictions rp ON rp.cell_id = r.cell_id AND rp.valid_for = r.observed_at
        WHERE r.observed_at = :valid_for
    """
    df = query_df(sql, {"valid_for": valid_for}).dropna(subset=feature_columns)

    if df.empty:
        return df

    df["ml_probability"] = model.predict_proba(df[feature_columns])[:, 1]
    df["combined_risk"] = (
        ML_WEIGHT * df["ml_probability"] + HYDRO_WEIGHT * df["hydrological_threat"].fillna(0)
    )
    df["valid_for"] = valid_for
    return df[["cell_id", "valid_for", "hydrological_threat", "ml_probability", "combined_risk"]]


def write_predictions(predictions: pd.DataFrame) -> None:
    predictions.to_sql("risk_predictions", get_engine(), if_exists="append", index=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valid-for", required=True, help="Timestamp to score, e.g. 2026-09-13T06:00:00")
    args = parser.parse_args()

    preds = score_current_conditions(pd.Timestamp(args.valid_for))
    if preds.empty:
        print("No cells had complete feature data for this timestamp.")
    else:
        write_predictions(preds)
        print(f"Wrote {len(preds)} risk_predictions rows for {args.valid_for}")

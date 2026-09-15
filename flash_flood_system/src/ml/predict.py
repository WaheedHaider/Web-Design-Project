"""
Phase 4/5: score the current feature snapshot for every grid cell with the
trained model, combine with the hydrological threat into a single risk
value, and update it onto the same risk_predictions row.

Must run AFTER src/hydrology/ffg_engine.py for the same --valid-for: this
script requires hydrological_threat to already be present (it does not
default a missing value to 0 — that would silently understate risk for
cells the hydrological engine hasn't scored yet) and only UPDATEs that
existing row, it never inserts a new one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import MODEL_VERSION
from database.db_utils import bulk_update, query_df
from src.ml.train_model import MODEL_OUTPUT_PATH

# Weight given to the ML probability vs. the hydrological threat when forming
# combined_risk. Calibrate in Phase 7 backtesting rather than treating as final.
ML_WEIGHT = 0.6
HYDRO_WEIGHT = 0.4


def load_model():
    bundle = joblib.load(MODEL_OUTPUT_PATH)
    return bundle["model"], bundle["feature_columns"]


def score_current_conditions(valid_for: pd.Timestamp, model_version: str = MODEL_VERSION) -> pd.DataFrame:
    model, feature_columns = load_model()

    # hydrological_threat is pulled from the row ffg_engine.py already wrote
    # for this exact (cell_id, valid_for, model_version) — an inner join, not
    # left, so a cell the hydrological engine hasn't scored yet is excluded
    # rather than silently treated as zero threat. soil_moisture is joined
    # "as-of" (most recent reading at or before the rainfall timestamp)
    # since satellite soil-moisture revisit times don't line up with rainfall.
    sql = """
        SELECT
            r.cell_id,
            r.rain_mm_1h, r.rain_mm_3h, r.rain_mm_6h, r.rain_mm_12h, r.rain_mm_24h, r.rain_mm_72h,
            sm.soil_moisture_pct, sm.antecedent_wetness_index,
            tf.elevation_m, tf.slope_deg, tf.flow_accumulation, tf.twi, tf.distance_to_stream_m,
            rp.hydrological_threat
        FROM rainfall r
        JOIN terrain_features tf ON tf.cell_id = r.cell_id
        JOIN risk_predictions rp
            ON rp.cell_id = r.cell_id AND rp.valid_for = r.observed_at AND rp.model_version = :model_version
        LEFT JOIN LATERAL (
            SELECT soil_moisture_pct, antecedent_wetness_index
            FROM soil_moisture sm
            WHERE sm.cell_id = r.cell_id AND sm.observed_at <= r.observed_at
            ORDER BY sm.observed_at DESC
            LIMIT 1
        ) sm ON true
        WHERE r.observed_at = :valid_for AND rp.hydrological_threat IS NOT NULL
    """
    df = query_df(sql, {"valid_for": valid_for, "model_version": model_version}).dropna(subset=feature_columns)

    if df.empty:
        return df

    df["ml_probability"] = model.predict_proba(df[feature_columns])[:, 1]
    df["combined_risk"] = ML_WEIGHT * df["ml_probability"] + HYDRO_WEIGHT * df["hydrological_threat"]
    # Illustrative confidence proxy: agreement between the two independent
    # signals (data-driven ML vs. domain-based hydrology). When they agree,
    # confidence is high; when they diverge, it's low. Replace with a
    # calibration-error-based measure once Phase 7 backtesting exists.
    df["confidence"] = (1 - (df["ml_probability"] - df["hydrological_threat"]).abs()).clip(0, 1)
    df["valid_for"] = valid_for
    df["model_version"] = model_version
    return df[["cell_id", "valid_for", "model_version", "ml_probability", "combined_risk", "confidence"]]


def write_predictions(predictions: pd.DataFrame) -> int:
    return bulk_update(
        predictions,
        "risk_predictions",
        key_columns=["cell_id", "valid_for", "model_version"],
        update_columns=["ml_probability", "combined_risk", "confidence"],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valid-for", required=True, help="Timestamp to score, e.g. 2026-09-13T06:00:00")
    args = parser.parse_args()

    preds = score_current_conditions(pd.Timestamp(args.valid_for))
    if preds.empty:
        print(
            "No cells had complete feature data + an existing hydrological_threat row for "
            "this timestamp. Run src/hydrology/ffg_engine.py --valid-for first."
        )
    else:
        updated = write_predictions(preds)
        print(f"Updated {updated} risk_predictions rows for {args.valid_for}")

"""
FFG-like dynamic threshold engine.

Not a reproduction of IMD/SAsiaFFGS's exact equations — a domain-informed
model asking: "how much rainfall can this cell's watershed tolerate, given
its current wetness and terrain, before flash-flood/runoff threat becomes
significant?" The threshold drops as antecedent wetness, slope, TWI and
proximity to a stream increase. Weights are seeded from config.yaml and are
placeholders until Phase 3 calibrates them against historical flood_events.

This must run — and its --write-db output land in risk_predictions — BEFORE
src/ml/predict.py, which reads hydrological_threat back out for that same
(cell_id, valid_for, model_version) row and fills in ml_probability/
combined_risk/confidence on top of it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import CONFIG, MODEL_VERSION
from database.db_utils import query_df, upsert_dataframe

HYDRO_CFG = CONFIG["hydrology"]

# Columns required from the cell/timestamp feature snapshot to compute a
# hydrological threat score.
REQUIRED_COLUMNS = [
    "antecedent_wetness_index",
    "slope_deg",
    "twi",
    "distance_to_stream_m",
    "rain_mm_6h",
]


def _normalize(series: pd.Series, low: float, high: float) -> pd.Series:
    return ((series - low) / (high - low)).clip(0, 1)


def dynamic_rainfall_threshold(
    antecedent_wetness_index: pd.Series,
    slope_deg: pd.Series,
    twi: pd.Series,
    distance_to_stream_m: pd.Series,
    base_threshold_mm: float = HYDRO_CFG["base_threshold_mm"],
) -> pd.Series:
    """
    Returns, per cell, the rainfall (mm) beyond which hydrological threat
    becomes significant. Higher wetness/slope/TWI and closer streams pull
    the threshold down from the fully-dry baseline.
    """
    slope_norm = _normalize(slope_deg, low=0, high=45)
    twi_norm = _normalize(twi, low=twi.quantile(0.05), high=twi.quantile(0.95))
    proximity_norm = 1 - _normalize(distance_to_stream_m, low=0, high=1000)

    susceptibility = (
        HYDRO_CFG["wetness_weight"] * antecedent_wetness_index
        + HYDRO_CFG["slope_weight"] * slope_norm
        + HYDRO_CFG["twi_weight"] * twi_norm
        + HYDRO_CFG["distance_to_stream_weight"] * proximity_norm
    )

    threshold = base_threshold_mm * (1 - susceptibility)
    return threshold.clip(lower=base_threshold_mm * 0.1).rename("dynamic_threshold_mm")


def hydrological_threat(rain_mm_recent: pd.Series, threshold_mm: pd.Series) -> pd.Series:
    """
    0-1 threat score: 0 when rainfall is well under threshold, approaching 1
    as rainfall meets/exceeds the dynamic threshold. Uses a smooth ratio
    rather than a hard cutoff so the ML model receives a continuous signal.
    """
    ratio = rain_mm_recent / threshold_mm.replace(0, np.nan)
    return ratio.clip(upper=1.5).fillna(0).rename("hydrological_threat") / 1.5


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Adds dynamic_threshold_mm + hydrological_threat columns to df in place."""
    df["dynamic_threshold_mm"] = dynamic_rainfall_threshold(
        df["antecedent_wetness_index"], df["slope_deg"], df["twi"], df["distance_to_stream_m"]
    )
    df["hydrological_threat"] = hydrological_threat(df["rain_mm_6h"], df["dynamic_threshold_mm"])
    return df


def fetch_snapshot(valid_for: pd.Timestamp) -> pd.DataFrame:
    """
    Pulls terrain + rainfall + the most recent prior soil-moisture reading
    (an "as-of" join, since satellite soil moisture rarely lands on the exact
    same timestamp as a rainfall observation) for every cell at valid_for.
    """
    sql = """
        SELECT
            r.cell_id, r.observed_at AS valid_for, r.rain_mm_6h,
            tf.slope_deg, tf.twi, tf.distance_to_stream_m,
            sm.antecedent_wetness_index
        FROM rainfall r
        JOIN terrain_features tf ON tf.cell_id = r.cell_id
        LEFT JOIN LATERAL (
            SELECT antecedent_wetness_index
            FROM soil_moisture sm
            WHERE sm.cell_id = r.cell_id AND sm.observed_at <= r.observed_at
            ORDER BY sm.observed_at DESC
            LIMIT 1
        ) sm ON true
        WHERE r.observed_at = :valid_for
    """
    return query_df(sql, {"valid_for": valid_for})


def run_for_timestamp(valid_for: pd.Timestamp, model_version: str = MODEL_VERSION) -> pd.DataFrame:
    df = fetch_snapshot(valid_for)
    df = df.dropna(subset=REQUIRED_COLUMNS)
    if df.empty:
        return df

    df = compute(df)
    df["model_version"] = model_version

    upsert_dataframe(
        df[["cell_id", "valid_for", "model_version", "hydrological_threat"]],
        "risk_predictions",
        conflict_columns=["cell_id", "valid_for", "model_version"],
        update_columns=["hydrological_threat"],
    )
    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--valid-for", help="Timestamp to score from the DB and write to risk_predictions, e.g. 2026-09-13T06:00:00"
    )
    parser.add_argument(
        "--features-csv",
        help=f"Offline mode: CSV with columns {REQUIRED_COLUMNS} (no DB write, use with --out-csv)",
    )
    parser.add_argument("--out-csv", help="Required with --features-csv")
    args = parser.parse_args()

    if args.valid_for:
        result = run_for_timestamp(pd.Timestamp(args.valid_for))
        if result.empty:
            print("No cells had complete rainfall/terrain/soil-moisture data for this timestamp.")
        else:
            print(f"Wrote hydrological_threat for {len(result)} cells at {args.valid_for}")
    elif args.features_csv:
        if not args.out_csv:
            parser.error("--out-csv is required with --features-csv")
        offline_df = compute(pd.read_csv(args.features_csv))
        offline_df.to_csv(args.out_csv, index=False)
        print(f"Computed hydrological threat for {len(offline_df)} cells -> {args.out_csv}")
    else:
        parser.error("Provide either --valid-for (DB mode) or --features-csv (offline mode)")

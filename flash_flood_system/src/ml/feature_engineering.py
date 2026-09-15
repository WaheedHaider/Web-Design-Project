"""
Assembles the per-cell feature table the ML model trains/predicts on, by
joining rainfall, soil moisture/wetness, terrain and the hydrological
threat score computed upstream. One row per (cell, timestamp).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import MODEL_VERSION
from database.db_utils import query_df

FEATURE_COLUMNS = [
    "rain_mm_1h",
    "rain_mm_3h",
    "rain_mm_6h",
    "rain_mm_12h",
    "rain_mm_24h",
    "rain_mm_72h",
    "soil_moisture_pct",
    "antecedent_wetness_index",
    "elevation_m",
    "slope_deg",
    "flow_accumulation",
    "twi",
    "distance_to_stream_m",
    "hydrological_threat",
]

LABEL_COLUMN = "was_flooded"


def build_training_table(
    start_date: str, end_date: str, model_version: str = MODEL_VERSION
) -> pd.DataFrame:
    """
    Joins rainfall/soil_moisture/terrain_features/risk_predictions.hydrological_threat
    for every (cell, timestamp) in [start_date, end_date], labeled positive only for
    timestamps that fall inside an actual flood_events time window for that cell
    (not just "this cell was flooded at some point" — see was_flooded below).
    Positive/negative sampling strategy will be refined once real historical
    event coverage is known (Phase 4).

    soil_moisture is joined "as-of" (most recent reading at or before the
    rainfall timestamp) rather than on an exact timestamp match, since
    satellite soil-moisture revisit times don't align with rainfall records.
    """
    sql = """
        SELECT
            r.cell_id, r.observed_at,
            r.rain_mm_1h, r.rain_mm_3h, r.rain_mm_6h, r.rain_mm_12h, r.rain_mm_24h, r.rain_mm_72h,
            sm.soil_moisture_pct, sm.antecedent_wetness_index,
            tf.elevation_m, tf.slope_deg, tf.flow_accumulation, tf.twi, tf.distance_to_stream_m,
            rp.hydrological_threat,
            -- fe.event_id (not fec.cell_id) so a cell is only labeled positive for
            -- timestamps actually inside the event window, not every timestamp ever
            -- recorded for a cell that flooded at some unrelated point in time.
            CASE WHEN fe.event_id IS NOT NULL THEN 1 ELSE 0 END AS was_flooded
        FROM rainfall r
        JOIN terrain_features tf ON tf.cell_id = r.cell_id
        LEFT JOIN risk_predictions rp
            ON rp.cell_id = r.cell_id AND rp.valid_for = r.observed_at AND rp.model_version = :model_version
        LEFT JOIN LATERAL (
            SELECT soil_moisture_pct, antecedent_wetness_index
            FROM soil_moisture sm
            WHERE sm.cell_id = r.cell_id AND sm.observed_at <= r.observed_at
            ORDER BY sm.observed_at DESC
            LIMIT 1
        ) sm ON true
        LEFT JOIN flood_event_cells fec ON fec.cell_id = r.cell_id
        LEFT JOIN flood_events fe ON fe.event_id = fec.event_id
            AND r.observed_at BETWEEN fe.event_start AND COALESCE(fe.event_end, fe.event_start + INTERVAL '1 day')
        WHERE r.observed_at BETWEEN :start_date AND :end_date
    """
    return query_df(sql, {"start_date": start_date, "end_date": end_date, "model_version": model_version})


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    df = df.dropna(subset=FEATURE_COLUMNS + [LABEL_COLUMN])
    return df[FEATURE_COLUMNS], df[LABEL_COLUMN]

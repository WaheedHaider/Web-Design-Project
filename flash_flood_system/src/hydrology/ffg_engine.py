"""
FFG-like dynamic threshold engine.

Not a reproduction of IMD/SAsiaFFGS's exact equations — a domain-informed
model asking: "how much rainfall can this cell's watershed tolerate, given
its current wetness and terrain, before flash-flood/runoff threat becomes
significant?" The threshold drops as antecedent wetness, slope, TWI and
proximity to a stream increase. Weights are seeded from config.yaml and are
placeholders until Phase 3 calibrates them against historical flood_events.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import CONFIG

HYDRO_CFG = CONFIG["hydrology"]


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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features-csv", required=True, help=(
        "CSV with columns: antecedent_wetness_index, slope_deg, twi, "
        "distance_to_stream_m, rain_mm_6h"
    ))
    parser.add_argument("--out-csv", required=True)
    args = parser.parse_args()

    df = pd.read_csv(args.features_csv)
    df["dynamic_threshold_mm"] = dynamic_rainfall_threshold(
        df["antecedent_wetness_index"], df["slope_deg"], df["twi"], df["distance_to_stream_m"]
    )
    df["hydrological_threat"] = hydrological_threat(df["rain_mm_6h"], df["dynamic_threshold_mm"])
    df.to_csv(args.out_csv, index=False)
    print(f"Computed hydrological threat for {len(df)} cells -> {args.out_csv}")

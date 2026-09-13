"""
Antecedent wetness condition (AWC): how saturated a cell's ground already is,
combining recent soil-moisture observations with rainfall accumulated over
the preceding days. Used as the primary input to the dynamic threshold in
ffg_engine.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def antecedent_wetness_index(
    soil_moisture_pct: pd.Series,
    rain_mm_72h: pd.Series,
    soil_saturation_pct: float = 45.0,
    rain_saturation_mm: float = 150.0,
) -> pd.Series:
    """
    Blends normalized soil moisture and normalized 72h rainfall into a single
    0-1 wetness index. Saturation constants are illustrative defaults —
    Phase 3 calibrates them per-watershed from historical soil/rainfall data.

    awc = 0.6 * (soil_moisture / soil_saturation) + 0.4 * (rain_72h / rain_saturation)
    """
    soil_component = (soil_moisture_pct / soil_saturation_pct).clip(0, 1)
    rain_component = (rain_mm_72h / rain_saturation_mm).clip(0, 1)
    return (0.6 * soil_component + 0.4 * rain_component).rename("antecedent_wetness_index")


def classify_wetness(awi: pd.Series) -> pd.Series:
    bins = [-np.inf, 0.3, 0.6, np.inf]
    labels = ["DRY", "MODERATE", "SATURATED"]
    return pd.cut(awi, bins=bins, labels=labels)

"""
Phase 5: convert grid-cell risk predictions into ward-level risk.

A plain average hides small critical pockets (e.g. a ward averaging 35% risk
but containing one 95% cell over a school). So the ward score combines:
average risk, max risk, the fraction of the ward's area above a high-risk
threshold, and an exposure score — not an unweighted mean.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import CONFIG
from database.db_utils import get_engine, query_df

AGG_CFG = CONFIG["ward_aggregation"]

RISK_CATEGORY_BINS = [0, 0.4, 0.6, 0.8, 1.01]
RISK_CATEGORY_LABELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]


def _high_risk_area_pct(group: pd.DataFrame, threshold: float) -> float:
    return 100.0 * (group["combined_risk"] >= threshold).mean()


def aggregate_ward_risk(cell_predictions: pd.DataFrame, exposure_by_cell: pd.Series | None = None) -> pd.DataFrame:
    """
    cell_predictions: columns [ward_id, cell_id, combined_risk, confidence]
        for a single `valid_for` timestamp.
    exposure_by_cell: optional Series indexed by cell_id with a 0-1 exposure
        score (population/critical-infrastructure weighted). Defaults to 0
        (no exposure weighting) until Phase 5's exposure layer is built.
    """
    df = cell_predictions.copy()
    if exposure_by_cell is not None:
        df["exposure"] = df["cell_id"].map(exposure_by_cell).fillna(0)
    else:
        df["exposure"] = 0.0

    threshold = AGG_CFG["high_risk_cell_threshold"]

    rows = []
    for ward_id, group in df.groupby("ward_id"):
        avg_risk = group["combined_risk"].mean()
        max_risk = group["combined_risk"].max()
        high_risk_pct = _high_risk_area_pct(group, threshold)
        exposure_score = group["exposure"].mean()
        confidence = group["confidence"].mean() if "confidence" in group else None

        ward_score = (
            AGG_CFG["weight_avg_risk"] * avg_risk
            + AGG_CFG["weight_max_risk"] * max_risk
            + AGG_CFG["weight_high_risk_area_pct"] * (high_risk_pct / 100.0)
            + AGG_CFG["weight_exposure"] * exposure_score
        )

        rows.append(
            {
                "ward_id": ward_id,
                "avg_risk": avg_risk,
                "max_risk": max_risk,
                "high_risk_area_pct": high_risk_pct,
                "exposure_score": exposure_score,
                "ward_risk_score": ward_score,
                "confidence": confidence,
            }
        )

    result = pd.DataFrame(rows)
    result["risk_category"] = pd.cut(
        result["ward_risk_score"], bins=RISK_CATEGORY_BINS, labels=RISK_CATEGORY_LABELS, right=False
    )
    return result


def aggregate_for_timestamp(valid_for: pd.Timestamp) -> pd.DataFrame:
    sql = """
        SELECT gc.ward_id, rp.cell_id, rp.combined_risk, rp.confidence
        FROM risk_predictions rp
        JOIN grid_cells gc ON gc.cell_id = rp.cell_id
        WHERE rp.valid_for = :valid_for AND gc.ward_id IS NOT NULL
    """
    cell_predictions = query_df(sql, {"valid_for": valid_for})
    if cell_predictions.empty:
        return cell_predictions

    ward_risk = aggregate_ward_risk(cell_predictions)
    ward_risk["valid_for"] = valid_for
    return ward_risk


def write_ward_risk(ward_risk: pd.DataFrame) -> None:
    ward_risk.to_sql("ward_risk", get_engine(), if_exists="append", index=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valid-for", required=True)
    args = parser.parse_args()

    ward_risk_df = aggregate_for_timestamp(pd.Timestamp(args.valid_for))
    if ward_risk_df.empty:
        print("No ward-linked risk predictions found for this timestamp.")
    else:
        write_ward_risk(ward_risk_df)
        print(f"Wrote ward_risk for {len(ward_risk_df)} wards at {args.valid_for}")

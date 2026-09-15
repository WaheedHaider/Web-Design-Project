"""
Fills grid_cells.ward_id / village_id / watershed_id by testing each cell's
centroid against the loaded administrative and hydrological boundaries.
Without this, ward_aggregation.py has nothing to group cells by and the
watershed_id FK used by the hydrological engine's per-watershed calibration
stays empty.

Run once after both the admin boundaries (admin_boundaries.py) and the grid
(load_grid_to_db.py) are loaded, and again any time new cells are added
(e.g. after refining high-risk cells to 100m).

Usage:
    python -m src.spatial.assign_admin_watershed
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from database.db_utils import get_engine

# grid_cells column -> (boundary table, boundary PK column)
ASSIGNMENTS = {
    "ward_id": ("wards", "ward_id"),
    "village_id": ("villages", "village_id"),
    "watershed_id": ("watersheds", "watershed_id"),
}


def assign_all() -> dict[str, int]:
    results = {}
    with get_engine().begin() as conn:
        for fk_col, (table, pk_col) in ASSIGNMENTS.items():
            result = conn.execute(
                text(
                    f"UPDATE grid_cells gc SET {fk_col} = b.{pk_col} "
                    f"FROM {table} b "
                    f"WHERE gc.{fk_col} IS NULL AND ST_Within(gc.centroid, b.geom)"
                )
            )
            results[fk_col] = result.rowcount
    return results


if __name__ == "__main__":
    counts = assign_all()
    for fk_col, n in counts.items():
        print(f"Assigned {fk_col} for {n} grid cells.")

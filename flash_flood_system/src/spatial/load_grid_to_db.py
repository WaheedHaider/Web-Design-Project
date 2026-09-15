"""
Loads a grid vector file produced by grid_generator.py into the grid_cells
table. centroid is filled server-side by the trg_set_grid_cell_centroid
trigger (see database/schema.sql) — this script never computes it itself.

For refined (100m) cells, parent_cell_code (text, set by
grid_generator.refine_cells) is resolved to the parent's actual cell_id
after insert.

Usage:
    python -m src.spatial.load_grid_to_db --grid data/processed/grid/base_grid_250m.gpkg
    python -m src.spatial.load_grid_to_db --grid data/processed/grid/refined_100m.gpkg
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from database.db_utils import get_engine, write_geodataframe


def load_grid(grid_path: str) -> int:
    gdf = gpd.read_file(grid_path)
    has_parent_codes = "parent_cell_code" in gdf.columns and gdf["parent_cell_code"].notna().any()

    load_cols = ["cell_code", "resolution_m", "geometry"]
    write_geodataframe(gdf[load_cols], "grid_cells", if_exists="append")
    print(f"Inserted {len(gdf)} grid cells from {grid_path}.")

    if has_parent_codes:
        resolved = resolve_parent_cell_ids(gdf)
        print(f"Resolved parent_cell_id for {resolved} refined cells.")

    return len(gdf)


def resolve_parent_cell_ids(gdf: gpd.GeoDataFrame) -> int:
    """
    grid_generator.refine_cells() stamps each fine cell with its parent's
    cell_code (text). Once both parent and child rows exist in grid_cells,
    translate that into the real parent_cell_id FK via a join on cell_code.
    """
    pairs = gdf.loc[gdf["parent_cell_code"].notna(), ["cell_code", "parent_cell_code"]]
    if pairs.empty:
        return 0

    with get_engine().begin() as conn:
        pairs.to_sql("_staging_parent_codes", conn, index=False, if_exists="replace")
        result = conn.execute(
            text(
                """
                UPDATE grid_cells child
                SET parent_cell_id = parent.cell_id
                FROM _staging_parent_codes s
                JOIN grid_cells parent ON parent.cell_code = s.parent_cell_code
                WHERE child.cell_code = s.cell_code
                """
            )
        )
        conn.execute(text("DROP TABLE _staging_parent_codes"))
        return result.rowcount


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", required=True)
    args = parser.parse_args()

    load_grid(args.grid)

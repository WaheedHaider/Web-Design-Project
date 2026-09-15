"""
Phase 1: build the fine-scale prediction grid.

Generates a regular fishnet at the configured base resolution (default 250m)
clipped to a study-area boundary, in the projected CRS so cell sizes are true
metres. High-risk cells can later be refined to 100m via `refine_cells`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon, box

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import BASE_GRID_RESOLUTION_M, GEOGRAPHIC_CRS, HIGH_RISK_GRID_RESOLUTION_M, PROJECTED_CRS


def _fishnet(bounds: tuple[float, float, float, float], resolution_m: float) -> list[Polygon]:
    minx, miny, maxx, maxy = bounds
    xs = np.arange(minx, maxx, resolution_m)
    ys = np.arange(miny, maxy, resolution_m)
    return [
        box(x, y, x + resolution_m, y + resolution_m)
        for x in xs
        for y in ys
    ]


def generate_grid(
    boundary: gpd.GeoDataFrame,
    resolution_m: float = BASE_GRID_RESOLUTION_M,
) -> gpd.GeoDataFrame:
    """
    boundary: study-area polygon(s) in any CRS (e.g. dissolved Uttarakhand outline).
    Returns a GeoDataFrame of grid cells (in EPSG:4326) clipped to the boundary,
    with columns: cell_code, resolution_m, geometry, centroid_lon, centroid_lat.
    """
    boundary_proj = boundary.to_crs(PROJECTED_CRS)
    dissolved = boundary_proj.union_all() if hasattr(boundary_proj, "union_all") else boundary_proj.unary_union

    cells = _fishnet(dissolved.bounds, resolution_m)
    grid = gpd.GeoDataFrame(geometry=cells, crs=PROJECTED_CRS)

    grid = grid[grid.intersects(dissolved)].copy()
    grid["geometry"] = grid.geometry.intersection(dissolved)
    grid = grid[~grid.geometry.is_empty]

    grid = grid.reset_index(drop=True)
    n_digits = max(6, len(str(len(grid))))
    grid["cell_code"] = [
        f"C{str(i).zfill(n_digits)}_{int(resolution_m)}M" for i in grid.index
    ]
    grid["resolution_m"] = int(resolution_m)
    grid["parent_cell_code"] = None

    grid = grid.to_crs(GEOGRAPHIC_CRS)
    centroids = grid.geometry.centroid
    grid["centroid_lon"] = centroids.x
    grid["centroid_lat"] = centroids.y

    return grid[["cell_code", "resolution_m", "parent_cell_code", "geometry", "centroid_lon", "centroid_lat"]]


def refine_cells(
    parent_grid: gpd.GeoDataFrame,
    cell_codes_to_refine: list[str],
    fine_resolution_m: float = HIGH_RISK_GRID_RESOLUTION_M,
) -> gpd.GeoDataFrame:
    """
    Subdivides the named parent cells (e.g. those with predicted risk above
    the `high_risk_refine_threshold` in config.yaml) into a finer fishnet.
    Returns only the new fine cells; callers append them to grid_cells with
    parent_cell_id pointing back to the original 250m cell.
    """
    parents = parent_grid[parent_grid["cell_code"].isin(cell_codes_to_refine)].to_crs(PROJECTED_CRS)

    fine_rows = []
    for _, parent in parents.iterrows():
        sub_cells = _fishnet(parent.geometry.bounds, fine_resolution_m)
        sub_gdf = gpd.GeoDataFrame(geometry=sub_cells, crs=PROJECTED_CRS)
        sub_gdf = sub_gdf[sub_gdf.intersects(parent.geometry)]
        sub_gdf["geometry"] = sub_gdf.geometry.intersection(parent.geometry)
        sub_gdf = sub_gdf[~sub_gdf.geometry.is_empty]
        sub_gdf["parent_cell_code"] = parent["cell_code"]
        fine_rows.append(sub_gdf)

    if not fine_rows:
        return gpd.GeoDataFrame(columns=["cell_code", "resolution_m", "parent_cell_code", "geometry"], crs=GEOGRAPHIC_CRS)

    fine_grid = gpd.GeoDataFrame(pd_concat(fine_rows), crs=PROJECTED_CRS).reset_index(drop=True)
    fine_grid["cell_code"] = [
        f"{row.parent_cell_code}_R{i}_{int(fine_resolution_m)}M"
        for i, row in fine_grid.iterrows()
    ]
    fine_grid["resolution_m"] = int(fine_resolution_m)

    fine_grid = fine_grid.to_crs(GEOGRAPHIC_CRS)
    centroids = fine_grid.geometry.centroid
    fine_grid["centroid_lon"] = centroids.x
    fine_grid["centroid_lat"] = centroids.y

    return fine_grid[["cell_code", "resolution_m", "parent_cell_code", "geometry", "centroid_lon", "centroid_lat"]]


def pd_concat(frames):
    import pandas as pd

    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate the base prediction grid from a boundary file.")
    parser.add_argument("--boundary", required=True, help="Path to a boundary vector file (e.g. dissolved state outline)")
    parser.add_argument("--output", required=True, help="Output path (GeoPackage/Shapefile/GeoJSON)")
    parser.add_argument("--resolution-m", type=float, default=BASE_GRID_RESOLUTION_M)
    args = parser.parse_args()

    boundary_gdf = gpd.read_file(args.boundary)
    grid_gdf = generate_grid(boundary_gdf, resolution_m=args.resolution_m)
    grid_gdf.to_file(args.output)
    print(f"Generated {len(grid_gdf)} cells at {args.resolution_m}m -> {args.output}")

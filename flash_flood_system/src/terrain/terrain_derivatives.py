"""
Phase 1: derive slope, aspect, flow direction/accumulation, TWI and
distance-to-stream from the conditioned+projected DEM using WhiteboxTools,
then sample every raster onto the prediction grid's cell centroids.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from whitebox import WhiteboxTools

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import PROJECTED_CRS
from database.db_utils import query_df, upsert_dataframe

wbt = WhiteboxTools()
wbt.set_verbose_mode(False)


def compute_terrain_rasters(dem_path: str, output_dir: str, stream_threshold: float = 1000.0) -> dict[str, str]:
    """
    Runs the WhiteboxTools terrain pipeline on a conditioned DEM.
    stream_threshold: minimum flow-accumulation (cells) to classify a cell as
    a stream when extracting the drainage network for distance-to-stream.
    Returns a dict of derivative name -> output raster path.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wbt.work_dir = str(out_dir)

    dem = str(Path(dem_path).resolve())
    paths = {
        "slope": str(out_dir / "slope.tif"),
        "aspect": str(out_dir / "aspect.tif"),
        "flow_direction": str(out_dir / "flow_direction.tif"),
        "flow_accumulation": str(out_dir / "flow_accumulation.tif"),
        "twi": str(out_dir / "twi.tif"),
        "streams": str(out_dir / "streams.tif"),
        "distance_to_stream": str(out_dir / "distance_to_stream.tif"),
    }

    wbt.slope(dem, paths["slope"])
    wbt.aspect(dem, paths["aspect"])
    wbt.d8_pointer(dem, paths["flow_direction"])
    wbt.d8_flow_accumulation(dem, paths["flow_accumulation"], out_type="cells")

    wbt.wetness_index(
        sca=paths["flow_accumulation"],
        slope=paths["slope"],
        output=paths["twi"],
    )

    wbt.extract_streams(paths["flow_accumulation"], paths["streams"], threshold=stream_threshold)
    wbt.euclidean_distance(paths["streams"], paths["distance_to_stream"])

    # Not a derivative WhiteboxTools computes — the input DEM itself is the
    # elevation raster. Included here so sample_terrain_to_grid() samples it
    # alongside everything else instead of leaving elevation_m unpopulated
    # (which would otherwise silently fail every downstream dropna() in
    # src/ml/feature_engineering.py, since elevation_m is a required feature).
    paths["elevation"] = dem

    return paths


def _sample_raster_at_points(raster_path: str, points_proj: gpd.GeoSeries) -> np.ndarray:
    with rasterio.open(raster_path) as src:
        coords = [(p.x, p.y) for p in points_proj]
        values = np.array([v[0] for v in src.sample(coords)], dtype="float64")
        nodata = src.nodata
        if nodata is not None:
            values[values == nodata] = np.nan
    return values


def sample_terrain_to_grid(grid: gpd.GeoDataFrame, terrain_rasters: dict[str, str]) -> pd.DataFrame:
    """
    grid: prediction grid GeoDataFrame (any CRS) with a 'cell_code' column.
    Returns a DataFrame with cell_code + one column per terrain derivative,
    ready to load into the terrain_features table (joined via grid_cells.cell_code).
    """
    centroids_proj = grid.to_crs(PROJECTED_CRS).geometry.centroid

    result = pd.DataFrame({"cell_code": grid["cell_code"].values})
    column_map = {
        "elevation": "elevation_m",
        "slope": "slope_deg",
        "aspect": "aspect_deg",
        "flow_direction": "flow_direction",
        "flow_accumulation": "flow_accumulation",
        "twi": "twi",
        "distance_to_stream": "distance_to_stream_m",
    }
    for key, col in column_map.items():
        if key in terrain_rasters:
            result[col] = _sample_raster_at_points(terrain_rasters[key], centroids_proj)

    return result


def write_terrain_features(terrain_df: pd.DataFrame) -> int:
    """
    Resolves cell_code -> cell_id against grid_cells (the grid must already be
    loaded via src.spatial.load_grid_to_db) and upserts into terrain_features,
    keyed on cell_id (its primary key).
    """
    cell_ids = query_df("SELECT cell_id, cell_code FROM grid_cells")
    merged = terrain_df.merge(cell_ids, on="cell_code", how="inner")

    unmatched = len(terrain_df) - len(merged)
    if unmatched:
        print(f"WARNING: {unmatched} cells had terrain values but no matching cell_code in grid_cells.")

    feature_cols = [c for c in merged.columns if c not in ("cell_code", "cell_id")]
    upsert_dataframe(
        merged[["cell_id"] + feature_cols],
        "terrain_features",
        conflict_columns=["cell_id"],
        update_columns=feature_cols,
    )
    return len(merged)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", required=True, help="Conditioned + reprojected DEM (see dem_processing.py)")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--grid", required=True, help="Prediction grid vector file (see grid_generator.py)")
    parser.add_argument("--out-csv", help="Also/instead save the sampled values to CSV")
    parser.add_argument(
        "--write-db", action="store_true",
        help="Load into terrain_features (requires the grid already loaded via src.spatial.load_grid_to_db)",
    )
    args = parser.parse_args()
    if not args.out_csv and not args.write_db:
        parser.error("Provide --out-csv and/or --write-db")

    rasters = compute_terrain_rasters(args.dem, args.output_dir)
    grid_gdf = gpd.read_file(args.grid)
    terrain_df = sample_terrain_to_grid(grid_gdf, rasters)

    if args.out_csv:
        terrain_df.to_csv(args.out_csv, index=False)
        print(f"Sampled terrain derivatives for {len(terrain_df)} cells -> {args.out_csv}")
    if args.write_db:
        n = write_terrain_features(terrain_df)
        print(f"Loaded terrain_features for {n} cells.")

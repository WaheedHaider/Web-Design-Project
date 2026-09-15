"""
Run this on any downloaded shapefile or raster BEFORE ingesting it — Survey of
India / HydroSHEDS files rarely use the exact column/band names our scripts
expect, so check here first rather than guessing --column-map values.

Usage:
    python -m src.ingestion.inspect_source --vector data/raw/boundaries/uk_villages.shp
    python -m src.ingestion.inspect_source --raster data/raw/dem/uk_dem_conditioned.tif
"""
from __future__ import annotations

import argparse

import geopandas as gpd
import rasterio


def inspect_vector(path: str) -> None:
    gdf = gpd.read_file(path)
    print(f"\n--- {path} ---")
    print(f"Feature count : {len(gdf)}")
    print(f"CRS           : {gdf.crs}")
    print(f"Geometry type : {gdf.geom_type.unique().tolist()}")
    print(f"Bounds        : {tuple(gdf.total_bounds)}")
    print(f"Columns       : {[c for c in gdf.columns if c != 'geometry']}")
    print("Sample row:")
    sample = gdf.drop(columns="geometry").iloc[0] if len(gdf) else "  (empty)"
    print(sample)
    invalid = (~gdf.geometry.is_valid).sum()
    if invalid:
        print(f"WARNING: {invalid} invalid geometries (admin_boundaries.py auto-repairs these with buffer(0))")


def inspect_raster(path: str) -> None:
    with rasterio.open(path) as src:
        print(f"\n--- {path} ---")
        print(f"CRS        : {src.crs}")
        print(f"Size       : {src.width} x {src.height} ({src.count} band(s))")
        print(f"Resolution : {src.res}")
        print(f"Bounds     : {src.bounds}")
        print(f"Nodata     : {src.nodata}")
        print(f"Dtype      : {src.dtypes}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector", help="Path to a shapefile/GeoPackage/GeoJSON")
    parser.add_argument("--raster", help="Path to a GeoTIFF/DEM")
    args = parser.parse_args()

    if not args.vector and not args.raster:
        parser.error("Provide --vector and/or --raster")

    if args.vector:
        inspect_vector(args.vector)
    if args.raster:
        inspect_raster(args.raster)

"""
Phase 1: load Survey of India administrative shapefiles (state -> district ->
tehsil -> village) into PostGIS, after validating geometry and reprojecting
to the storage CRS (EPSG:4326).

Usage:
    python -m src.ingestion.admin_boundaries \
        --level village \
        --shapefile data/raw/boundaries/uttarakhand_villages.shp \
        --parent-fk-col district_id
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import GEOGRAPHIC_CRS
from database.db_utils import write_geodataframe

LEVEL_TABLE = {
    "state": "admin_states",
    "district": "admin_districts",
    "tehsil": "admin_tehsils",
    "village": "villages",
    "ward": "wards",
}

REQUIRED_NAME_COL = {
    "state": "state_name",
    "district": "district_name",
    "tehsil": "tehsil_name",
    "village": "village_name",
    "ward": "ward_name",
}


def load_and_validate(shapefile_path: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(shapefile_path)

    if gdf.empty:
        raise ValueError(f"{shapefile_path} contains no features.")

    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)

    gdf = gdf[gdf.geometry.notna()]

    if gdf.crs is None:
        raise ValueError(
            f"{shapefile_path} has no CRS defined — set it explicitly before ingesting."
        )
    if gdf.crs.to_string() != GEOGRAPHIC_CRS:
        gdf = gdf.to_crs(GEOGRAPHIC_CRS)

    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: g if g.geom_type.startswith("Multi") else gpd.GeoSeries([g]).unary_union
    )

    return gdf


def ingest(level: str, shapefile_path: str, column_map: dict[str, str] | None = None) -> None:
    if level not in LEVEL_TABLE:
        raise ValueError(f"Unknown admin level '{level}'. Expected one of {list(LEVEL_TABLE)}")

    gdf = load_and_validate(shapefile_path)

    if column_map:
        gdf = gdf.rename(columns=column_map)

    name_col = REQUIRED_NAME_COL[level]
    if name_col not in gdf.columns:
        raise ValueError(
            f"Expected a '{name_col}' column after mapping. "
            f"Available columns: {list(gdf.columns)}. Use --column-map to rename source fields."
        )

    table = LEVEL_TABLE[level]
    write_geodataframe(gdf, table, if_exists="append")
    print(f"Loaded {len(gdf)} '{level}' features into {table}.")


def _parse_column_map(pairs: list[str] | None) -> dict[str, str] | None:
    if not pairs:
        return None
    mapping = {}
    for pair in pairs:
        src, dst = pair.split("=")
        mapping[src] = dst
    return mapping


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", required=True, choices=list(LEVEL_TABLE))
    parser.add_argument("--shapefile", required=True)
    parser.add_argument(
        "--column-map",
        nargs="*",
        help="Rename source shapefile columns, e.g. DISTNAME=district_name",
    )
    args = parser.parse_args()

    ingest(args.level, args.shapefile, _parse_column_map(args.column_map))

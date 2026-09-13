"""SQLAlchemy engine + GeoPandas <-> PostGIS helpers shared across the pipeline."""
from __future__ import annotations

import geopandas as gpd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.settings import get_db_config

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_db_config().sqlalchemy_url)
    return _engine


def run_schema(schema_path: str | Path = None) -> None:
    """Executes database/schema.sql against flash_flood_db. Idempotent (IF NOT EXISTS)."""
    schema_path = Path(schema_path) if schema_path else Path(__file__).parent / "schema.sql"
    ddl = schema_path.read_text()
    with get_engine().begin() as conn:
        conn.execute(text(ddl))


def read_table(table_name: str, geom_col: str = "geom") -> gpd.GeoDataFrame:
    return gpd.read_postgis(f"SELECT * FROM {table_name}", get_engine(), geom_col=geom_col)


def write_geodataframe(
    gdf: gpd.GeoDataFrame,
    table_name: str,
    if_exists: str = "append",
    geom_col: str = "geom",
) -> None:
    """Writes a GeoDataFrame to PostGIS. gdf must already be in EPSG:4326 to match schema."""
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    gdf = gdf.rename(columns={gdf.geometry.name: geom_col}).set_geometry(geom_col)
    gdf.to_postgis(table_name, get_engine(), if_exists=if_exists, index=False)


def query_df(sql: str, params: dict | None = None):
    import pandas as pd

    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


if __name__ == "__main__":
    run_schema()
    print("Schema applied to flash_flood_db.")

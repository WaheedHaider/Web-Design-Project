"""SQLAlchemy engine + GeoPandas <-> PostGIS helpers shared across the pipeline."""
from __future__ import annotations

import uuid

import geopandas as gpd
import pandas as pd
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def upsert_dataframe(
    df: pd.DataFrame,
    table_name: str,
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
) -> None:
    """
    INSERT ... ON CONFLICT (conflict_columns) DO UPDATE. Use when a row may or
    may not already exist (e.g. the first hydrological_threat write for a new
    cell/timestamp). `table_name` must already have a UNIQUE index/constraint
    on exactly `conflict_columns` (see database/schema.sql).

    update_columns defaults to every non-conflict column in df, but pass it
    explicitly to update only some columns — e.g. writing hydrological_threat
    without clobbering an ml_probability a later step may have already set.
    """
    if df.empty:
        return

    engine = get_engine()
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)

    update_columns = update_columns or [c for c in df.columns if c not in conflict_columns]
    records = df.where(pd.notnull(df), None).to_dict(orient="records")

    stmt = pg_insert(table).values(records)
    update_dict = {col: getattr(stmt.excluded, col) for col in update_columns}
    stmt = stmt.on_conflict_do_update(index_elements=conflict_columns, set_=update_dict)

    with engine.begin() as conn:
        conn.execute(stmt)


def bulk_update(
    df: pd.DataFrame,
    table_name: str,
    key_columns: list[str],
    update_columns: list[str],
) -> int:
    """
    UPDATEs existing rows only (no insert), matched on key_columns, via a
    throwaway staging table + a single UPDATE...FROM join. Use this instead
    of upsert_dataframe when a row is REQUIRED to already exist — e.g.
    predict.py filling in ml_probability/combined_risk/confidence on the row
    src/hydrology/ffg_engine.py already wrote for that cell/valid_for/model_version.
    Rows in df with no matching existing row are silently skipped (0 rows
    updated for them) rather than inserted, since a prediction with no
    hydrological_threat should not exist.
    Returns the number of rows actually updated.
    """
    if df.empty:
        return 0

    engine = get_engine()
    staging_table = f"_staging_{table_name}_{uuid.uuid4().hex[:8]}"
    cols = key_columns + update_columns

    with engine.begin() as conn:
        df[cols].where(pd.notnull(df[cols]), None).to_sql(
            staging_table, conn, index=False, if_exists="replace"
        )
        set_clause = ", ".join(f"{c} = s.{c}" for c in update_columns)
        join_clause = " AND ".join(f"t.{c} = s.{c}" for c in key_columns)
        result = conn.execute(
            text(
                f'UPDATE "{table_name}" t SET {set_clause} '
                f'FROM "{staging_table}" s WHERE {join_clause}'
            )
        )
        conn.execute(text(f'DROP TABLE "{staging_table}"'))
        return result.rowcount


if __name__ == "__main__":
    run_schema()
    print("Schema applied to flash_flood_db.")

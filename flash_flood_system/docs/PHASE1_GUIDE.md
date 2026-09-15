# Phase 1 Execution Guide — Data & Geographic Foundation

Goal: administrative boundaries + DEM/terrain + prediction grid loaded into
PostGIS for Uttarakhand (or a chosen pilot watershed — see recommendation in
`docs/ARCHITECTURE.md`).

## 0. Environment

```bash
cd flash_flood_system
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # set FFS_DB_* to your local PostGIS credentials
python -m database.db_utils   # applies schema.sql (safe to re-run — IF NOT EXISTS)
```

If you're re-running this against a database that already has an older
version of `schema.sql` applied (from before the fixes below), drop and
recreate `flash_flood_db` first — the changes (nullable parent FKs, new
unique indexes, `model_version NOT NULL DEFAULT`) aren't expressed as safe
`ALTER`s, since nothing had been loaded against the old schema yet.

## 1. Inspect what you've already downloaded

Before mapping any columns, check what's actually in each file — Survey of
India / HydroSHEDS files rarely match our schema's column names:

```bash
python -m src.ingestion.inspect_source --vector data/raw/boundaries/<your_file>.shp
python -m src.ingestion.inspect_source --raster data/raw/dem/<your_dem>.tif
```

This prints the CRS, geometry type, feature count, and every column name +
a sample row (for vectors), or CRS/size/resolution/nodata (for rasters) —
use the column names it prints to build your `--column-map` in step 3.

### Clipping full-extent downloads first

HydroSHEDS ships continent- or subcontinent-sized tiles, so a full download
set runs to several GB while the pilot area needs a tiny fraction of it.
`scripts/clip_to_pilot_area.py` cuts everything down to the 5 pilot districts
(Uttarkashi, Chamoli, Rudraprayag, Bageshwar, Pithoragarh) losslessly:

```bash
python scripts/clip_to_pilot_area.py \
    --input-dir  /path/to/full_downloads \
    --output-dir /path/to/pilot_clipped
```

Rasters are windowed-read (a multi-GB DEM never loads fully into RAM) and
rewritten with DEFLATE compression; vectors are bbox-filtered and written as
single-file GeoPackages. Add `--dry-run` to preview, `--boundary <file>` to
use a real district shapefile's extent instead of the built-in envelope.

The default extent is deliberately padded (`--buffer-deg`, default 0.1°):
flash-flood hydrology depends on upstream contributing area that often lies
outside the district being assessed, so a tight district clip would discard
terrain the model needs. For the same reason, use the flow-direction and
flow-accumulation rasters as downloaded — do not recompute flow accumulation
from a clipped DEM, since clipping truncates upstream catchments.

Place raw downloads under `data/raw/` (gitignored):

| Dataset | Where | Destination |
|---|---|---|
| Uttarakhand admin shapefiles (state/district/tehsil/village) | Survey of India | `data/raw/boundaries/` |
| HydroBASINS (watersheds) | HydroSHEDS | `data/raw/hydro/` |
| HydroRIVERS | HydroSHEDS | `data/raw/hydro/` |
| Conditioned DEM | HydroSHEDS | `data/raw/dem/` |
| Historical landslides | GSI Bhu-Sanket | `data/raw/landslides/` |

## 2. Load HydroSHEDS watersheds (if you have HydroBASINS)

No dedicated script yet for this one — it's a plain geometry+attribute load,
same shape as admin boundaries:

```python
import geopandas as gpd
from database.db_utils import write_geodataframe

gdf = gpd.read_file("data/raw/hydro/uttarakhand_hybas.shp").to_crs("EPSG:4326")
gdf = gdf.rename(columns={"HYBAS_ID": "hybas_id", "PFAF_ID": "pfaf_id", "UP_AREA": "upstream_area_km2"})
write_geodataframe(gdf[["hybas_id", "pfaf_id", "upstream_area_km2", "geometry"]], "watersheds")
```

## 3. Load administrative boundaries

Run once per level, in order (state → district → tehsil → village → ward).
Column names in Survey of India shapefiles rarely match the schema exactly —
use `--column-map SRC=dst` to rename before load (check real names with
`inspect_source.py` from step 1 first).

Parent FKs (`district_id`, `tehsil_id`, ...) are resolved **automatically**
after each load via a spatial join (`ST_Within` against the parent polygon)
— you don't need to hand-map them.

```bash
python -m src.ingestion.admin_boundaries --level state \
    --shapefile data/raw/boundaries/uttarakhand_state.shp \
    --column-map STATE=state_name STCODE=state_code

python -m src.ingestion.admin_boundaries --level district \
    --shapefile data/raw/boundaries/uttarakhand_districts.shp \
    --column-map DISTRICT=district_name

python -m src.ingestion.admin_boundaries --level tehsil \
    --shapefile data/raw/boundaries/uttarakhand_tehsils.shp \
    --column-map TEHSIL=tehsil_name

python -m src.ingestion.admin_boundaries --level village \
    --shapefile data/raw/boundaries/uttarakhand_villages.shp \
    --column-map VILLNAME=village_name
```

Each command prints how many rows resolved a parent FK vs. the total — if
some don't match, it's usually a CRS or boundary-vintage mismatch between the
child and parent shapefile; those specific rows need manual review.

## 4. Generate and load the prediction grid

```bash
# Dissolve the state boundary (or your chosen pilot watershed) into one polygon first
python -m src.spatial.grid_generator \
    --boundary data/raw/boundaries/uttarakhand_state.shp \
    --output data/processed/grid/base_grid_250m.gpkg \
    --resolution-m 250

python -m src.spatial.load_grid_to_db --grid data/processed/grid/base_grid_250m.gpkg
```

`load_grid_to_db.py` inserts `cell_code`/`resolution_m`/`geom`; `centroid` is
filled automatically by a database trigger.

## 5. Process the DEM and derive + load terrain

```bash
python -m src.terrain.dem_processing \
    --dem data/raw/dem/uttarakhand_dem_conditioned.tif \
    --boundary data/raw/boundaries/uttarakhand_state.shp \
    --output-dir data/processed/terrain

python -m src.terrain.terrain_derivatives \
    --dem data/processed/terrain/dem_projected.tif \
    --output-dir data/processed/terrain \
    --grid data/processed/grid/base_grid_250m.gpkg \
    --write-db --out-csv data/processed/terrain/terrain_features.csv
```

`--write-db` resolves each cell's `cell_code` to its `cell_id` and loads
straight into `terrain_features` (including `elevation_m`, sampled directly
from the DEM); `--out-csv` is optional and just for inspection.

## 6. Assign each grid cell to its ward, village and watershed

```bash
python -m src.spatial.assign_admin_watershed
```

Fills `grid_cells.ward_id` / `village_id` / `watershed_id` via `ST_Within`
against each cell's centroid. This must run after both boundaries (step 3)
and the grid (step 4) are loaded, and again any time cells are refined to
100m — everything downstream of Phase 1 (ward aggregation, alerts) groups by
these FKs.

## 7. Verify

```sql
SELECT count(*) FROM admin_states;
SELECT count(*) FROM villages;
SELECT count(*) FROM grid_cells;
SELECT count(*) FROM terrain_features;
SELECT count(*) FROM grid_cells WHERE ward_id IS NOT NULL;
```

Once these are populated, Phase 1 is complete and Phase 2 (rainfall/soil
moisture ingestion, IoT) can begin.

## Phase 3/4 run order (once rainfall + soil moisture ingestion exists)

The hydrological engine must write to `risk_predictions` **before**
`predict.py` runs — it reads back the row `ffg_engine.py` wrote for the same
`(cell_id, valid_for, model_version)` key rather than defaulting to zero
threat for cells it hasn't scored:

```bash
python -m src.hydrology.ffg_engine --valid-for 2026-09-13T06:00:00
python -m src.ml.predict --valid-for 2026-09-13T06:00:00
python -m src.aggregation.ward_aggregation --valid-for 2026-09-13T06:00:00
```

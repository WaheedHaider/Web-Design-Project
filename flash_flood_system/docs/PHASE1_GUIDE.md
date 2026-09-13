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

## 1. Get the data

Place raw downloads under `data/raw/` (gitignored):

| Dataset | Where | Destination |
|---|---|---|
| Uttarakhand admin shapefiles (state/district/tehsil/village) | Survey of India | `data/raw/boundaries/` |
| HydroBASINS (watersheds) | HydroSHEDS | `data/raw/hydro/` |
| HydroRIVERS | HydroSHEDS | `data/raw/hydro/` |
| Conditioned DEM | HydroSHEDS | `data/raw/dem/` |
| Historical landslides | GSI Bhu-Sanket | `data/raw/landslides/` |

## 2. Load administrative boundaries

Run once per level, in order (state → district → tehsil → village), so FK
references resolve. Column names in Survey of India shapefiles rarely match the
schema exactly — use `--column-map SRC=dst` to rename before load.

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

`admin_boundaries.py` currently loads geometry + name columns only. Once loaded,
set each child row's parent FK (`district_id`, `tehsil_id`, ...) with a spatial
join (`gpd.sjoin`) against the parent table before/while loading — this is left
as a data-specific step since Survey of India shapefiles vary in whether they
already carry a parent code column.

## 3. Generate the prediction grid

```bash
# Dissolve the state boundary (or your chosen pilot watershed) into one polygon first
python -m src.spatial.grid_generator \
    --boundary data/raw/boundaries/uttarakhand_state.shp \
    --output data/processed/grid/base_grid_250m.gpkg \
    --resolution-m 250
```

Load the resulting grid into `grid_cells` (write a small loader with
`database.db_utils.write_geodataframe`, or extend `grid_generator.py`'s `__main__`
once the target table's `watershed_id`/`ward_id` spatial joins are ready).

## 4. Process the DEM and derive terrain

```bash
python -m src.terrain.dem_processing \
    --dem data/raw/dem/uttarakhand_dem_conditioned.tif \
    --boundary data/raw/boundaries/uttarakhand_state.shp \
    --output-dir data/processed/terrain

python -m src.terrain.terrain_derivatives \
    --dem data/processed/terrain/dem_projected.tif \
    --output-dir data/processed/terrain \
    --grid data/processed/grid/base_grid_250m.gpkg \
    --out-csv data/processed/terrain/terrain_features.csv
```

Load `terrain_features.csv` into the `terrain_features` table, joined to
`grid_cells` via `cell_code`.

## 5. Verify

```sql
SELECT count(*) FROM admin_states;
SELECT count(*) FROM villages;
SELECT count(*) FROM grid_cells;
SELECT count(*) FROM terrain_features;
```

Once these are populated, Phase 1 is complete and Phase 2 (rainfall/soil
moisture ingestion, IoT) can begin.

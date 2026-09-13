# Progress

## Decisions carried over (no code required)

- [x] Architecture finalized (data → spatial → hydrology → ML → grid → ward → dashboard → alerts)
- [x] Tech stack selected (see root README / requirements.txt)
- [x] Final geographic target: Himalayan belt; Phase 1 dev scope: Uttarakhand
- [x] PostGIS installed, `flash_flood_db` created, `postgis` extension enabled
- [x] Phase 1 data sources identified (Survey of India, HydroBASINS, HydroRIVERS, HydroSHEDS DEM, GSI Bhu-Sanket)
- [x] Admin dataset: Survey of India, state = Uttarakhand, state→district→tehsil→village
- [x] File format: Shapefile
- [x] DEM conditioning: Conditioned DEM

## Code scaffold (this session — progress was 0 before this)

- [x] Project structure created (`flash_flood_system/`)
- [x] `config/config.yaml` + `config/settings.py` — non-secret config + .env-based secrets
- [x] `database/schema.sql` — full PostGIS DDL (admin hierarchy, watersheds/rivers,
      grid_cells, terrain_features, rainfall, soil_moisture, landslides, flood_events,
      iot_sensors/observations, risk_predictions, ward_risk, alerts)
- [x] `database/db_utils.py` — SQLAlchemy engine, schema runner, GeoDataFrame I/O helpers
- [x] `src/ingestion/admin_boundaries.py` — shapefile validation/reprojection/PostGIS load
- [x] `src/spatial/grid_generator.py` — 250m fishnet generation + 100m high-risk refinement
- [x] `src/terrain/dem_processing.py` — DEM clip + reproject
- [x] `src/terrain/terrain_derivatives.py` — WhiteboxTools slope/aspect/flow/TWI/distance-to-stream + grid sampling
- [x] `src/hydrology/antecedent_wetness.py` — soil moisture + 72h rainfall wetness index
- [x] `src/hydrology/ffg_engine.py` — dynamic rainfall threshold + hydrological threat score
- [x] `src/ml/feature_engineering.py` — training table assembly from DB
- [x] `src/ml/train_model.py` — calibrated XGBoost training + evaluation
- [x] `src/ml/predict.py` — score current conditions, combine ML + hydrological threat
- [x] `src/aggregation/ward_aggregation.py` — weighted ward risk (avg/max/high-risk-area%/exposure)
- [x] Docs: README, ARCHITECTURE, PHASE1_GUIDE

All of the above is runnable code, but every script needs real input data
(shapefiles, DEM, rainfall/soil-moisture feeds, historical event records) that
this session could not fetch (large licensed/institutional geospatial datasets).
**Nothing has been executed against real Uttarakhand data yet.**

## Pipeline fixes (second pass — closing gaps found by inspection, not by running against data)

These were found by re-reading the scaffold, not by hitting them at runtime —
there's still no real data to run against. Each is a concrete bug or missing
link, not a design opinion:

- [x] `predict.py` read `hydrological_threat` from a column nothing ever wrote —
      `ffg_engine.py` now writes it to `risk_predictions` first (`--valid-for`,
      DB mode), and `predict.py` only proceeds for cells that row exists for.
- [x] No uniqueness anywhere → reruns duplicated rows. Added unique indexes on
      `rainfall`, `soil_moisture`, `risk_predictions`, `ward_risk`, plus a
      generic `upsert_dataframe`/`bulk_update` in `database/db_utils.py`.
- [x] `grid_cells.ward_id`/`village_id`/`watershed_id` were never populated —
      added `src/spatial/assign_admin_watershed.py` (`ST_Within` on centroid).
- [x] `confidence` was never computed — `predict.py` now derives it from
      ML/hydrology agreement (placeholder pending Phase 7 calibration).
- [x] Exact-timestamp joins between `rainfall` and `soil_moisture` would return
      near-zero rows against real multi-source data (different revisit times) —
      switched to an "as-of" `LATERAL` join in `feature_engineering.py`,
      `predict.py`, and `ffg_engine.py`.
- [x] `admin_boundaries.py` required parent FKs (`district_id`, ...) to be
      hand-mapped — now resolved automatically via `ST_Within(ST_PointOnSurface(...))`
      after each load, with unmatched-row counts printed for review.
- [x] Single-`Polygon` shapefiles weren't actually converted to `MultiPolygon`
      before insert (the old code's `unary_union` trick was a no-op on a lone
      geometry) — fixed with `shapely.geometry.MultiPolygon([g])`.
- [x] `elevation_m` is a required ML feature but nothing sampled it from the
      DEM — every training/prediction row would have silently been dropped by
      `dropna(subset=FEATURE_COLUMNS)`. `terrain_derivatives.py` now samples
      the DEM itself for it.
- [x] `feature_engineering.py`'s flood label used `flood_event_cells.cell_id
      IS NOT NULL` (unconditional on time) instead of the time-windowed
      `flood_events` join — this would have labeled *every* timestamp for a
      once-flooded cell as positive, not just timestamps during the actual
      event. Fixed to check the time-windowed join instead.
- [x] No loader existed from a generated grid file into `grid_cells`, and no
      loader from sampled terrain CSVs into `terrain_features` — added
      `src/spatial/load_grid_to_db.py` and `terrain_derivatives.write_terrain_features`
      (`--write-db`).
- [x] Added GIST spatial indexes on every admin/hydro geometry column (only
      `grid_cells` had one before) — needed for the `ST_Within` joins above to
      be fast at scale.
- [x] Added `src/ingestion/inspect_source.py` — prints CRS/columns/geometry
      type for any downloaded shapefile or raster before you write a
      `--column-map`, since Survey of India/HydroSHEDS files rarely match our
      column names out of the box.

**Still open** (documented, not yet fixed — need a decision or real data
first): grid generation is in-memory and won't scale past a pilot watershed;
WhiteboxTools/rasterio processing isn't tiled for a statewide DEM; ML training
split is random rather than spatial/temporal (leakage risk); no
orchestration/scheduler for Phase 2's real-time cadence; no tests; no API/dashboard.
See `docs/ARCHITECTURE.md` for the scale/ML-quality recommendations.

## Not started

- [ ] Download + inspect Uttarakhand admin shapefiles, HydroBASINS/HydroRIVERS, conditioned DEM, GSI landslide data
- [ ] Run `admin_boundaries.py` against real shapefiles → populate admin_states/districts/tehsils/villages/wards
- [ ] Run `grid_generator.py` against the real Uttarakhand (or pilot watershed) boundary
- [ ] Run `dem_processing.py` + `terrain_derivatives.py` against the real conditioned DEM
- [ ] Rainfall ingestion (GPM IMERG / GSMaP / IMD) — Phase 2
- [ ] Soil moisture ingestion (SMAP / ERA5-Land) — Phase 2
- [ ] IoT pipeline (ESP32 → MQTT → DB) — Phase 2
- [ ] Historical ML training dataset assembly (real flood_events/landslides) — Phase 4
- [ ] Hydrological threshold calibration against historical events — Phase 3
- [ ] ML model actually trained/validated on real data — Phase 4
- [ ] Exposure layer (population/infrastructure) — Phase 5
- [ ] GIS dashboard (React + MapLibre) — Phase 5
- [ ] Alert engine wiring (thresholds → notifications) — Phase 6
- [ ] Historical backtesting / false-alarm & missed-event validation — Phase 7

## Immediate next step

Follow `docs/PHASE1_GUIDE.md` (updated run order: inspect → boundaries →
grid+load → terrain+load → ward/watershed assignment) against whatever
shapefiles/DEM you've already downloaded.

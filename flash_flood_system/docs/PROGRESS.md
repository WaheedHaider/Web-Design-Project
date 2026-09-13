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

Follow `docs/PHASE1_GUIDE.md`: obtain the Uttarakhand shapefiles + conditioned
DEM, then run the ingestion → grid → terrain scripts in order.

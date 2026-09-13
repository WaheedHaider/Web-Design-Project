-- Flash Flood Prediction System — PostGIS schema
-- Target DB: flash_flood_db (created in Phase 0 setup)
-- Run once after `CREATE EXTENSION postgis;`

CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- ADMINISTRATIVE HIERARCHY (Survey of India boundaries)
-- ============================================================

-- state_id/district_id/tehsil_id/village_id are nullable on the CHILD level
-- itself so admin_boundaries.py can insert geometry first and resolve the
-- parent FK afterwards via a spatial join (see resolve_parent_fk in
-- src/ingestion/admin_boundaries.py) rather than requiring it hand-mapped
-- from source shapefile columns.

CREATE TABLE IF NOT EXISTS admin_states (
    state_id        SERIAL PRIMARY KEY,
    state_code      VARCHAR(10) UNIQUE NOT NULL,
    state_name      VARCHAR(100) NOT NULL,
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_states_geom ON admin_states USING GIST (geom);

CREATE TABLE IF NOT EXISTS admin_districts (
    district_id     SERIAL PRIMARY KEY,
    state_id        INTEGER REFERENCES admin_states(state_id),
    district_code   VARCHAR(10),
    district_name   VARCHAR(100) NOT NULL,
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_districts_geom ON admin_districts USING GIST (geom);

CREATE TABLE IF NOT EXISTS admin_tehsils (
    tehsil_id       SERIAL PRIMARY KEY,
    district_id     INTEGER REFERENCES admin_districts(district_id),
    tehsil_code     VARCHAR(10),
    tehsil_name     VARCHAR(100) NOT NULL,
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_tehsils_geom ON admin_tehsils USING GIST (geom);

CREATE TABLE IF NOT EXISTS villages (
    village_id      SERIAL PRIMARY KEY,
    tehsil_id       INTEGER REFERENCES admin_tehsils(tehsil_id),
    village_code    VARCHAR(20),
    village_name    VARCHAR(150) NOT NULL,
    population      INTEGER,
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_villages_geom ON villages USING GIST (geom);

CREATE TABLE IF NOT EXISTS wards (
    ward_id         SERIAL PRIMARY KEY,
    village_id      INTEGER REFERENCES villages(village_id),
    ward_code       VARCHAR(20),
    ward_name       VARCHAR(150) NOT NULL,
    population      INTEGER,
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wards_geom ON wards USING GIST (geom);

-- ============================================================
-- HYDROLOGICAL GEOGRAPHY (HydroSHEDS)
-- ============================================================

CREATE TABLE IF NOT EXISTS watersheds (
    watershed_id       SERIAL PRIMARY KEY,
    hybas_id           BIGINT UNIQUE,           -- HydroBASINS identifier
    pfaf_id            BIGINT,                  -- Pfafstetter code
    upstream_area_km2  DOUBLE PRECISION,
    geom               GEOMETRY(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_watersheds_geom ON watersheds USING GIST (geom);

CREATE TABLE IF NOT EXISTS rivers (
    river_id        SERIAL PRIMARY KEY,
    hyriv_id        BIGINT UNIQUE,              -- HydroRIVERS identifier
    river_name      VARCHAR(150),
    order_strahler  INTEGER,
    watershed_id    INTEGER REFERENCES watersheds(watershed_id),
    geom            GEOMETRY(MultiLineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rivers_geom ON rivers USING GIST (geom);

-- ============================================================
-- PREDICTION GRID
-- ============================================================

CREATE TABLE IF NOT EXISTS grid_cells (
    cell_id             BIGSERIAL PRIMARY KEY,
    cell_code           VARCHAR(40) UNIQUE NOT NULL,  -- e.g. "C000123_250M"
    resolution_m        INTEGER NOT NULL,             -- 250 or 100 (refined)
    parent_cell_id      BIGINT REFERENCES grid_cells(cell_id), -- set when refined from a 250m parent
    watershed_id        INTEGER REFERENCES watersheds(watershed_id),
    ward_id             INTEGER REFERENCES wards(ward_id),
    village_id          INTEGER REFERENCES villages(village_id),
    geom                GEOMETRY(Polygon, 4326) NOT NULL,
    -- filled automatically by trg_set_grid_cell_centroid below if left NULL on insert
    centroid            GEOMETRY(Point, 4326)
);

CREATE INDEX IF NOT EXISTS idx_grid_cells_geom ON grid_cells USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_cells_centroid ON grid_cells USING GIST (centroid);
CREATE INDEX IF NOT EXISTS idx_grid_cells_ward ON grid_cells (ward_id);
CREATE INDEX IF NOT EXISTS idx_grid_cells_watershed ON grid_cells (watershed_id);
CREATE INDEX IF NOT EXISTS idx_grid_cells_parent ON grid_cells (parent_cell_id);

-- Loaders (src/spatial/load_grid_to_db.py) only insert cell_code/resolution_m/geom;
-- this fills centroid server-side so PostGIS's own centroid definition is the
-- single source of truth instead of recomputing it client-side.
CREATE OR REPLACE FUNCTION set_grid_cell_centroid() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.centroid IS NULL THEN
        NEW.centroid := ST_Centroid(NEW.geom);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_set_grid_cell_centroid ON grid_cells;
CREATE TRIGGER trg_set_grid_cell_centroid
    BEFORE INSERT OR UPDATE OF geom ON grid_cells
    FOR EACH ROW EXECUTE FUNCTION set_grid_cell_centroid();

-- ============================================================
-- TERRAIN (derived once per grid cell from the conditioned DEM)
-- ============================================================

CREATE TABLE IF NOT EXISTS terrain_features (
    cell_id                 BIGINT PRIMARY KEY REFERENCES grid_cells(cell_id),
    elevation_m             DOUBLE PRECISION,
    slope_deg               DOUBLE PRECISION,
    aspect_deg              DOUBLE PRECISION,
    flow_direction          INTEGER,
    flow_accumulation       DOUBLE PRECISION,
    twi                     DOUBLE PRECISION,     -- topographic wetness index
    distance_to_stream_m    DOUBLE PRECISION,
    relative_elevation_m    DOUBLE PRECISION,
    updated_at              TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- TIME-SERIES OBSERVATIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS rainfall (
    id              BIGSERIAL PRIMARY KEY,
    cell_id         BIGINT NOT NULL REFERENCES grid_cells(cell_id),
    observed_at     TIMESTAMPTZ NOT NULL,
    source          VARCHAR(30) NOT NULL,   -- IMERG | GSMaP | IMD | GAUGE | FORECAST
    rain_mm_30min   DOUBLE PRECISION,
    rain_mm_1h      DOUBLE PRECISION,
    rain_mm_3h      DOUBLE PRECISION,
    rain_mm_6h      DOUBLE PRECISION,
    rain_mm_12h     DOUBLE PRECISION,
    rain_mm_24h     DOUBLE PRECISION,
    rain_mm_72h     DOUBLE PRECISION,
    is_forecast     BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_rainfall_cell_time ON rainfall (cell_id, observed_at);
-- Lets ingestion upsert (ON CONFLICT) instead of duplicating rows on re-run.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rainfall_cell_time_source ON rainfall (cell_id, observed_at, source);

CREATE TABLE IF NOT EXISTS soil_moisture (
    id                  BIGSERIAL PRIMARY KEY,
    cell_id             BIGINT NOT NULL REFERENCES grid_cells(cell_id),
    observed_at         TIMESTAMPTZ NOT NULL,
    source              VARCHAR(30) NOT NULL,  -- SMAP | ERA5_LAND | IOT
    soil_moisture_pct   DOUBLE PRECISION,
    antecedent_wetness_index DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_soil_moisture_cell_time ON soil_moisture (cell_id, observed_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_soil_moisture_cell_time_source ON soil_moisture (cell_id, observed_at, source);

-- ============================================================
-- HISTORICAL EVENTS (for ML labels + calibration)
-- ============================================================

CREATE TABLE IF NOT EXISTS landslides (
    landslide_id    SERIAL PRIMARY KEY,
    source          VARCHAR(30) DEFAULT 'GSI_BHU_SANKET',
    event_date      DATE,
    cell_id         BIGINT REFERENCES grid_cells(cell_id),
    severity        VARCHAR(20),
    geom            GEOMETRY(Point, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS flood_events (
    event_id            SERIAL PRIMARY KEY,
    source              VARCHAR(30) DEFAULT 'CWC',
    event_start         TIMESTAMPTZ NOT NULL,
    event_end           TIMESTAMPTZ,
    watershed_id        INTEGER REFERENCES watersheds(watershed_id),
    severity            VARCHAR(20),
    fatalities          INTEGER,
    description         TEXT,
    geom                GEOMETRY(MultiPolygon, 4326)
);

CREATE TABLE IF NOT EXISTS flood_event_cells (
    event_id        INTEGER NOT NULL REFERENCES flood_events(event_id),
    cell_id         BIGINT NOT NULL REFERENCES grid_cells(cell_id),
    was_flooded     BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (event_id, cell_id)
);

-- ============================================================
-- IOT (Phase 2)
-- ============================================================

CREATE TABLE IF NOT EXISTS iot_sensors (
    sensor_id       VARCHAR(30) PRIMARY KEY,   -- ESP32 device id
    sensor_type     VARCHAR(30) NOT NULL,       -- RAIN_GAUGE | SOIL_MOISTURE | WATER_LEVEL | WEATHER_STATION
    cell_id         BIGINT REFERENCES grid_cells(cell_id),
    installed_at    DATE,
    status          VARCHAR(20) DEFAULT 'ACTIVE', -- ACTIVE | OFFLINE | FAULTY
    geom            GEOMETRY(Point, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS iot_observations (
    id              BIGSERIAL PRIMARY KEY,
    sensor_id       VARCHAR(30) NOT NULL REFERENCES iot_sensors(sensor_id),
    observed_at     TIMESTAMPTZ NOT NULL,
    rainfall_mm     DOUBLE PRECISION,
    soil_moisture_pct DOUBLE PRECISION,
    water_level_cm  DOUBLE PRECISION,
    battery_v       DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_iot_obs_sensor_time ON iot_observations (sensor_id, observed_at);

-- ============================================================
-- PREDICTIONS + ALERTS (Phase 4-6 output)
-- ============================================================

CREATE TABLE IF NOT EXISTS risk_predictions (
    id                      BIGSERIAL PRIMARY KEY,
    cell_id                 BIGINT NOT NULL REFERENCES grid_cells(cell_id),
    predicted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_for               TIMESTAMPTZ NOT NULL,   -- forecast validity time
    hydrological_threat     DOUBLE PRECISION,       -- 0-1, from FFG-like engine (written first)
    ml_probability          DOUBLE PRECISION,       -- 0-1, from XGBoost/LightGBM (written second)
    combined_risk           DOUBLE PRECISION,       -- 0-1, calibrated combination
    confidence              DOUBLE PRECISION,       -- 0-1
    lead_time_minutes       INTEGER,
    -- NOT NULL: a NULL here would make the unique index below useless, since
    -- SQL treats every NULL as distinct and ON CONFLICT would never match.
    model_version           VARCHAR(30) NOT NULL DEFAULT 'v1'
);

CREATE INDEX IF NOT EXISTS idx_risk_pred_cell_time ON risk_predictions (cell_id, valid_for);
-- One row per (cell, valid_for, model_version): src/hydrology writes hydrological_threat
-- first via upsert, src/ml/predict.py then fills ml_probability/combined_risk/confidence
-- on that SAME row via a keyed update — see docs/PHASE1_GUIDE.md.
CREATE UNIQUE INDEX IF NOT EXISTS uq_risk_predictions_cell_valid_model
    ON risk_predictions (cell_id, valid_for, model_version);

CREATE TABLE IF NOT EXISTS ward_risk (
    id                      BIGSERIAL PRIMARY KEY,
    ward_id                 INTEGER NOT NULL REFERENCES wards(ward_id),
    valid_for               TIMESTAMPTZ NOT NULL,
    avg_risk                DOUBLE PRECISION,
    max_risk                DOUBLE PRECISION,
    high_risk_area_pct      DOUBLE PRECISION,
    exposure_score          DOUBLE PRECISION,
    ward_risk_score         DOUBLE PRECISION,
    confidence              DOUBLE PRECISION,
    risk_category           VARCHAR(20)  -- LOW | MODERATE | HIGH | CRITICAL
);

CREATE INDEX IF NOT EXISTS idx_ward_risk_ward_time ON ward_risk (ward_id, valid_for);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ward_risk_ward_time ON ward_risk (ward_id, valid_for);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id            BIGSERIAL PRIMARY KEY,
    ward_id             INTEGER NOT NULL REFERENCES wards(ward_id),
    issued_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    risk_level          VARCHAR(20) NOT NULL,  -- WATCH | WARNING | CRITICAL
    probability         DOUBLE PRECISION,
    lead_time_minutes   INTEGER,
    message             TEXT,
    status              VARCHAR(20) DEFAULT 'ACTIVE'  -- ACTIVE | EXPIRED | CANCELLED
);

CREATE INDEX IF NOT EXISTS idx_alerts_ward ON alerts (ward_id, issued_at);

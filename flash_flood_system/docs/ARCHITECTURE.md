# Architecture

## Pipeline

```
Data Sources (rainfall, soil moisture, DEM/terrain, historical events, forecast, IoT)
        ↓
Data Ingestion (Python / Xarray / GeoPandas)
        ↓
Spatial Engine (PostGIS, 100–250m grid, watersheds, villages/wards)
        ↓
Hydrological Engine (dynamic threshold)  +  Terrain derivatives (slope, flow, TWI)
        ↓
ML Risk Engine (XGBoost/LightGBM, calibrated probability)
        ↓
Fine-Grid Risk (probability, confidence, lead time)
        ↓
Village/Ward Aggregation (avg + max + high-risk-area% + exposure — not a plain mean)
        ↓
GIS Dashboard (React + MapLibre GL)
        ↓
Early Warning / Alerts (threshold + lead time + geo-targeted)
```

## Why grid *and* administrative boundaries

Water follows slopes/streams/watersheds; authorities act on villages/wards/tehsils/districts.
The system keeps both: hydrology drives the grid-cell prediction, then cells are
overlaid onto administrative geometry for the decision-making layer. See
`database/schema.sql` — `grid_cells` carries FKs to both `watershed_id` and `ward_id`.

## Hydrology vs. ML — two different questions

- **Hydrological engine** (`src/hydrology/`): calculative/domain-based. "Given rainfall
  and current watershed condition, how threatening is the hydrological situation?"
  Produces `hydrological_threat` (0-1).
- **ML engine** (`src/ml/`): data-driven. "Based on historical patterns and current
  conditions, how likely is a flash-flood event?" Produces `ml_probability` (0-1),
  calibrated (not just ranked) since alert thresholds depend on true probabilities.

`src/ml/predict.py` combines both into `combined_risk` — a weighted blend, not a
naive average, with weights recalibrated during Phase 7 historical backtesting.

## Grid resolution

Base grid: 250m (`grid.base_resolution_m` in `config/config.yaml`). Cells whose
predicted risk crosses `grid.high_risk_refine_threshold` (default 0.6) are
refined to 100m via `src/spatial/grid_generator.refine_cells`. We do not create
a 30m grid from 250m-native source data — that would be fake precision.

## Data honesty

The system reports **flood probability / risk / runoff-threat**, never a claimed
flood depth, unless a validated hydraulic model is built separately. Dashboard
and alert copy must not imply depth estimation.

## Recommended adjustments (SIH feasibility)

These are changes worth making relative to the original plan, given a hackathon
timeline and this session's inability to fetch large external geospatial datasets:

1. **Pick one pilot watershed for the demo, not all of Uttarakhand.** Full-state
   DEM processing + grid generation at 250m is tens of millions of cells and will
   not finish inside a hackathon build/demo cycle. Recommend picking a single
   flood-prone watershed (e.g. around a known landslide/flood-prone tehsil) to
   carry end-to-end — ingestion through dashboard — then argue the pipeline
   generalizes statewide. `config.yaml` is already structured to add states without
   code changes; do the same for a `pilot_watershed_id` scoping flag when real
   boundary data lands.
2. **Historical label scarcity is the single biggest risk** (also flagged in the
   original plan as the #1 challenge). Recommend budgeting time to build a
   *physically-informed synthetic label* fallback — e.g. label a cell/time as
   high-risk when `hydrological_threat` from the FFG-like engine exceeds a strict
   threshold AND it lies in a GSI-flagged susceptible zone — so the ML model has
   something to train on even if CWC/GSI event records for the pilot watershed are
   thin. Treat this explicitly as a fallback, not a substitute for real labels once
   available.
3. **Exposure layer**: rather than waiting on official population/infrastructure
   data, start with OpenStreetMap (buildings, roads, schools, hospitals) as the
   Phase 1 exposure proxy — it's immediately fetchable and good enough to
   demonstrate the hazard-vs-impact distinction in section 14 of the original plan.
4. **Confidence field**: define it now, don't leave it implicit. Recommend
   `confidence = f(data recency, sensor/satellite coverage density, model
   calibration error in that risk band)` — stub this as a fixed function in
   `src/ml/predict.py` once Phase 4 has a trained model, rather than a placeholder
   constant, so the dashboard's "Confidence: HIGH/LOW" field means something.
5. **IoT can be simulated for the demo.** Building physical ESP32 hardware is
   valuable but not required to demonstrate the architecture — a script that
   publishes synthetic MQTT payloads matching `iot_observations`' schema lets the
   dashboard and alert pipeline be fully demoed before hardware exists.

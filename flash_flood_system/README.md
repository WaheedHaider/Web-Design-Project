# Flash Flood Prediction System (SIH 2026)

A hyper-local flash-flood prediction and early-warning system for hilly/Himalayan
regions of India. Fuses satellite rainfall, soil moisture, terrain, historical
disaster data, forecasts and real-time IoT observations into fine-scale
(100–250m) risk predictions, aggregated to village/ward level for actionable,
lead-time-bearing warnings.

Initial development scope: **Uttarakhand**. The architecture is state-independent
so other Himalayan states (Himachal Pradesh, J&K, Ladakh, Sikkim, Arunachal
Pradesh, …) can be added later without redesign.

See `docs/ARCHITECTURE.md` for the full system design and `docs/PROGRESS.md`
for current status. Start with `docs/PHASE1_GUIDE.md` to run the geographic
foundation pipeline.

## Layout

```
flash_flood_system/
├── config/          # config.yaml (non-secret) + settings.py loader
├── database/         # PostGIS schema.sql + db_utils.py
├── data/
│   ├── raw/          # dem/, boundaries/, hydro/, landslides/ (gitignored)
│   ├── processed/     # terrain/, hydro/, grid/ (gitignored)
│   └── weather/       # rainfall/soil-moisture pulls (gitignored)
├── src/
│   ├── ingestion/     # admin boundary + (later) rainfall/soil-moisture loaders
│   ├── spatial/       # prediction grid generation/refinement
│   ├── terrain/       # DEM clip/reproject + slope/aspect/flow/TWI derivatives
│   ├── hydrology/     # antecedent wetness + FFG-like dynamic threshold engine
│   ├── ml/            # feature engineering, XGBoost training, prediction
│   └── aggregation/   # grid-cell -> ward/village risk aggregation
├── notebooks/         # exploratory analysis
├── outputs/           # trained models, exported risk layers (gitignored)
└── docs/
```

## Setup

```bash
cd flash_flood_system
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your local PostGIS credentials
python -m database.db_utils   # applies schema.sql to flash_flood_db
```

Requires PostgreSQL + PostGIS (`flash_flood_db`, `CREATE EXTENSION postgis;`)
already set up — this was completed in the initial project setup.

## Current phase: Phase 1 — Data & Geographic Foundation

Load Survey of India administrative boundaries and the conditioned HydroSHEDS
DEM for Uttarakhand, build the prediction grid, and derive terrain features.
See `docs/PHASE1_GUIDE.md` for the exact command sequence.

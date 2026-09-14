# Session Handoff — FFGS (SIH 2026)

Written at end of session `session_01SUWsAvy9k9kdmFKkifm8A8`, for whoever/whatever
continues this work next (a new Claude Code session, or you). Read this before
`docs/PROGRESS.md` — this is the narrative of *how* we got here and *exactly*
what to do next; PROGRESS.md is the phase-by-phase checklist.

## Repo / branch / PR — source of truth

- **Repo**: `WaheedHaider/Web-Design-Project` (public)
- **Branch**: `claude/jolly-bell-vtyick`
- **PR**: [#2](https://github.com/WaheedHaider/Web-Design-Project/pull/2) — open, clean, mergeable, no CI configured on this repo (so "clean" is as good as it gets)
- **Latest commit**: `bf152f8` — "clip_to_pilot_area.py: fix PROJ/PostGIS conflict and corrupted .sbn index"
- Everything described below as "done" is pushed to this exact commit. Nothing is sitting uncommitted anywhere.

A separate repo, `CODEBOTS01/FLOODSAFE`, was raised mid-session as a possible
new home for this work — see "Open blockers" below before assuming that's
where things continue.

## What happened this session, in order

1. **Scaffolded the whole Phase 1 pipeline** inside `flash_flood_system/`, a
   new top-level folder in this repo (chosen deliberately — the repo's
   existing content is an unrelated gym/class website; you approved adding
   this alongside it rather than replacing it or using a different repo).
2. **Re-read the scaffold adversarially** and fixed real bugs before any data
   ever touched it: exact-timestamp joins that would return ~0 rows against
   real multi-source data (switched to as-of `LATERAL` joins), a flood-label
   query that would have marked *every* timestamp for a once-flooded cell as
   positive instead of just the event window, `elevation_m` never actually
   being sampled from the DEM (would've silently dropped every ML row), no
   uniqueness anywhere so reruns duplicated data, `ward_id`/`watershed_id`
   never being assigned to grid cells, admin boundary parent FKs requiring
   manual mapping, and a `Polygon`→`MultiPolygon` conversion that was a no-op.
3. **Opened PR #2** and started monitoring it (a standing routine re-checks it
   hourly — CI/comments/mergeability — it has stayed clean and quiet the
   entire session; nothing has ever needed action there).
4. **Built `scripts/clip_to_pilot_area.py`** to shrink your ~9GB of full-extent
   HydroSHEDS/HydroBASINS/HydroRIVERS/Survey-of-India downloads down to just
   the 5 pilot districts (Uttarkashi, Chamoli, Rudraprayag, Bageshwar,
   Pithoragarh). Verified correctness on synthetic data first (bit-identical
   raster clipping, correct vector bbox filtering) before you ran it for real.
5. **You ran it against your real data** on your Windows machine and hit two
   real environment bugs, both now fixed and verified:
   - PostgreSQL/PostGIS's bundled `proj.db` was shadowing `pyproj`'s own,
     breaking every raster clip (`DATABASE.LAYOUT.VERSION.MINOR` error) — fixed
     by clearing `PROJ_LIB`/`PROJ_DATA` at the top of the script.
   - 4 of 12 HydroBASINS levels had corrupted `.sbn` spatial-index sidecar
     files, unrelated to the actual geometry — fixed with a full-read fallback.
   - **Final successful real-data run**: **9.7GB → 348.5MB**, 30/30 geospatial
     files clipped correctly. Of that 348.5MB, ~301MB is `landslide_report.pdf`
     (copied through untouched, not clippable) and only **~47MB is the actual
     clipped geodata** (DEM, flow direction, flow accumulation, HydroBASINS,
     HydroRIVERS, admin boundaries).
6. **Tried to get that 348.5MB into a session — this is the part that's still
   unresolved.** Three attempts, three different blockers:
   - Google Drive: **blocked at this session's network-policy level.**
     Confirmed via the proxy's own status endpoint — `drive.google.com` gets an
     explicit 403 policy denial on CONNECT. Not a bug, not retryable, not
     something a different approach routes around from inside this session.
   - Pushing to `CODEBOTS01/FLOODSAFE` directly from this session: blocked
     because this session's git access is pinned to one GitHub owner
     (`WaheedHaider`) — a second owner's repo can't be attached mid-session.
   - Spawning a **fresh** session pointed at `CODEBOTS01/FLOODSAFE`: also
     blocked — `github_repo_access_denied`. The Claude GitHub App has never
     been granted access to that repo/account at all (separate from the
     owner-tier issue above).
   - **Net result: the clipped data still only exists on your local machine**,
     at `C:\FFGS\pilot_clipped` (and `pilot_clipped.zip` next to it). It was
     never actually transferred into any Claude session.
7. Since then, the session has just been idling on the PR-monitoring routine
   waiting for direction — nothing new to report there.

## Open blockers you need to resolve before data work can continue

1. **Which repo.** Either:
   - (a) Keep using `WaheedHaider/Web-Design-Project` PR #2 — zero setup, works right now, or
   - (b) Fix `CODEBOTS01/FLOODSAFE` access first: go to **github.com/settings/installations**
     on the `CODEBOTS01` account, find the **Claude** app, and grant it access
     to that repo (or "All repositories"). Only then can a session attach it.
2. **How the data gets in.** Given the real clipped size is only **~47MB**
   (once you leave the 301MB PDF aside), the simplest fix is probably: **just
   commit it directly to the git branch** rather than hunting for another file
   host. 47MB is well within normal git comfort. Concretely, whichever repo
   you land on:
   ```powershell
   cd C:\FFGS\pilot_clipped
   git init                          # if starting fresh from this folder
   git add . -- ':!landslide_report.pdf'
   git commit -m "Add clipped Uttarakhand pilot data (5 districts)"
   git push ...
   ```
   (Do **not** try Google Drive again in a new session unless you've confirmed
   its network policy differs from this one — assume it's blocked the same way.)

## What's fully built and pushed (detailed)

**Database**
- `database/schema.sql` — full PostGIS DDL: admin hierarchy (state→district→tehsil→village→ward, nullable parent FKs resolved post-load), watersheds/rivers, `grid_cells` (with auto-centroid trigger), `terrain_features`, `rainfall`/`soil_moisture` (unique-indexed), `landslides`, `flood_events`/`flood_event_cells`, `iot_sensors`/`iot_observations`, `risk_predictions` (unique-indexed on cell+time+model_version), `ward_risk`, `alerts`. GIST indexes on every geometry column.
- `database/db_utils.py` — engine, schema runner, `upsert_dataframe` (INSERT...ON CONFLICT), `bulk_update` (staging-table UPDATE), GeoDataFrame I/O.

**Ingestion**
- `src/ingestion/admin_boundaries.py` — validates/reprojects/loads shapefiles; auto-resolves parent FKs via `ST_Within(ST_PointOnSurface(...))`.
- `src/ingestion/inspect_source.py` — CRS/columns/geometry-type dump for any shapefile or raster before ingesting.

**Spatial**
- `src/spatial/grid_generator.py` — 250m fishnet grid + 100m high-risk refinement.
- `src/spatial/load_grid_to_db.py` — loads generated grid into `grid_cells`, resolves refined-cell parent links.
- `src/spatial/assign_admin_watershed.py` — assigns `ward_id`/`village_id`/`watershed_id` via `ST_Within` on cell centroid.

**Terrain**
- `src/terrain/dem_processing.py` — DEM clip + reproject.
- `src/terrain/terrain_derivatives.py` — WhiteboxTools slope/aspect/flow direction/flow accumulation/TWI/distance-to-stream, plus elevation sampled directly from the DEM; `--write-db` loads straight into `terrain_features`.

**Hydrology**
- `src/hydrology/antecedent_wetness.py` — soil moisture + 72h rainfall → wetness index.
- `src/hydrology/ffg_engine.py` — dynamic rainfall threshold (drops as wetness/slope/TWI/stream-proximity rise) → `hydrological_threat`; writes to `risk_predictions` first in the pipeline (must run before `predict.py`).

**ML**
- `src/ml/feature_engineering.py` — training-table assembly with as-of joins and correctly time-windowed flood labels.
- `src/ml/train_model.py` — calibrated XGBoost (isotonic calibration, since alerting needs real probabilities not just ranking).
- `src/ml/predict.py` — scores current conditions, requires `ffg_engine.py`'s row to already exist (no silent zero-fallback), computes a confidence proxy from ML/hydrology agreement.

**Aggregation**
- `src/aggregation/ward_aggregation.py` — ward risk = weighted(avg, max, high-risk-area%, exposure) — deliberately not a plain average.

**Utility**
- `scripts/clip_to_pilot_area.py` — the pilot-area clipping tool described above; battle-tested against your real 9.7GB download.

**Docs**
- `README.md`, `docs/ARCHITECTURE.md` (design rationale + explicit scale/ML-quality recommendations), `docs/PROGRESS.md` (phase checklist, kept current), `docs/PHASE1_GUIDE.md` (exact command sequence for Phase 1), this file.

## What's NOT done — remaining work

*(Dashboard intentionally excluded from this list per your note — treated as handled outside this pipeline.)*

**Immediate — blocks everything else:**
- [ ] Get the ~47MB clipped dataset into whatever session continues this (see "Open blockers" above)
- [ ] Stand up a real PostgreSQL+PostGIS instance in that session's environment and run `python -m database.db_utils`
- [ ] Run Phase 1 for real, in order, per `docs/PHASE1_GUIDE.md`:
      `inspect_source.py` → `admin_boundaries.py` (state→district→tehsil→village→ward) → `grid_generator.py` + `load_grid_to_db.py` → `dem_processing.py` + `terrain_derivatives.py --write-db` → `assign_admin_watershed.py`

**Phase 2 — no code written yet:**
- [ ] Rainfall ingestion (GPM IMERG via `earthaccess`, or GSMaP/IMD)
- [ ] Soil moisture ingestion (ERA5-Land via `cdsapi`, or SMAP via `earthaccess`)
- [ ] IoT MQTT subscriber (ESP32 → broker → `iot_observations`)

**Phase 3:**
- [ ] Calibrate `ffg_engine.py`'s weights (currently illustrative placeholders in `config.yaml`) against real historical events once available

**Phase 4:**
- [ ] Obtain real historical flood/landslide records (CWC, GSI)
- [ ] If coverage is too thin to train on, build the synthetic-label fallback described in `docs/ARCHITECTURE.md` (hydrological_threat + GSI susceptibility zone → provisional label)
- [ ] Actually run `train_model.py` and validate it

**Phase 5:**
- [ ] Exposure layer — `ward_aggregation.py` currently defaults exposure to 0 everywhere; build the OSM-buildings/roads/schools proxy recommended in `docs/ARCHITECTURE.md`

**Phase 6:**
- [ ] Alert engine — schema (`alerts` table) and thresholds (`config.yaml`) exist; no code generates or sends an alert yet

**Phase 7:**
- [ ] Historical backtesting / false-alarm & missed-event validation — depends on everything above being real

## Architecture — unchanged, still the plan

Full rationale is in `docs/ARCHITECTURE.md`; short version: rainfall + soil
moisture + terrain + historical events + forecast + IoT → hydrological engine
(domain-based threshold) + ML engine (data-driven probability) → combined
per-cell risk on a 100–250m grid → aggregated to ward/village level
(avg+max+high-risk-area%+exposure, not a plain mean) → alerts. Grid and
administrative geometry are both kept (hydrology follows terrain, authorities
act on admin boundaries) via `grid_cells`' FKs to both.

Recommended scope adjustments already agreed and baked into the docs: build
against a pilot area (these 5 districts) before attempting statewide;
synthetic labels as a fallback for label scarcity; OSM as the Phase 1
exposure proxy; IoT can be simulated via MQTT for demo purposes before real
hardware exists.

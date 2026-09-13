"""
Clip full-extent source data (HydroSHEDS DEM / flow rasters, HydroBASINS,
HydroRIVERS, landslide inventories) down to the 5 pilot districts before
uploading.

Run this LOCALLY, on the machine holding the full-size downloads — it turns
~9GB into a few hundred MB with no loss of information inside the pilot area.

    python scripts/clip_to_pilot_area.py \
        --input-dir  /path/to/your/downloads \
        --output-dir ./pilot_clipped

HydroSHEDS/HydroBASINS/HydroRIVERS downloads usually arrive as .zip archives
(sometimes with the shapefile nested a folder or two deep) — these are
auto-extracted into output-dir/_extracted/ before scanning, so you don't need
to unzip anything by hand first.

Rasters are clipped with a windowed read (the full array is never loaded, so
a multi-GB DEM won't exhaust RAM) and rewritten with DEFLATE compression.
Vectors are filtered by bounding box against the file's spatial index and
written as GeoPackage, so each one uploads as a single file instead of the
.shp/.dbf/.shx/.prj sidecar set. Non-geospatial files (e.g. a landslide
report PDF) aren't clippable, so they're copied through to the output
folder unchanged rather than silently dropped.

WHY THE DEFAULT EXTENT IS GENEROUS
Flash-flood hydrology depends on upstream contributing area, which frequently
sits outside the district the flood actually hits. Clipping tight to district
polygons would silently discard that upstream terrain, so the default is a
rectangular envelope around all five districts plus a buffer.

For the same reason: use the flow-direction / flow-accumulation rasters you
already downloaded, whose values encode full upstream contribution. Do NOT
recompute flow accumulation from the *clipped* DEM — clipping truncates
upstream catchments and recomputed values would be wrong near the edges.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from shapely.geometry import box

# Approximate envelope covering Uttarkashi, Chamoli, Rudraprayag, Bageshwar
# and Pithoragarh (lon_min, lat_min, lon_max, lat_max) in EPSG:4326.
# Approximate on purpose — over-inclusion costs a little file size, while
# under-inclusion would silently cut off part of a district.
PILOT_DISTRICTS = ["Uttarkashi", "Chamoli", "Rudraprayag", "Bageshwar", "Pithoragarh"]
DEFAULT_BBOX = (77.7, 29.3, 81.2, 31.6)

RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".bil", ".asc"}
VECTOR_SUFFIXES = {".shp", ".gpkg", ".geojson", ".json", ".gml", ".kml"}


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}PB"


def clip_raster(src_path: Path, dst_path: Path, bbox_4326: tuple[float, float, float, float]) -> bool:
    with rasterio.open(src_path) as src:
        if src.crs is None:
            print(f"  SKIP (no CRS defined): {src_path.name}")
            return False

        # The bbox is lat/lon; the raster may be projected. Convert before windowing.
        if src.crs.to_epsg() != 4326:
            bounds = transform_bounds("EPSG:4326", src.crs, *bbox_4326, densify_pts=21)
        else:
            bounds = bbox_4326

        window = from_bounds(*bounds, transform=src.transform)
        window = window.round_offsets().round_lengths()
        full = Window(0, 0, src.width, src.height)
        try:
            window = window.intersection(full)
        except rasterio.errors.WindowError:
            print(f"  SKIP (no overlap with pilot area): {src_path.name}")
            return False

        if window.width <= 0 or window.height <= 0:
            print(f"  SKIP (no overlap with pilot area): {src_path.name}")
            return False

        profile = src.profile.copy()
        profile.update(
            width=int(window.width),
            height=int(window.height),
            transform=src.window_transform(window),
            compress="deflate",
            # predictor 3 for floating point, 2 for integer — both lossless
            predictor=3 if src.profile["dtype"].startswith("float") else 2,
            tiled=True,
            blockxsize=512,
            blockysize=512,
        )

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst_path, "w", **profile) as dst:
            # Copy band by band, one windowed read each — never the full array.
            for band in range(1, src.count + 1):
                dst.write(src.read(band, window=window), band)

    return True


def clip_vector(src_path: Path, dst_path: Path, bbox_4326: tuple[float, float, float, float]) -> bool:
    # Pass the bbox as a GeoSeries with an explicit CRS so GeoPandas reprojects
    # it into the file's own CRS rather than assuming they already match.
    bbox_geom = gpd.GeoSeries([box(*bbox_4326)], crs="EPSG:4326")

    try:
        gdf = gpd.read_file(src_path, bbox=bbox_geom)
    except Exception as exc:
        print(f"  SKIP (unreadable: {exc}): {src_path.name}")
        return False

    if gdf.empty:
        print(f"  SKIP (no features in pilot area): {src_path.name}")
        return False

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(dst_path, driver="GPKG")
    print(f"    kept {len(gdf)} features")
    return True


def extract_zips(input_dir: Path, extract_root: Path) -> list[Path]:
    """
    HydroSHEDS/HydroBASINS/HydroRIVERS downloads are typically delivered as
    zips, often with the shapefile nested inside its own subfolder. Extracts
    each zip found under input_dir into extract_root/<zip stem>/, skipping
    ones already extracted (safe to re-run). Returns the extraction dirs.
    Never writes into input_dir itself, so the original download folder
    (which may be an OneDrive-synced path) is never modified.
    """
    extracted_dirs = []
    for zip_path in sorted(input_dir.rglob("*.zip")):
        # Spaces in "flow acc.zip" etc. are fine — Path handles them as-is.
        target = extract_root / zip_path.stem
        if target.exists() and any(target.iterdir()):
            print(f"[{zip_path.relative_to(input_dir)}]  already extracted -> {target}")
            extracted_dirs.append(target)
            continue

        target.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(target)
            print(f"[{zip_path.relative_to(input_dir)}]  extracted -> {target}")
            extracted_dirs.append(target)
        except zipfile.BadZipFile:
            print(f"[{zip_path.relative_to(input_dir)}]  SKIP (not a valid zip file)")

    return extracted_dirs


def collect_inputs(search_dir: Path) -> list[Path]:
    files = []
    for path in sorted(search_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in RASTER_SUFFIXES or suffix in VECTOR_SUFFIXES:
            files.append(path)
    return files


def collect_passthrough_files(input_dir: Path) -> list[Path]:
    """
    Non-geospatial files sitting directly in input_dir (e.g. a landslide
    inventory PDF/report, a readme) that clip_raster/clip_vector can't
    process but shouldn't silently vanish from the upload either — these get
    copied through to the output folder unchanged.
    """
    skip_suffixes = RASTER_SUFFIXES | VECTOR_SUFFIXES | {".zip"}
    return [
        p for p in sorted(input_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() not in skip_suffixes
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input-dir", required=True, help="Folder holding the full-size downloads")
    parser.add_argument("--output-dir", required=True, help="Where clipped copies are written")
    parser.add_argument(
        "--bbox", nargs=4, type=float, metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"),
        help=f"Override the default pilot extent {DEFAULT_BBOX}",
    )
    parser.add_argument(
        "--boundary",
        help="Use this vector file's extent instead of --bbox (e.g. a real district shapefile)",
    )
    parser.add_argument(
        "--buffer-deg", type=float, default=0.1,
        help="Degrees of padding added to the extent (default 0.1 ~ 11km) to retain upstream terrain",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be clipped without writing clipped output. Zips still get "
             "extracted (into output-dir/_extracted/) so their contents can be listed — "
             "re-run without --dry-run afterward and the extraction is reused, not redone.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not input_dir.is_dir():
        print(f"ERROR: --input-dir not found: {input_dir}")
        return 1

    if args.boundary:
        boundary = gpd.read_file(args.boundary).to_crs("EPSG:4326")
        bbox = tuple(boundary.total_bounds)
        source = f"extent of {args.boundary}"
    elif args.bbox:
        bbox = tuple(args.bbox)
        source = "--bbox"
    else:
        bbox = DEFAULT_BBOX
        source = f"default envelope of {', '.join(PILOT_DISTRICTS)}"

    b = args.buffer_deg
    bbox = (bbox[0] - b, bbox[1] - b, bbox[2] + b, bbox[3] + b)

    # Zips are extracted into output_dir/_extracted/<zip stem>/ — never into
    # input_dir itself, so a source folder synced by OneDrive/Drive is never
    # written to by this script.
    extract_root = output_dir / "_extracted"
    print("--- Extracting archives ---")
    extracted_dirs = extract_zips(input_dir, extract_root)
    if not extracted_dirs:
        print("(no .zip files found)")
    print()

    # (source_path, output-relative-path) pairs. Files already sitting loose
    # in input_dir keep their path relative to it; files that came out of a
    # zip are namespaced under that zip's name so e.g. every HydroRIVERS
    # shapefile doesn't collide with every HydroBASINS one on disk.
    file_pairs: list[tuple[Path, Path]] = []
    for f in collect_inputs(input_dir):
        file_pairs.append((f, f.relative_to(input_dir)))
    for extracted_dir in extracted_dirs:
        for f in collect_inputs(extracted_dir):
            file_pairs.append((f, Path(extracted_dir.name) / f.relative_to(extracted_dir)))

    passthrough = collect_passthrough_files(input_dir)

    total_in = sum(f.stat().st_size for f, _ in file_pairs) + sum(f.stat().st_size for f in passthrough)

    print(f"Pilot extent : {tuple(round(v, 3) for v in bbox)}  ({source}, +{b}° buffer)")
    print(f"Input        : {input_dir}")
    print(f"Found        : {len(file_pairs)} geospatial files + {len(passthrough)} other files, {human_size(total_in)}")
    print(f"Output       : {output_dir}\n")

    if passthrough:
        print("Files that aren't clippable geospatial data (will be copied through as-is):")
        for f in passthrough:
            print(f"  {f.relative_to(input_dir)}  ({human_size(f.stat().st_size)})")
        print()

    if args.dry_run:
        for src, rel in file_pairs:
            print(f"  would clip {rel}  ({human_size(src.stat().st_size)})")
        return 0

    written = 0
    for src, rel in file_pairs:
        print(f"[{rel}]  {human_size(src.stat().st_size)}")
        try:
            if src.suffix.lower() in RASTER_SUFFIXES:
                ok = clip_raster(src, output_dir / rel, bbox)
            else:
                ok = clip_vector(src, (output_dir / rel).with_suffix(".gpkg"), bbox)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            continue

        if ok:
            written += 1
            out = output_dir / rel
            out = out if out.exists() else out.with_suffix(".gpkg")
            if out.exists():
                print(f"  -> {human_size(out.stat().st_size)}")

    if passthrough:
        print("\n--- Copying non-geospatial files through unchanged ---")
        for src in passthrough:
            rel = src.relative_to(input_dir)
            dst = output_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  copied {rel}")

    # _extracted/ holds the raw unzipped originals, not deliverables — clean
    # it up so it isn't counted or uploaded alongside the actual clipped output.
    if extract_root.exists():
        shutil.rmtree(extract_root)

    total_out = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file())
    print(f"\nClipped {written}/{len(file_pairs)} geospatial files, copied {len(passthrough)} other file(s)")
    print(f"{human_size(total_in)} -> {human_size(total_out)}")
    if total_in and total_out:
        print(f"Reduction: {100 * (1 - total_out / total_in):.1f}%")
    print(f"\nUpload this folder: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

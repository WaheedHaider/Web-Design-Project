"""
Phase 1: clip and reproject the conditioned HydroSHEDS DEM to the study area
before terrain derivatives are computed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import rasterio
from rasterio.mask import mask
from rasterio.warp import Resampling, calculate_default_transform, reproject
import geopandas as gpd

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from config.settings import PROJECTED_CRS


def clip_dem_to_boundary(dem_path: str, boundary: gpd.GeoDataFrame, output_path: str) -> str:
    """Clips a (conditioned) DEM raster to the study-area boundary geometry."""
    with rasterio.open(dem_path) as src:
        boundary_same_crs = boundary.to_crs(src.crs)
        geoms = [geom.__geo_interface__ for geom in boundary_same_crs.geometry]

        out_image, out_transform = mask(src, geoms, crop=True)
        out_meta = src.meta.copy()
        out_meta.update(
            {
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform,
            }
        )

    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(out_image)

    return output_path


def reproject_dem(dem_path: str, output_path: str, dst_crs: str = PROJECTED_CRS) -> str:
    """Reprojects the DEM into the metric CRS used for slope/flow calculations."""
    with rasterio.open(dem_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        meta = src.meta.copy()
        meta.update({"crs": dst_crs, "transform": transform, "width": width, "height": height})

        with rasterio.open(output_path, "w", **meta) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                )

    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", required=True, help="Path to the raw conditioned DEM (GeoTIFF)")
    parser.add_argument("--boundary", required=True, help="Path to the study-area boundary vector file")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    boundary_gdf = gpd.read_file(args.boundary)
    clipped = clip_dem_to_boundary(args.dem, boundary_gdf, str(out_dir / "dem_clipped.tif"))
    reprojected = reproject_dem(clipped, str(out_dir / "dem_projected.tif"))
    print(f"DEM ready for terrain derivatives: {reprojected}")

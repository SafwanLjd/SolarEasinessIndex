"""
Script 03: Sample PVOUT raster at segment centroids
Input:  data/processed/segments_200m.geojson
        data/raw/solar/PVOUT.tif
Output: data/processed/pvout.csv
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

RAW       = Path("data/raw")
PROCESSED = Path("data/processed")


def main():
    # --- load segments ---
    segments = gpd.read_file(PROCESSED / "segments_200m.geojson")
    if segments.crs.to_epsg() != 25832:
        segments = segments.to_crs(25832)
    assert segments.crs.to_epsg() == 25832, f"CRS wrong: {segments.crs}"

    df = segments[["segment_id", "centroid_lon", "centroid_lat"]].copy()

    # --- sample raster ---
    tif_path = RAW / "solar" / "PVOUT.tif"
    with rasterio.open(tif_path) as src:
        log.info(f"Raster CRS: {src.crs}  |  Shape: {src.shape}  |  nodata: {src.nodata}")

        coords = list(zip(df["centroid_lon"], df["centroid_lat"]))
        sampled = list(src.sample(coords))
        nodata = src.nodata

    values = []
    for s in sampled:
        v = s[0]
        if nodata is not None and v == nodata:
            values.append(float("nan"))
        else:
            values.append(float(v))

    df["pvout_annual"] = values

    # --- validate ---
    nan_count = df["pvout_annual"].isna().sum()
    vmin = df["pvout_annual"].min()
    vmax = df["pvout_annual"].max()
    vmean = df["pvout_annual"].mean()

    log.info(f"PVOUT range for corridor: {vmin:.1f} - {vmax:.1f}")
    log.info(f"PVOUT mean: {vmean:.1f}")
    log.info(f"NaN count: {nan_count}")

    if vmax < 10:
        log.error("WRONG FILE: values suggest daily totals not yearly. Check file path.")
        sys.exit(1)

    # --- save ---
    output_path = PROCESSED / "pvout.csv"
    df[["segment_id", "pvout_annual"]].to_csv(output_path, index=False)

    log.info(f"Rows processed: {len(df)}")
    log.info(f"Missing values:\n{df[['pvout_annual']].isnull().sum()}")
    log.info(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()

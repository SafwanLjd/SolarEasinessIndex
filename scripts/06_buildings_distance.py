"""
Script 06: Distance from each segment centroid to nearest building (LV grid proxy)
Input:  data/processed/segments_200m.geojson
        data/processed/buildings.geojson
Output: data/processed/buildings_distance.csv
"""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

PROCESSED = Path("data/processed")


def main():
    # --- load segments ---
    segments = gpd.read_file(PROCESSED / "segments_200m.geojson")
    if segments.crs.to_epsg() != 25832:
        segments = segments.to_crs(25832)
    assert segments.crs.to_epsg() == 25832, f"CRS wrong: {segments.crs}"

    # Build centroid point GeoDataFrame from WGS84 lon/lat
    centroids = segments[["segment_id", "centroid_lon", "centroid_lat"]].copy()
    centroids["geometry"] = centroids.apply(
        lambda r: Point(r["centroid_lon"], r["centroid_lat"]), axis=1
    )
    centroids = gpd.GeoDataFrame(centroids, geometry="geometry", crs="EPSG:4326")
    centroids = centroids.to_crs(25832)
    assert centroids.crs.to_epsg() == 25832, f"CRS wrong: {centroids.crs}"

    # --- load buildings ---
    buildings = gpd.read_file(PROCESSED / "buildings.geojson")
    if buildings.crs.to_epsg() != 25832:
        buildings = buildings.to_crs(25832)
    assert buildings.crs.to_epsg() == 25832, f"CRS wrong: {buildings.crs}"
    log.info(f"Buildings loaded: {len(buildings)}")

    # --- nearest join ---
    result = gpd.sjoin_nearest(
        centroids[["segment_id", "geometry"]],
        buildings[["building_id", "geometry"]],
        how="left",
        distance_col="building_dist_m",
    )

    result = result.drop_duplicates(subset="segment_id", keep="first")
    df = result[["segment_id", "building_dist_m"]].copy()
    df["building_dist_m"] = df["building_dist_m"].round(2)

    # --- save ---
    output_path = PROCESSED / "buildings_distance.csv"
    df.to_csv(output_path, index=False)

    # --- validate ---
    log.info(
        f"building_dist_m - min: {df['building_dist_m'].min():.1f}, "
        f"max: {df['building_dist_m'].max():.1f}, "
        f"mean: {df['building_dist_m'].mean():.1f}"
    )

    remote = df[df["building_dist_m"] > 500]
    if len(remote) > 0:
        log.warning(f"Remote segments (>500m from building): {list(remote['segment_id'])}")
    else:
        log.info("No remote segments (all within 500m of a building)")

    log.info(f"Rows processed: {len(df)}")
    log.info(f"Missing values:\n{df.isnull().sum()}")
    log.info(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()

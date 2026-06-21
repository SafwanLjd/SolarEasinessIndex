"""
Script 05: Compute deflection angle, station proximity, and crossing count
Input:  data/processed/segments_200m.geojson
        data/processed/stations.geojson
        data/processed/crossings.geojson
Output: data/processed/geometry_attrs.csv
"""

import logging
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

PROCESSED = Path("data/processed")


def bearing(x1, y1, x2, y2):
    """Bearing from (x1,y1) to (x2,y2) in EPSG:25832 easting/northing."""
    return math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360


def angular_diff(a, b):
    """Absolute angular difference normalised to 0-180 degrees."""
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def main():
    # --- load segments ---
    segments = gpd.read_file(PROCESSED / "segments_200m.geojson")
    if segments.crs.to_epsg() != 25832:
        segments = segments.to_crs(25832)
    assert segments.crs.to_epsg() == 25832, f"CRS wrong: {segments.crs}"

    # --- deflection angle ---
    deflections = []
    for _, row in segments.iterrows():
        line = row.geometry
        start = line.interpolate(0, normalized=True)
        mid = line.interpolate(0.5, normalized=True)
        end = line.interpolate(1, normalized=True)

        b1 = bearing(start.x, start.y, mid.x, mid.y)
        b2 = bearing(mid.x, mid.y, end.x, end.y)
        deflections.append(round(angular_diff(b1, b2), 2))

    segments["deflection_deg"] = deflections
    segments["is_curved"] = segments["deflection_deg"] > 3.0

    # --- station proximity ---
    stations = gpd.read_file(PROCESSED / "stations.geojson")
    if stations.crs.to_epsg() != 25832:
        stations = stations.to_crs(25832)
    assert stations.crs.to_epsg() == 25832, f"CRS wrong: {stations.crs}"

    buffered = segments[["segment_id", "geometry"]].copy()
    buffered["geometry"] = buffered.geometry.buffer(50)

    joined = gpd.sjoin(buffered, stations[["geometry"]], how="left", predicate="intersects")
    near_ids = set(joined.dropna(subset=["index_right"])["segment_id"])
    segments["near_station"] = segments["segment_id"].isin(near_ids)

    # --- level crossings per segment ---
    crossings_path = PROCESSED / "crossings.geojson"
    if crossings_path.exists():
        crossings = gpd.read_file(crossings_path)
        if crossings.crs.to_epsg() != 25832:
            crossings = crossings.to_crs(25832)
        assert crossings.crs.to_epsg() == 25832, f"CRS wrong: {crossings.crs}"

        # Buffer segments by 15m and count crossings within each
        seg_buf = segments[["segment_id", "geometry"]].copy()
        seg_buf["geometry"] = seg_buf.geometry.buffer(15)
        joined_c = gpd.sjoin(
            crossings[["geometry"]], seg_buf, how="inner", predicate="within"
        )
        counts = joined_c.groupby("segment_id").size().reset_index(name="crossing_count")
        segments = segments.merge(counts, on="segment_id", how="left")
        segments["crossing_count"] = segments["crossing_count"].fillna(0).astype(int)
        log.info(f"Level crossings loaded: {len(crossings)}")
    else:
        log.warning("crossings.geojson not found - setting crossing_count = 0")
        segments["crossing_count"] = 0

    # --- save ---
    df = segments[["segment_id", "deflection_deg", "is_curved", "near_station", "crossing_count"]].copy()
    output_path = PROCESSED / "geometry_attrs.csv"
    df.to_csv(output_path, index=False)

    # --- validate ---
    curved_count = df["is_curved"].sum()
    curved_pct = curved_count / len(df) * 100
    station_count = df["near_station"].sum()
    station_segs = list(df.loc[df["near_station"], "segment_id"])
    crossing_segs = df[df["crossing_count"] > 0]

    log.info(f"Curved segments (>3°): {curved_count} ({curved_pct:.1f}%)")
    log.info(f"Near-station segments: {station_count}")
    log.info(f"Near-station segment_ids: {station_segs}")
    log.info(f"Segments with crossings: {len(crossing_segs)} (max {df['crossing_count'].max()} per segment)")
    log.info(f"Rows processed: {len(df)}")
    log.info(f"Missing values:\n{df.isnull().sum()}")
    log.info(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()

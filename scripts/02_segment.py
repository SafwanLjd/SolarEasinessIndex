"""
Script 02: Segment railway line into 200m pieces
Input:  data/processed/strohgaeu_line.geojson
Output: data/processed/segments_200m.geojson
"""

import logging
import math
from pathlib import Path

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import LineString, Point

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

PROCESSED = Path("data/processed")
SEGMENT_LENGTH = 200  # metres


def main():
    # --- load ---
    gdf = gpd.read_file(PROCESSED / "strohgaeu_line.geojson")
    if gdf.crs.to_epsg() != 25832:
        gdf = gdf.to_crs(25832)
    assert gdf.crs.to_epsg() == 25832, f"CRS wrong: {gdf.crs}"

    line = gdf.geometry.iloc[0]
    total_length = line.length
    log.info(f"Line length: {total_length:.1f} m")

    # --- interpolate cut points ---
    distances = list(range(0, int(total_length), SEGMENT_LENGTH))
    if distances[-1] < total_length:
        distances.append(total_length)

    cut_points = [line.interpolate(d) for d in distances]

    # --- build segments ---
    transformer = Transformer.from_crs(25832, 4326, always_xy=True)

    rows = []
    for i in range(len(cut_points) - 1):
        p_start = cut_points[i]
        p_end = cut_points[i + 1]

        # Sub-LineString between the two interpolated points
        start_d = distances[i]
        end_d = distances[i + 1]

        # Extract the portion of the original line between start_d and end_d
        coords = []
        coords.append((p_start.x, p_start.y))

        # Add original vertices that fall between start_d and end_d
        for coord in line.coords:
            pt = Point(coord)
            d = line.project(pt)
            if start_d < d < end_d:
                coords.append(coord)

        coords.append((p_end.x, p_end.y))
        segment = LineString(coords)

        # Segment attributes
        seg_id = f"STR_{i + 1:03d}"
        seg_length = segment.length

        # Centroid in EPSG:4326
        centroid = segment.centroid
        clon, clat = transformer.transform(centroid.x, centroid.y)

        # Azimuth: bearing from start to end in EPSG:25832
        dx = p_end.x - p_start.x
        dy = p_end.y - p_start.y
        azimuth = math.degrees(math.atan2(dx, dy)) % 360

        rows.append({
            "segment_id": seg_id,
            "start_chainage_m": start_d,
            "end_chainage_m": end_d,
            "segment_length_m": round(seg_length, 2),
            "centroid_lon": round(clon, 6),
            "centroid_lat": round(clat, 6),
            "azimuth_deg": round(azimuth, 2),
            "geometry": segment,
        })

    segments = gpd.GeoDataFrame(rows, crs="EPSG:25832")
    assert segments.crs.to_epsg() == 25832, f"CRS wrong: {segments.crs}"

    # --- drop stub segments shorter than 50m ---
    MIN_LENGTH = 50  # metres
    short = segments[segments["segment_length_m"] < MIN_LENGTH]
    if len(short) > 0:
        log.info(
            f"Dropping {len(short)} stub segment(s) shorter than {MIN_LENGTH}m: "
            f"{list(short['segment_id'])} (lengths: {list(short['segment_length_m'])})"
        )
        segments = segments[segments["segment_length_m"] >= MIN_LENGTH].reset_index(drop=True)

    # --- save ---
    output_path = PROCESSED / "segments_200m.geojson"
    segments.to_file(output_path, driver="GeoJSON")

    # --- validate ---
    total_seg_length = segments["segment_length_m"].sum()
    log.info(f"Rows processed: {len(segments)}")
    log.info(f"Total segment length sum: {total_seg_length:.1f} m")
    log.info(f"First: {segments['segment_id'].iloc[0]}  Last: {segments['segment_id'].iloc[-1]}")
    log.info(
        f"centroid_lat range: {segments['centroid_lat'].min():.4f} - "
        f"{segments['centroid_lat'].max():.4f}"
    )
    log.info(f"Missing values:\n{segments.isnull().sum()}")
    log.info(f"CRS: {segments.crs}  |  Bounds: {segments.total_bounds}")
    log.info(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()

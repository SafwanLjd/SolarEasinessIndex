"""
Script 08: Flag segments that intersect Landschaftsschutzgebiet (LSG)
Input:  data/processed/segments_200m.geojson
        data/raw/exclusions/Landschaftsschutzgebiet (LSG).shp
Output: data/processed/exclusion_flags.csv

Note: LSG is a less restrictive protection category than Natura 2000 - it does not
automatically prohibit PV installation. Treated here as a conservative flag;
excluded=True sets sei_score=0, but requires case-by-case planning review.
"""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

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

    # Buffer each segment by 50m
    segments["geom_buf"] = segments.geometry.buffer(50)

    # --- load LSG, clipped to corridor bbox + 1000m ---
    bbox = segments.total_bounds  # (minx, miny, maxx, maxy)
    margin = 1000
    lsg = gpd.read_file(
        RAW / "exclusions" / "Landschaftsschutzgebiet (LSG).shp",
        bbox=(bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin),
    )
    if lsg.crs.to_epsg() != 25832:
        lsg = lsg.to_crs(25832)
    assert lsg.crs.to_epsg() == 25832, f"CRS wrong: {lsg.crs}"
    log.info(f"LSG polygons loaded (clipped): {len(lsg)}")

    # --- spatial join ---
    joined = gpd.sjoin(
        segments.set_geometry("geom_buf")[["segment_id", "geom_buf"]],
        lsg[["geometry"]],
        how="left",
        predicate="intersects",
    )

    flagged_ids = set(joined.dropna(subset=["index_right"])["segment_id"])

    df = pd.DataFrame({"segment_id": segments["segment_id"]})
    df["in_lsg"] = df["segment_id"].isin(flagged_ids)
    df["excluded"] = df["in_lsg"]

    # --- save ---
    output_path = PROCESSED / "exclusion_flags.csv"
    df.to_csv(output_path, index=False)

    # --- validate ---
    excluded_count = df["excluded"].sum()
    excluded_ids = list(df.loc[df["excluded"], "segment_id"])
    log.info(f"Excluded segments: {excluded_count}")
    log.info(f"Excluded segment_ids: {excluded_ids}")

    if excluded_count == 0:
        log.warning("No segments flagged as LSG - check spatial join and file path")

    log.info(f"Rows processed: {len(df)}")
    log.info(f"Missing values:\n{df.isnull().sum()}")
    log.info(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()

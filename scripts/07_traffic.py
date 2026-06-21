"""
Script 07: Assign train frequency to all segments (uniform, from timetable PDF)
Input:  data/processed/segments_200m.geojson
        data/raw/timetable/train_counts.json (parsed from PDF)
Output: data/processed/traffic.csv

Train counts were manually parsed from the RB47 timetable PDF into
data/raw/timetable/train_counts.json. This script reads that JSON
so the values are traceable and auditable without editing source code.
"""

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

RAW       = Path("data/raw")
PROCESSED = Path("data/processed")


def main():
    # --- load train counts ---
    counts_path = RAW / "timetable" / "train_counts.json"
    with open(counts_path) as f:
        counts = json.load(f)

    weekday = counts["counts"]["weekday"]["total_both_directions"]
    sunday  = counts["counts"]["sunday_holiday"]["total_both_directions"]
    saturday = counts["counts"]["saturday"]["total_both_directions"]

    log.info(f"Source: {counts['source']} (valid from {counts['valid_from']})")
    log.info(f"Weekday: {weekday}, Saturday: {saturday}, Sunday/holiday: {sunday}")

    assert weekday > 0, "Weekday train count is 0 - check train_counts.json"

    # --- load segments ---
    segments = gpd.read_file(PROCESSED / "segments_200m.geojson")
    if segments.crs.to_epsg() != 25832:
        segments = segments.to_crs(25832)
    assert segments.crs.to_epsg() == 25832, f"CRS wrong: {segments.crs}"

    df = pd.DataFrame({
        "segment_id": segments["segment_id"],
        "trains_per_day": weekday,
        "trains_per_saturday": saturday,
        "trains_per_sunday": sunday,
    })

    # --- save ---
    output_path = PROCESSED / "traffic.csv"
    df.to_csv(output_path, index=False)

    # --- validate ---
    log.info(f"Rows processed: {len(df)}")
    log.info(f"Missing values:\n{df.isnull().sum()}")
    log.info(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()

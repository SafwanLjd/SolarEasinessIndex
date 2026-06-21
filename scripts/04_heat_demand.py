"""
Script 04: Assign heat demand from waermebedarf building blocks to segments
Input:  data/processed/segments_200m.geojson
        data/raw/heat_demand/waermebedarf_baubloecke.shp
Output: data/processed/heat_demand.csv

Heat demand is computed as the mean qoutg_p_m2 (total useful heat output
per m^2 of building block area, kWh/a/m^2) across all building blocks
within 500 m of each segment. The 500 m buffer represents the typical
reach of a low-voltage distribution network and gives ~93% segment coverage.
Segments with no building blocks within 500 m receive 0.0 (genuinely rural).
"""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

RAW       = Path("data/raw")
PROCESSED = Path("data/processed")

BUFFER_M = 500  # metres around each segment


def main():
    # --- load segments ---
    segments = gpd.read_file(PROCESSED / "segments_200m.geojson")
    if segments.crs.to_epsg() != 25832:
        segments = segments.to_crs(25832)
    assert segments.crs.to_epsg() == 25832, f"CRS wrong: {segments.crs}"

    # --- load waermebedarf, clipped to corridor bbox + buffer ---
    bbox = segments.total_bounds
    margin = BUFFER_M + 100
    baubloecke = gpd.read_file(
        RAW / "heat_demand" / "waermebedarf_baubloecke.shp",
        bbox=(bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin),
    )
    if baubloecke.crs.to_epsg() != 25832:
        baubloecke = baubloecke.to_crs(25832)
    assert baubloecke.crs.to_epsg() == 25832, f"CRS wrong: {baubloecke.crs}"
    log.info(f"Building blocks loaded (clipped): {len(baubloecke)}")

    # --- buffer segments and spatial join ---
    # Buffer the segment geometry (not just the centroid) so we capture
    # building blocks alongside the track, not only directly underneath.
    seg_buf = segments[["segment_id", "geometry"]].copy()
    seg_buf["geometry"] = seg_buf.geometry.buffer(BUFFER_M)

    joined = gpd.sjoin(
        baubloecke[["qoutg_p_m2", "geometry"]],
        seg_buf,
        how="inner",
        predicate="intersects",
    )

    # Mean heat demand across all blocks intersecting each segment buffer
    agg = joined.groupby("segment_id")["qoutg_p_m2"].mean().reset_index()
    agg = agg.rename(columns={"qoutg_p_m2": "heat_demand_p_m2"})

    df = segments[["segment_id"]].merge(agg, on="segment_id", how="left")

    # --- handle NaN (genuinely rural, no blocks within buffer) ---
    nan_count = df["heat_demand_p_m2"].isna().sum()
    if nan_count > 0:
        nan_ids = list(df.loc[df["heat_demand_p_m2"].isna(), "segment_id"])
        log.info(
            f"{nan_count} segments have no building blocks within {BUFFER_M}m "
            f"(rural/open land) - setting heat_demand_p_m2 = 0.0: {nan_ids}"
        )
        df["heat_demand_p_m2"] = df["heat_demand_p_m2"].fillna(0.0)

    coverage = (df["heat_demand_p_m2"] > 0).sum()
    log.info(f"Coverage: {coverage}/{len(df)} segments ({coverage/len(df)*100:.0f}%) "
             f"have heat demand within {BUFFER_M}m buffer")

    # --- save ---
    output_path = PROCESSED / "heat_demand.csv"
    df.to_csv(output_path, index=False)

    # --- validate ---
    log.info(f"heat_demand_p_m2 - min: {df['heat_demand_p_m2'].min():.2f}, "
             f"max: {df['heat_demand_p_m2'].max():.2f}, "
             f"mean: {df['heat_demand_p_m2'].mean():.2f}")

    top3 = df.nlargest(3, "heat_demand_p_m2")
    log.info(f"Top-3 heat demand segments: {list(top3['segment_id'])}")

    log.info(f"Rows processed: {len(df)}")
    log.info(f"Missing values:\n{df.isnull().sum()}")
    log.info(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()

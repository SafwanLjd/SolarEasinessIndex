"""
Script 09: Merge all attribute CSVs, normalise, compute entropy weights and SEI score
Input:  data/processed/segments_200m.geojson
        data/processed/pvout.csv
        data/processed/heat_demand.csv
        data/processed/geometry_attrs.csv
        data/processed/buildings_distance.csv
        data/processed/traffic.csv
        data/processed/exclusion_flags.csv
Output: data/processed/segments_final.geojson
        outputs/tables/segments_ranked.csv
"""

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

PROCESSED = Path("data/processed")
OUTPUTS   = Path("outputs")


# ---------------------------------------------------------------------------
# Normalisation and entropy weights
# ---------------------------------------------------------------------------

def minmax_norm(series: pd.Series, invert: bool = False) -> pd.Series:
    srange = series.max() - series.min()
    if srange == 0:
        return pd.Series(1.0, index=series.index)
    normed = (series - series.min()) / srange
    return (1 - normed) if invert else normed


def entropy_weights(df_norm: pd.DataFrame) -> dict:
    n = len(df_norm)
    epsilon = 1e-10
    p = df_norm.div(df_norm.sum(axis=0), axis=1)
    H = -(p * np.log(p + epsilon)).sum(axis=0) / np.log(n)
    d = 1 - H
    return (d / d.sum()).to_dict()


# ---------------------------------------------------------------------------
# Missing data substitution
# ---------------------------------------------------------------------------

def fill_corridor_mean(df: pd.DataFrame, col: str) -> pd.DataFrame:
    missing = df[col].isna()
    count = missing.sum()
    if count > 0:
        mean_val = df[col].mean()
        ids = list(df.loc[missing, "segment_id"])
        log.info(f"{col}: substituting corridor mean ({mean_val:.2f}) for {count} segments: {ids}")
        df[col] = df[col].fillna(mean_val)
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # --- load segments ---
    gdf = gpd.read_file(PROCESSED / "segments_200m.geojson")
    if gdf.crs.to_epsg() != 25832:
        gdf = gdf.to_crs(25832)
    assert gdf.crs.to_epsg() == 25832, f"CRS wrong: {gdf.crs}"

    # --- left-join all CSVs ---
    pvout      = pd.read_csv(PROCESSED / "pvout.csv")
    heat       = pd.read_csv(PROCESSED / "heat_demand.csv")
    geom_attrs = pd.read_csv(PROCESSED / "geometry_attrs.csv")
    buildings  = pd.read_csv(PROCESSED / "buildings_distance.csv")
    traffic    = pd.read_csv(PROCESSED / "traffic.csv")
    exclusions = pd.read_csv(PROCESSED / "exclusion_flags.csv")

    for csv_df, name in [
        (pvout, "pvout"), (heat, "heat_demand"), (geom_attrs, "geometry_attrs"),
        (buildings, "buildings_distance"), (traffic, "traffic"), (exclusions, "exclusion_flags"),
    ]:
        gdf = gdf.merge(csv_df, on="segment_id", how="left")
        log.info(f"Merged {name}: {len(csv_df)} rows")

    # --- missing data policy ---
    # heat_demand_p_m2: rural segments already set to 0.0 in script 04
    # (no building block coverage = zero local heat demand).
    gdf = fill_corridor_mean(gdf, "pvout_annual")
    gdf = fill_corridor_mean(gdf, "building_dist_m")
    gdf = fill_corridor_mean(gdf, "deflection_deg")
    assert gdf["heat_demand_p_m2"].notna().all(), "heat_demand_p_m2 has unexpected nulls"

    assert gdf["trains_per_day"].notna().all(), "trains_per_day has unexpected nulls"

    # --- normalise ---
    # Continuous factors: entropy-weighted to form the base suitability score.
    # Binary/categorical constraints: applied as penalties or exclusions.
    #
    # This two-layer architecture separates "how suitable is the terrain?"
    # (continuous entropy-weighted score) from "are there physical obstructions?"
    # (crossing penalty) and "is the site permittable?" (LSG exclusion).
    # Mixing binary and continuous variables in entropy weighting causes the
    # binary variable to dominate (~58%) due to its concentrated distribution
    # - a known property of Shannon entropy, not a reflection of engineering
    # importance (Malczewski & Rinner 2015).
    gdf["pvout_norm"]    = minmax_norm(gdf["pvout_annual"],      invert=False)
    gdf["heat_norm"]     = minmax_norm(gdf["heat_demand_p_m2"],  invert=False)
    gdf["building_norm"] = minmax_norm(gdf["building_dist_m"],   invert=True)
    gdf["traffic_norm"]  = minmax_norm(gdf["trains_per_day"],    invert=True)
    gdf["curve_norm"]    = minmax_norm(gdf["deflection_deg"],    invert=True)
    gdf["crossing_norm"] = minmax_norm(gdf["crossing_count"],    invert=True)

    # --- entropy weights (continuous factors only) ---
    # Entropy weighting is applied to continuous variables only.
    # traffic_norm is included: on this corridor it is constant (all 1.0)
    # and receives zero weight automatically. On corridors with varying
    # traffic, it would contribute non-zero weight.
    # heat_norm is included now that the 500m buffer approach gives ~93%
    # segment coverage (script 04).
    cont_norm_cols = [
        "pvout_norm", "heat_norm", "building_norm", "curve_norm", "traffic_norm",
    ]
    cont_weight_names = [
        "weight_pvout", "weight_heat", "weight_building", "weight_curve", "weight_traffic",
    ]

    weights = entropy_weights(gdf[cont_norm_cols].copy())
    for norm_col, w_col in zip(cont_norm_cols, cont_weight_names):
        gdf[w_col] = weights[norm_col]

    gdf["weight_crossing"] = 0.0  # applied as penalty, not weighted

    weight_sum = sum(weights.values())
    assert abs(weight_sum - 1.0) < 1e-6, f"Weights do not sum to 1.0: {weight_sum}"
    log.info(f"Entropy weights (continuous): { {k: round(v, 4) for k, v in weights.items()} }")

    # --- crossing penalty ---
    # Level crossings are physical constraints: panels cannot span the
    # crossing surface. Per DB Netz Ril 815, active crossings have a
    # minimum 5.50 m carriageway (typically 6-8 m) plus required setbacks
    # (drainage >= 2.25 m from rail, barriers >= 3.00 m from track axis),
    # totalling ~15 m of unusable track per crossing -- about 7.5% of a
    # 200 m segment. The 15% penalty is conservative (accounts for
    # installation/maintenance margins) and sensitivity-tested at 10%/20%.
    CROSSING_PENALTY = 0.15
    gdf["crossing_penalty"] = (1.0 - CROSSING_PENALTY) ** gdf["crossing_count"]
    log.info(f"Crossing penalty: {CROSSING_PENALTY:.0%} per crossing "
             f"({(gdf['crossing_count'] > 0).sum()} segments affected)")

    # --- SEI score ---
    # Base score from continuous entropy-weighted factors, then crossing penalty
    gdf["sei_base"] = sum(gdf[nc] * weights[nc] for nc in cont_norm_cols)
    gdf["sei_score"] = gdf["sei_base"] * gdf["crossing_penalty"]
    gdf.loc[gdf["excluded"] == True, "sei_score"] = 0.0

    # --- rank ---
    non_excluded = gdf["excluded"] != True
    gdf["rank"] = np.nan
    gdf.loc[non_excluded, "rank"] = (
        gdf.loc[non_excluded, "sei_score"]
        .rank(ascending=False, method="min")
        .astype(int)
    )

    # --- quality tiers (quartile-based on non-excluded sei_score) ---
    gdf["sei_tier"] = "Excluded"
    ne_scores = gdf.loc[non_excluded, "sei_score"]
    q75, q50, q25 = ne_scores.quantile([0.75, 0.50, 0.25])
    gdf.loc[non_excluded & (gdf["sei_score"] >= q75), "sei_tier"] = "A"
    gdf.loc[non_excluded & (gdf["sei_score"] >= q50) & (gdf["sei_score"] < q75), "sei_tier"] = "B"
    gdf.loc[non_excluded & (gdf["sei_score"] >= q25) & (gdf["sei_score"] < q50), "sei_tier"] = "C"
    gdf.loc[non_excluded & (gdf["sei_score"] < q25), "sei_tier"] = "D"
    tier_counts = gdf["sei_tier"].value_counts().sort_index()
    log.info(f"Quality tiers: {tier_counts.to_dict()}  (thresholds: A>={q75:.3f}, B>={q50:.3f}, C>={q25:.3f}, D<{q25:.3f})")

    # --- save GeoJSON ---
    assert gdf.crs.to_epsg() == 25832, f"CRS wrong before save: {gdf.crs}"
    geojson_path = PROCESSED / "segments_final.geojson"
    gdf.to_file(geojson_path, driver="GeoJSON")
    log.info(f"Output saved to: {geojson_path}")

    # --- save ranked CSV ---
    table_dir = OUTPUTS / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    csv_path = table_dir / "segments_ranked.csv"
    csv_df = gdf.drop(columns=["geometry"]).sort_values("rank")
    csv_df.to_csv(csv_path, index=False)
    log.info(f"Output saved to: {csv_path}")

    # --- validate ---
    excluded_count = gdf["excluded"].sum()
    log.info(f"Excluded segments: {excluded_count}")

    top5 = gdf[gdf["excluded"] != True].nlargest(5, "sei_score")
    display_cols = [
        "segment_id", "rank", "sei_score",
        "pvout_annual", "building_dist_m", "deflection_deg",
        "crossing_count", "trains_per_day",
    ]
    log.info(f"Top-5 segments:\n{top5[display_cols].to_string(index=False)}")

    log.info(f"Rows processed: {len(gdf)}")
    log.info(f"Missing values:\n{gdf.isnull().sum()}")
    log.info(f"CRS: {gdf.crs}  |  Bounds: {gdf.total_bounds}")


if __name__ == "__main__":
    main()

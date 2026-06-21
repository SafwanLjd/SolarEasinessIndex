"""
Exploration: Alternative scoring approaches and TOPSIS validation.

This script compares scoring approaches side-by-side to validate that the
primary method (entropy-weighted SAW with crossing penalty) produces stable
rankings regardless of aggregation technique.

Approaches compared:
1. ALL-IN-ONE  - Entropy weighting on all 5 scored variables including binary
   crossing_count. Crossing receives ~58% weight due to its concentrated
   binary distribution - a known property of Shannon entropy, not engineering
   importance (Malczewski & Rinner 2015).

2. SAW-PENALTY - The primary method. Binary crossing_count is applied as a
   multiplicative penalty (15% per crossing) AFTER entropy weighting of
   continuous-only variables. Separates terrain suitability from physical
   obstructions.

3. HYBRID - Entropy on continuous variables, then a fixed additive deduction
   per crossing. Preserves continuous score ordering while penalising
   obstructions.

4. TOPSIS - Technique for Order of Preference by Similarity to Ideal
   Solution (Hwang & Yoon 1981). Uses the same entropy weights but ranks by
   Euclidean distance to ideal/anti-ideal solutions rather than weighted sum.
   Serves as an independent validation of the SAW-penalty rankings.

All approaches keep LSG exclusion (sei_score=0 for excluded segments).

References:
  - Shannon entropy weighting: Hwang & Yoon (1981), Shannon (1948)
  - TOPSIS: Hwang & Yoon (1981)
  - Multiplicative penalty in GIS-MCDA: Malczewski & Rinner (2015)
"""

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

PROCESSED = Path("data/processed")
OUTPUTS = Path("outputs")


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


def approach_allinone(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """All-in-one entropy weighting on all 5 scored variables."""
    scored_norm = ["pvout_norm", "building_norm", "curve_norm", "crossing_norm", "traffic_norm"]
    weights = entropy_weights(gdf[scored_norm].copy())

    score = sum(gdf[c] * weights[c] for c in scored_norm)

    # Rank ALL segments (including excluded) so we can see what
    # LSG segments would score without the exclusion constraint.
    ranks = score.rank(ascending=False, method="min").astype(int)

    return pd.DataFrame({
        "segment_id": gdf["segment_id"],
        "score_allinone": score.round(4),
        "rank_allinone": ranks,
    })


def approach_penalty(gdf: gpd.GeoDataFrame, crossing_penalty: float = 0.15) -> pd.DataFrame:
    """
    SAW-penalty approach (primary method): entropy weight continuous
    variables only, then multiply by (1 - penalty) for each crossing.
    """
    cont_norm = ["pvout_norm", "heat_norm", "building_norm", "curve_norm", "traffic_norm"]
    weights = entropy_weights(gdf[cont_norm].copy())

    log.info(f"SAW-PENALTY continuous-only entropy weights: "
             f"{ {k: round(v, 4) for k, v in weights.items()} }")

    cont_score = sum(gdf[c] * weights[c] for c in cont_norm)
    penalty_factor = (1.0 - crossing_penalty) ** gdf["crossing_count"]
    score = cont_score * penalty_factor

    ranks = score.rank(ascending=False, method="min").astype(int)

    return pd.DataFrame({
        "score_penalty": score.round(4),
        "rank_penalty": ranks,
    })


def approach_hybrid(gdf: gpd.GeoDataFrame, crossing_deduction: float = 0.10) -> pd.DataFrame:
    """
    Hybrid: entropy weight continuous variables, then subtract a fixed
    deduction per crossing.
    """
    cont_norm = ["pvout_norm", "heat_norm", "building_norm", "curve_norm", "traffic_norm"]
    weights = entropy_weights(gdf[cont_norm].copy())

    cont_score = sum(gdf[c] * weights[c] for c in cont_norm)
    score = cont_score - (crossing_deduction * gdf["crossing_count"])
    score = score.clip(lower=0.0)

    ranks = score.rank(ascending=False, method="min").astype(int)

    return pd.DataFrame({
        "score_hybrid": score.round(4),
        "rank_hybrid": ranks,
    })


def approach_topsis(gdf: gpd.GeoDataFrame, crossing_penalty: float = 0.15) -> pd.DataFrame:
    """
    TOPSIS (Hwang & Yoon 1981) with entropy weights on continuous
    variables and multiplicative crossing penalty.

    Ranks by relative closeness to ideal solution rather than weighted
    sum. Serves as an independent validation of the SAW-penalty rankings.
    """
    cont_norm = ["pvout_norm", "heat_norm", "building_norm", "curve_norm", "traffic_norm"]
    weights = entropy_weights(gdf[cont_norm].copy())

    # Weighted normalised matrix
    weighted = pd.DataFrame()
    for col in cont_norm:
        weighted[col] = gdf[col] * weights[col]

    # Ideal (best achievable) and anti-ideal (worst achievable) solutions
    ideal = weighted.max()
    anti_ideal = weighted.min()

    # Euclidean distances to ideal and anti-ideal
    d_plus = np.sqrt(((weighted - ideal) ** 2).sum(axis=1))
    d_minus = np.sqrt(((weighted - anti_ideal) ** 2).sum(axis=1))

    # Relative closeness (0 = worst, 1 = best)
    closeness = d_minus / (d_plus + d_minus)

    # Apply crossing penalty (same constraint layer as SAW-penalty)
    penalty_factor = (1.0 - crossing_penalty) ** gdf["crossing_count"]
    score = closeness * penalty_factor

    ranks = score.rank(ascending=False, method="min").astype(int)

    return pd.DataFrame({
        "score_topsis": score.round(4),
        "rank_topsis": ranks,
    })


def main():
    gdf = gpd.read_file(PROCESSED / "segments_final.geojson")
    if gdf.crs.to_epsg() != 25832:
        gdf = gdf.to_crs(25832)

    # Recompute normalised columns to ensure consistency
    gdf["pvout_norm"] = minmax_norm(gdf["pvout_annual"], invert=False)
    gdf["building_norm"] = minmax_norm(gdf["building_dist_m"], invert=True)
    gdf["curve_norm"] = minmax_norm(gdf["deflection_deg"], invert=True)
    gdf["crossing_norm"] = minmax_norm(gdf["crossing_count"], invert=True)
    gdf["traffic_norm"] = minmax_norm(gdf["trains_per_day"], invert=True)

    # Run all four approaches
    r_allinone = approach_allinone(gdf)
    r_penalty = approach_penalty(gdf)
    r_hybrid = approach_hybrid(gdf)
    r_topsis = approach_topsis(gdf)

    comparison = pd.concat([r_allinone, r_penalty, r_hybrid, r_topsis], axis=1)

    # --- Display top 15 by SAW-penalty rank ---
    ne = comparison.sort_values("rank_penalty")
    display_cols = [
        "segment_id",
        "score_penalty", "rank_penalty",
        "score_topsis", "rank_topsis",
        "score_allinone", "rank_allinone",
        "score_hybrid", "rank_hybrid",
    ]
    log.info("\n=== APPROACH COMPARISON (top 15 by SAW-penalty rank) ===")
    log.info(f"\n{ne[display_cols].head(15).to_string(index=False)}")

    # --- Spearman rank correlations ---
    rank_cols = ["rank_allinone", "rank_penalty", "rank_hybrid", "rank_topsis"]
    labels = ["All-in-one", "SAW-penalty", "Hybrid", "TOPSIS"]

    log.info(f"\n=== SPEARMAN RANK CORRELATIONS ===")
    for i in range(len(rank_cols)):
        for j in range(i + 1, len(rank_cols)):
            rho, _ = spearmanr(ne[rank_cols[i]], ne[rank_cols[j]])
            log.info(f"  {labels[i]} vs {labels[j]}: rho = {rho:.4f}")

    # --- Top-1 agreement ---
    top1 = {}
    for col, label in zip(["rank_penalty", "rank_topsis", "rank_allinone", "rank_hybrid"], labels[1:] + [labels[0]]):
        idx = ne[col].idxmin()
        top1[label] = ne.loc[idx, "segment_id"]

    log.info(f"\n=== TOP-1 SEGMENT ===")
    for label, seg in top1.items():
        log.info(f"  {label}: {seg}")

    if len(set(top1.values())) == 1:
        log.info("  All four approaches agree on the top-1 segment.")
    else:
        log.info("  DIVERGENCE: top-1 differs across approaches.")

    # --- Weight comparison ---
    log.info(f"\n=== WEIGHT COMPARISON ===")
    all5 = ["pvout_norm", "building_norm", "curve_norm", "crossing_norm", "traffic_norm"]
    cont4 = ["pvout_norm", "building_norm", "curve_norm", "traffic_norm"]
    w_all = entropy_weights(gdf[all5].copy())
    w_cont = entropy_weights(gdf[cont4].copy())
    log.info("  All-in-one (5-var entropy):")
    for k, v in w_all.items():
        log.info(f"    {k}: {v:.4f}")
    log.info("  SAW-penalty / TOPSIS (continuous-only entropy):")
    for k, v in w_cont.items():
        log.info(f"    {k}: {v:.4f}")

    # --- Segments with big rank shifts ---
    ne_c = ne.copy()
    ne_c["shift_topsis"] = ne_c["rank_penalty"] - ne_c["rank_topsis"]
    ne_c["shift_allinone"] = ne_c["rank_penalty"] - ne_c["rank_allinone"]
    big_shifts = ne_c[
        (ne_c["shift_topsis"].abs() > 5) | (ne_c["shift_allinone"].abs() > 5)
    ]
    if len(big_shifts) > 0:
        log.info(f"\n=== SEGMENTS WITH RANK SHIFT > 5 (vs SAW-penalty) ===")
        log.info(f"\n{big_shifts[['segment_id', 'rank_penalty', 'rank_topsis', 'shift_topsis', 'rank_allinone', 'shift_allinone']].to_string(index=False)}")
    else:
        log.info("\nNo segments shift by more than 5 ranks between approaches.")

    # --- Save comparison ---
    out_dir = OUTPUTS / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "scoring_comparison.csv"
    comparison.to_csv(out_path, index=False)
    log.info(f"\nFull comparison saved to: {out_path}")


if __name__ == "__main__":
    main()

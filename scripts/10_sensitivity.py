"""
Script 10: Sensitivity analysis - weight and penalty scenarios on top-10 segments
Input:  data/processed/segments_final.geojson
Output: outputs/tables/sensitivity_results.csv
        outputs/figures/sensitivity.png

Scenarios tested:
  1. Entropy baseline (continuous-only weights + crossing penalty)
  2. Equal weights across continuous variables (+ crossing penalty)
  3. +/-25% perturbation for each active continuous variable
  4. Crossing penalty at 10% and 20% (vs baseline 15%)
"""

import logging
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

PROCESSED = Path("data/processed")
OUTPUTS   = Path("outputs")

CONT_NORM_COLS = ["pvout_norm", "heat_norm", "building_norm", "curve_norm", "traffic_norm"]
CONT_WEIGHT_COLS = ["weight_pvout", "weight_heat", "weight_building", "weight_curve", "weight_traffic"]
CONT_VAR_NAMES = ["pvout", "heat", "building", "curve", "traffic"]

BASELINE_CROSSING_PENALTY = 0.15


def build_scenarios(w_base: dict) -> dict:
    """Return dict of scenario_name -> (weights_dict, crossing_penalty)."""
    scenarios = {}

    # 1. Entropy baseline
    scenarios["entropy"] = (dict(w_base), BASELINE_CROSSING_PENALTY)

    # 2. Equal weights across continuous variables
    eq_w = 1.0 / len(CONT_NORM_COLS)
    scenarios["equal"] = ({c: eq_w for c in CONT_NORM_COLS}, BASELINE_CROSSING_PENALTY)

    # 3. +/-25% perturbation for each active continuous variable
    for var, col in zip(CONT_VAR_NAMES, CONT_NORM_COLS):
        if w_base[col] < 1e-6:
            log.info(f"Skipping {var} perturbation scenarios - baseline weight is 0.")
            continue
        for label, factor in [("up25", 1.25), ("down25", 0.75)]:
            adjusted = {}
            new_val = w_base[col] * factor
            remaining = 1.0 - new_val
            others_sum = sum(w_base[c] for c in CONT_NORM_COLS if c != col)
            for c in CONT_NORM_COLS:
                if c == col:
                    adjusted[c] = new_val
                else:
                    adjusted[c] = w_base[c] / others_sum * remaining
            scenarios[f"{var}_{label}"] = (adjusted, BASELINE_CROSSING_PENALTY)

    # 4. Crossing penalty sensitivity
    scenarios["crossing_10pct"] = (dict(w_base), 0.10)
    scenarios["crossing_20pct"] = (dict(w_base), 0.20)

    return scenarios


def score_and_rank(gdf: pd.DataFrame, weights: dict, crossing_penalty: float) -> pd.Series:
    """Compute SEI score with penalty approach and return ranks."""
    base_score = sum(gdf[c] * weights[c] for c in CONT_NORM_COLS)
    penalty_factor = (1.0 - crossing_penalty) ** gdf["crossing_count"]
    score = base_score * penalty_factor
    score = score.where(gdf["excluded"] != True, 0.0)
    ranks = pd.Series(np.nan, index=gdf.index)
    mask = gdf["excluded"] != True
    ranks[mask] = score[mask].rank(ascending=False, method="min").astype(int)
    return ranks


def main():
    # --- load ---
    gdf = gpd.read_file(PROCESSED / "segments_final.geojson")
    if gdf.crs.to_epsg() != 25832:
        gdf = gdf.to_crs(25832)
    assert gdf.crs.to_epsg() == 25832, f"CRS wrong: {gdf.crs}"

    # Extract baseline entropy weights (continuous only)
    w_base = {c: gdf[wc].iloc[0] for c, wc in zip(CONT_NORM_COLS, CONT_WEIGHT_COLS)}
    log.info(f"Baseline weights: { {k: round(v, 4) for k, v in w_base.items()} }")

    # --- build scenarios ---
    scenarios = build_scenarios(w_base)
    log.info(f"Scenarios: {list(scenarios.keys())}")

    # --- identify top-10 from entropy baseline ---
    baseline_ranks = score_and_rank(gdf, *scenarios["entropy"])
    top10_idx = baseline_ranks.nsmallest(10).index
    top10_ids = list(gdf.loc[top10_idx, "segment_id"])
    log.info(f"Baseline top-10: {top10_ids}")

    # --- run all scenarios ---
    results = {}
    for name, (weights, cp) in scenarios.items():
        ranks = score_and_rank(gdf, weights, cp)
        results[name] = {
            gdf.loc[i, "segment_id"]: int(ranks[i])
            for i in top10_idx
        }

    result_df = pd.DataFrame(results)
    result_df.index.name = "segment_id"

    # --- save CSV ---
    table_dir = OUTPUTS / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    csv_path = table_dir / "sensitivity_results.csv"
    result_df.to_csv(csv_path)
    log.info(f"Output saved to: {csv_path}")

    # --- plot heatmap ---
    fig_dir = OUTPUTS / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 5))

    cmap = ListedColormap(["#2ca02c", "#ffdd57", "#d62728"])  # green, yellow, red
    bounds = [0.5, 3.5, 6.5, result_df.values.max() + 0.5]
    norm = BoundaryNorm(bounds, cmap.N)

    im = ax.imshow(result_df.values, cmap=cmap, norm=norm, aspect="auto")

    ax.set_xticks(range(len(result_df.columns)))
    ax.set_xticklabels(result_df.columns, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(result_df.index)))
    ax.set_yticklabels(result_df.index, fontsize=9)

    for i in range(result_df.shape[0]):
        for j in range(result_df.shape[1]):
            val = result_df.iloc[i, j]
            color = "white" if val > 6 else "black"
            ax.text(j, i, str(val), ha="center", va="center", fontsize=8, color=color)

    ax.set_xlabel("Weight scenario")
    ax.set_ylabel("Segment")
    ax.set_title("Sensitivity Analysis: Rank of Top-10 Segments Across Weight Scenarios")

    cbar = fig.colorbar(im, ax=ax, ticks=[2, 5, 8])
    cbar.ax.set_yticklabels(["Rank 1-3", "Rank 4-6", "Rank 7+"])

    plt.tight_layout()
    fig_path = fig_dir / "sensitivity.png"
    fig.savefig(fig_path, dpi=300)
    plt.close(fig)
    log.info(f"Output saved to: {fig_path}")

    # --- validate ---
    top1_id = top10_ids[0]
    top1_ranks = result_df.loc[top1_id]
    rank_min, rank_max = top1_ranks.min(), top1_ranks.max()
    log.info(f"Top-1 segment ({top1_id}) rank range: {rank_min}-{rank_max}")

    if rank_max <= 3:
        log.info("STABLE - top-1 stays in top-3 across all scenarios")
    elif rank_max <= 5:
        log.info("STABLE - top-1 stays in top-5 across all scenarios")
    else:
        log.info("REVIEW - top-1 falls out of top-5 in at least one scenario")

    log.info(f"Scenarios tested: {len(scenarios)}")
    log.info(f"Rows processed: {len(result_df)}")
    log.info(f"Missing values:\n{result_df.isnull().sum()}")


if __name__ == "__main__":
    main()

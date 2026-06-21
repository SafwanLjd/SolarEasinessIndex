# Solar-Easiness Index (SEI) for the Strohgaeubahn

A GIS pipeline that scores every 200 m segment of the Strohgaeubahn railway
(Heimerdingen to Korntal, Baden-Wuerttemberg) for between-the-rails photovoltaic
installation suitability, modelled on the [Sun-Ways](https://www.sun-ways.ch/en)
pilot in Switzerland.

**Result:** Segment **STR_060** (near Schwieberdingen, 9.025 E / 48.867 N) is
identified as the highest-scoring 200 m segment with an SEI score of 0.968,
stable across all 12 sensitivity scenarios.

![SEI Heatmap](outputs/heatmaps/strohgaeu_heatmap_static.png)

---

## Research Question

> There is currently no systematic, data-driven method to rank every stretch
> of track according to its suitability for PV installation. [...] The core
> problem is the absence of a unified, quantitative framework combining
> railway operational data, solar resource information and grid proximity
> metrics to identify the most promising rail segments.

This project develops and validates such a framework on the Strohgaeubahn,
a 16.4 km single-track, unelectrified branch line served by RB47. The
framework is designed for BW-wide application but is validated here on a
single pilot corridor. The final deliverable is the identification of the
highest-scoring 200 m segment as a pilot site for future rail-solar
deployment.

## Method Overview

The pipeline segments the railway into 200 m sections and evaluates each
using a two-layer scoring architecture:

**Layer 1: Continuous factor score** (`sei_base`): Shannon entropy-weighted
sum of continuous variables. Entropy weighting (Hwang & Yoon 1981) derives
variable importance objectively from the data distribution.

| Variable | Source | Direction | Entropy Weight |
|---|---|---|---|
| `heat_demand_p_m2` (kWh/a/m2) | Energieatlas BW building blocks (500 m buffer) | higher = better | 44.1% |
| `deflection_deg` (degrees) | Track curvature at midpoint | lower = better | 27.6% |
| `pvout_annual` (kWh/kWp/yr) | Global Solar Atlas PVOUT raster | higher = better | 15.4% |
| `building_dist_m` (metres) | OSM building centroids | lower = better | 12.9% |
| `trains_per_day` (integer) | RB47 timetable (manual parse) | lower = better | 0.0%\* |

\*Uniform across the single-track corridor (76 trains/day); entropy correctly
assigns zero weight. Retained for framework portability to multi-branch networks.

Heat demand is the mean `qoutg_p_m2` (total useful heat output per m2 of
building block area) across all Waermeatlas building blocks within 500 m of
each segment. The 500 m buffer captures the local low-voltage grid
neighbourhood and gives 93% segment coverage (75/81). Segments with no
building blocks within 500 m receive 0.0.

**Layer 2: Constraint penalties:**
- **Crossing penalty:** Each level crossing reduces the score by 15%
  (multiplicative: `sei_score = sei_base * 0.85^crossing_count`).
  Per DB Netz Ril 815, active crossings have a minimum 5.50 m
  carriageway (typically 6-8 m) plus required setbacks (drainage
  >= 2.25 m from rail, barriers >= 3.00 m from track axis), totalling
  ~15 m of unusable track per crossing (~7.5% of a 200 m segment).
  The 15% penalty is conservative (includes installation and
  maintenance margins) and sensitivity-tested at 10% and 20%.
  24 of 81 segments are affected.
- **LSG exclusion:** Segments intersecting a Landschaftsschutzgebiet within
  a 50 m buffer are conservatively excluded (`sei_score = 0`). LSG does not
  automatically prohibit PV installation but requires case-by-case planning
  review. This conservative treatment was chosen because a pilot deployment
  should target uncontested land where permitting is straightforward.

**Quality tiers:** Non-excluded segments are classified into quartile-based
tiers (A/B/C/D) on the SEI score. Excluded segments receive tier "Excluded."

### Why a Two-Layer Architecture?

Mixing binary and continuous variables in Shannon entropy weighting causes
the binary variable to dominate (~58% weight) due to its concentrated
distribution, a known property of the method (Malczewski & Rinner 2015),
not a reflection of engineering importance. The two-layer approach separates
"how suitable is the terrain?" (continuous entropy-weighted score) from
"are there physical obstructions?" (crossing penalty), which is standard
practice in GIS-MCDA suitability analysis.

### Validation Against TOPSIS

The primary method (entropy-weighted SAW with crossing penalty) was validated
against TOPSIS (Hwang & Yoon 1981), which ranks by Euclidean distance to
ideal/anti-ideal solutions rather than weighted sum. All four tested
approaches (SAW-penalty, TOPSIS, all-in-one entropy, hybrid) agree on the
same top-1 segment and top-4 ranking. SAW-penalty and TOPSIS produce a
Spearman rank correlation of rho = 0.98 across all 81 segments. See
`scripts/explore_scoring.py` for the full comparison.

---

## Corridor Facts

| Metric | Value |
|---|---|
| Line | Strohgaeubahn (RB47), Heimerdingen to Korntal |
| Measured length | 16,400 m |
| Segments | 81 (200 m each, stub < 50 m dropped) |
| Gauge | 1,435 mm (standard) |
| Electrification | None |
| Operator | ZV Strohgaeubahn |
| Service | 2 tph weekday, 1 tph Sunday |
| Weekday trains | 76 both directions |

---

## Repository Structure

```
.
├── README.md                  # This file
├── requirements.txt           # Python dependencies
│
├── scripts/
│   ├── 01_fetch_osm.py        # Fetch railway, buildings, stations, crossings from OSM
│   ├── 02_segment.py          # Segment line into 200 m pieces
│   ├── 03_solar_atlas.py      # Sample PVOUT raster at segment centroids
│   ├── 04_heat_demand.py      # Spatial join with waermebedarf building blocks
│   ├── 05_geometry_attrs.py   # Deflection angle, station proximity, crossing count
│   ├── 06_buildings_distance.py  # Distance to nearest OSM building
│   ├── 07_traffic.py          # Assign train frequency from timetable JSON
│   ├── 08_exclusion_lsg.py    # Flag segments intersecting LSG zones
│   ├── 09_merge_and_score.py  # Merge, normalise, entropy weight, score, rank, tier
│   ├── 10_sensitivity.py      # Weight perturbation scenarios
│   ├── 11_visualise.py        # Interactive HTML viewer + satellite static map
│   └── explore_scoring.py     # SAW vs TOPSIS validation (exploration only)
│
├── data/
│   ├── raw/                                   # All raw data committed via Git LFS
│   │   ├── solar/
│   │   │   └── PVOUT.tif                      # Global Solar Atlas (YearlyMonthlyTotals)
│   │   ├── heat_demand/
│   │   │   └── waermebedarf_baubloecke.*      # Energieatlas BW building blocks
│   │   ├── exclusions/
│   │   │   └── Landschaftsschutzgebiet (LSG).* # LUBW protected areas
│   │   ├── osm/                               # Cached Overpass API responses
│   │   │   ├── strohgaeu_named_ways.json
│   │   │   ├── buildings_corridor.json
│   │   │   ├── stations_corridor.json
│   │   │   └── crossings_corridor.json
│   │   ├── timetable/
│   │   │   ├── train_counts.json              # Manually parsed from PDF
│   │   │   └── rb47-*.pdf                     # Source timetable
│   │   └── railway/
│   │       └── railway_RB_47.* (shp+companions)  # VVS GTFS reference
│   │
│   └── processed/                             # Pipeline outputs (committed)
│       ├── strohgaeu_line.geojson             # Merged railway line
│       ├── segments_200m.geojson              # 81 segments with centroids
│       ├── buildings.geojson                  # OSM building centroids
│       ├── stations.geojson                   # Station/halt points
│       ├── crossings.geojson                  # Level crossing points
│       ├── pvout.csv                          # PVOUT values per segment
│       ├── heat_demand.csv                    # Heat demand per segment
│       ├── geometry_attrs.csv                 # Deflection, station, crossings
│       ├── buildings_distance.csv             # Building distance per segment
│       ├── traffic.csv                        # Train frequency per segment
│       ├── exclusion_flags.csv                # LSG flags
│       └── segments_final.geojson             # Final scored/ranked output
│
└── outputs/
    ├── heatmaps/
    │   ├── strohgaeu_heatmap.html             # Interactive Leaflet viewer
    │   └── strohgaeu_heatmap_static.png       # Static map (satellite basemap)
    ├── figures/
    │   └── sensitivity.png                    # Sensitivity heatmap
    └── tables/
        ├── segments_ranked.csv                # Ranked table (no geometry)
        ├── sensitivity_results.csv            # Rank of top-10 across scenarios
        └── scoring_comparison.csv             # SAW vs TOPSIS validation
```

---

## Pipeline

Scripts run sequentially from the project root. Each reads from `data/processed/`
or `data/raw/` and writes to `data/processed/` or `outputs/`.

```bash
python scripts/01_fetch_osm.py          # Requires internet (Overpass API)
python scripts/02_segment.py
python scripts/03_solar_atlas.py        # Requires data/raw/solar/PVOUT.tif
python scripts/04_heat_demand.py        # Requires data/raw/heat_demand/waermebedarf_baubloecke.*
python scripts/05_geometry_attrs.py
python scripts/06_buildings_distance.py
python scripts/07_traffic.py
python scripts/08_exclusion_lsg.py      # Requires data/raw/exclusions/Landschaftsschutzgebiet (LSG).*
python scripts/09_merge_and_score.py
python scripts/10_sensitivity.py
python scripts/11_visualise.py
```

**CRS rule:** All spatial analysis is performed in EPSG:25832 (UTM Zone 32N).
Coordinates are only converted to EPSG:4326 for Overpass API queries, raster
sampling, and Folium map display.

---

## Data Sources

The following external datasets are stored in `data/raw/` via Git LFS.
They are tracked automatically on clone (`git lfs pull`).

| Dataset | Placed at | Source |
|---|---|---|
| PVOUT.tif (YearlyMonthlyTotals) | `data/raw/solar/PVOUT.tif` | [Global Solar Atlas v2](https://globalsolaratlas.info/) |
| waermebedarf_baubloecke.* | `data/raw/heat_demand/` | Energieatlas Baden-Wuerttemberg |
| Landschaftsschutzgebiet (LSG).* | `data/raw/exclusions/` | LUBW Baden-Wuerttemberg |
| railway_RB_47.* | `data/raw/railway/` | VVS GTFS (reference only) |

**Important:** The PVOUT.tif must be from the **YearlyMonthlyTotals** directory,
not AvgDailyTotals. Yearly values for this corridor are 1151-1165 kWh/kWp/yr.
Daily averages (2-4 kWh/kWp/day) indicate the wrong file.

OSM data (railway line, buildings, stations, level crossings) was fetched
via the Overpass API and cached in `data/raw/osm/`. Script 01 skips the
API call when cache files are present, so no internet is needed to re-run.

Train counts (`data/raw/timetable/train_counts.json`) were manually parsed
from the RB47 timetable PDF and are committed to the repository for
traceability.

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3.11+.

---

## Key Results

### Top-1 Segment: STR_060

| Component | Raw Value | Normalised | Weight | Contribution |
|---|---|---|---|---|
| heat_demand_p_m2 | 51.6 kWh/a/m2 | 0.936 | 0.441 | 0.412 |
| deflection_deg | 0.03 deg | 0.999 | 0.276 | 0.276 |
| pvout_annual | 1165.5 kWh/kWp/yr | 1.000 | 0.154 | 0.154 |
| building_dist_m | 18.1 m | 0.975 | 0.129 | 0.126 |
| trains_per_day | 76 | 1.000 | 0.000 | 0.000 |
| **sei_base** | | | | **0.968** |
| crossing_count | 0 | penalty = 1.000 | | x 1.000 |
| **SEI score** | | | | **0.968** |

Location: 9.025 E, 48.867 N (straight track between Schwieberdingen and
Hemmingen, no level crossings, 18 m from nearest building, not in LSG).

### Quality Tier Distribution

| Tier | Count | SEI Score Range |
|---|---|---|
| A (top 25%) | 15 | >= 0.762 |
| B (25-50%) | 15 | 0.648 - 0.761 |
| C (50-75%) | 15 | 0.546 - 0.647 |
| D (bottom 25%) | 15 | < 0.546 |
| Excluded (LSG) | 21 | 0.000 |

### Sensitivity Analysis

12 scenarios tested: entropy baseline, equal weights, +/-25% perturbation
for each of the 4 active continuous variables (heat, curve, pvout, building),
and crossing penalty at 10%/20% (vs baseline 15%). STR_060 holds rank 1
across **all** scenarios. Top-10 membership is stable across all tested
weight configurations.

![Sensitivity Analysis](outputs/figures/sensitivity.png)

---

## Limitations

1. **Solar resource resolution.** The Global Solar Atlas PVOUT raster
   (~250 m pixels) slightly exceeds the 200 m segment length, and solar
   yield varies only 1.2% across this corridor. The framework would benefit
   from higher-resolution irradiance data or would show greater
   discrimination on corridors spanning varied terrain.
2. **Grid access proxy.** Building distance serves as a proxy for
   low-voltage grid access. Direct Ortsnetzstation distances would be more
   precise but are not openly available at the required spatial resolution.
3. **No shading model.** Local shading from vegetation, embankments, and
   adjacent structures is not captured. A LiDAR-based or site-survey
   analysis would be needed for detailed installation planning.
4. **Fixed 200 m segmentation.** Non-overlapping windows mean the optimal
   site could straddle a boundary. In practice, the scored variables change
   gradually along this corridor, so a small offset would not significantly
   alter the top-ranked result.

---

## References

- Hwang, C.L. and Yoon, K. (1981). *Multiple Attribute Decision Making: Methods and Applications*. Springer.
- Malczewski, J. and Rinner, C. (2015). *Multicriteria Decision Analysis in Geographic Information Science*. Springer.
- Shannon, C.E. (1948). A Mathematical Theory of Communication. *Bell System Technical Journal*, 27(3), 379-423.
- Sun-Ways SA. Rail-solar pilot project. https://www.sun-ways.ch/en
- Global Solar Atlas v2. https://globalsolaratlas.info/
- OpenRailwayMap. https://www.openrailwaymap.org/

---

## License

This is a university research project. Code is provided as-is for academic purposes.
External datasets are subject to their respective licenses (see Data Sources above).

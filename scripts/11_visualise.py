"""
Script 11: Generate static map (satellite basemap) and interactive HTML viewer.

Input:  data/processed/segments_final.geojson
        data/processed/stations.geojson
Output: outputs/heatmaps/strohgaeu_heatmap.html
        outputs/heatmaps/strohgaeu_heatmap_static.png
"""

import json
import logging
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.cm import ScalarMappable

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

PROCESSED = Path("data/processed")
OUTPUTS = Path("outputs")

SEI_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "solar", [(0.8, 0.0, 0.0), (1.0, 0.75, 0.0), (0.0, 0.7, 0.0)], N=256
)
SEI_NORM = mcolors.Normalize(vmin=0, vmax=1)


def rgb_hex(val: float) -> str:
    """Convert a 0-1 SEI score to a hex color string."""
    r, g, b, _ = SEI_CMAP(SEI_NORM(val))
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


# ---------------------------------------------------------------------------
# Static map with satellite basemap
# ---------------------------------------------------------------------------

def build_static_map(segments: gpd.GeoDataFrame, stations: gpd.GeoDataFrame,
                     out_path: Path):
    seg_3857 = segments.to_crs(3857)
    sta_3857 = stations.to_crs(3857)

    fig, ax = plt.subplots(figsize=(12, 14), dpi=300)

    all_bounds = seg_3857.total_bounds
    pad = 500
    ax.set_xlim(all_bounds[0] - pad, all_bounds[2] + pad)
    ax.set_ylim(all_bounds[1] - pad, all_bounds[3] + pad)

    cx.add_basemap(ax, source=cx.providers.Esri.WorldImagery, zoom=14)

    non_excluded = seg_3857[seg_3857["excluded"] != True]
    excluded = seg_3857[seg_3857["excluded"] == True]

    # Black outline for all segments
    for _, row in seg_3857.iterrows():
        xs, ys = row.geometry.xy
        ax.plot(xs, ys, color="black", linewidth=7, solid_capstyle="round",
                zorder=3)

    # Excluded segments in muted grey
    for _, row in excluded.iterrows():
        xs, ys = row.geometry.xy
        ax.plot(xs, ys, color="#666666", linewidth=4, solid_capstyle="round",
                zorder=4, alpha=0.6)

    # Non-excluded segments colored by SEI score
    for _, row in non_excluded.iterrows():
        color = SEI_CMAP(SEI_NORM(row["sei_score"]))
        xs, ys = row.geometry.xy
        ax.plot(xs, ys, color=color, linewidth=4, solid_capstyle="round",
                zorder=4)

    # Top-1 segment highlight (white glow)
    top1 = non_excluded.loc[non_excluded["rank"].idxmin()]
    bx, by = top1.geometry.xy
    ax.plot(bx, by, color="white", linewidth=11, solid_capstyle="round",
            zorder=4.4, alpha=0.7)
    ax.plot(bx, by, color=SEI_CMAP(SEI_NORM(top1["sei_score"])), linewidth=5,
            solid_capstyle="round", zorder=4.5)

    best_mid = top1.geometry.interpolate(0.5, normalized=True)
    ax.annotate(
        f"BEST SEGMENT\n{top1['segment_id']} - SEI {top1['sei_score']:.3f}",
        xy=(best_mid.x, best_mid.y),
        xytext=(30, 30), textcoords="offset points",
        fontsize=8, fontweight="bold", color="#00ee00",
        arrowprops=dict(arrowstyle="-|>", color="white", lw=2),
        path_effects=[pe.withStroke(linewidth=3, foreground="black")],
        bbox=dict(boxstyle="round,pad=0.3", facecolor="black", alpha=0.7,
                  edgecolor="white"),
        zorder=7,
    )

    # Station markers with labels (clip to plot bounds to avoid overflow)
    sta_3857.plot(ax=ax, color="white", edgecolor="black", markersize=80,
                  zorder=5, linewidth=1.5)
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    for _, row in sta_3857.iterrows():
        sx, sy = row.geometry.x, row.geometry.y
        near_right = sx > xlim[0] + 0.75 * (xlim[1] - xlim[0])
        near_top = sy > ylim[0] + 0.85 * (ylim[1] - ylim[0])
        ox = -14 if near_right else 14
        oy = -12 if near_top else 10
        ha = "right" if near_right else "left"
        ax.annotate(
            row["name"],
            xy=(sx, sy),
            xytext=(ox, oy), textcoords="offset points",
            fontsize=8, fontweight="bold", color="white", ha=ha,
            path_effects=[pe.withStroke(linewidth=3, foreground="black")],
            zorder=6,
            annotation_clip=True,
        )

    # Colorbar inside the map area (no white space below)
    cax = ax.inset_axes([0.02, 0.10, 0.28, 0.018])
    cax.set_facecolor((0, 0, 0, 0.55))
    sm = ScalarMappable(cmap=SEI_CMAP, norm=SEI_NORM)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cbar.set_label("Solar-Easiness Index", fontsize=8, fontweight="bold",
                   color="white", labelpad=2)
    cbar.set_ticks([0, 0.25, 0.5, 0.75, 1.0])
    cbar.ax.tick_params(colors="white", labelsize=7, length=0)

    ax.set_title("Strohgaeubahn - Solar-Easiness Index (SEI)",
                 fontsize=14, fontweight="bold", pad=15)
    ax.set_axis_off()

    fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Interactive HTML map (self-contained Leaflet)
# ---------------------------------------------------------------------------

def build_interactive_html(segments: gpd.GeoDataFrame,
                           stations: gpd.GeoDataFrame, out_path: Path):
    seg4326 = segments.to_crs(4326)
    sta4326 = stations.to_crs(4326)

    seg_features = []
    for _, row in seg4326.iterrows():
        coords = list(row.geometry.coords)
        props = {
            "id": row["segment_id"],
            "score": round(float(row["sei_score"]), 4),
            "base": round(float(row["sei_base"]), 4),
            "tier": row["sei_tier"],
            "rank": None if np.isnan(row["rank"]) else int(row["rank"]),
            "pvout": round(float(row["pvout_annual"]), 1),
            "bldg": round(float(row["building_dist_m"]), 1),
            "defl": round(float(row["deflection_deg"]), 2),
            "xing": int(row["crossing_count"]),
            "xpen": round(float(row["crossing_penalty"]), 3),
            "trains": int(row["trains_per_day"]),
            "heat": round(float(row["heat_demand_p_m2"]), 1),
            "station": bool(row["near_station"]),
            "lsg": bool(row["in_lsg"]),
            "excl": bool(row["excluded"]),
            "pn": round(float(row["pvout_norm"]), 4),
            "hn": round(float(row["heat_norm"]), 4),
            "bn": round(float(row["building_norm"]), 4),
            "cn": round(float(row["curve_norm"]), 4),
            "tn": round(float(row["traffic_norm"]), 4),
            "wp": round(float(row["weight_pvout"]), 4),
            "wh": round(float(row["weight_heat"]), 4),
            "wb": round(float(row["weight_building"]), 4),
            "wc": round(float(row["weight_curve"]), 4),
            "wt": round(float(row["weight_traffic"]), 4),
        }
        seg_features.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[c[0], c[1]] for c in coords]},
            "properties": props,
        })

    sta_features = []
    for _, row in sta4326.iterrows():
        sta_features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [row.geometry.x, row.geometry.y]},
            "properties": {"name": row["name"],
                           "railway_type": row["railway_type"]},
        })

    seg_json = json.dumps({"type": "FeatureCollection",
                           "features": seg_features})
    sta_json = json.dumps({"type": "FeatureCollection",
                           "features": sta_features})

    n_stops = 20
    gradient_stops = []
    for i in range(n_stops + 1):
        v = i / n_stops
        gradient_stops.append(f"{rgb_hex(v)} {v*100:.0f}%")
    gradient_css = ", ".join(gradient_stops)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Strohgaeubahn -- Solar-Easiness Index</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f1729; }}

  #panel {{
    position: fixed; top: 0; left: 0; width: 340px; bottom: 0;
    background: #0f1729; color: #d0d8e8; overflow-y: auto;
    display: flex; flex-direction: column; z-index: 1000;
    border-right: 1px solid #1e293b;
  }}
  #map {{ position: fixed; top: 0; left: 340px; right: 0; bottom: 0; }}

  .hdr {{ padding: 16px 18px 12px; border-bottom: 1px solid #1e293b; }}
  .hdr h1 {{ font-size: 15px; color: #fff; letter-spacing: 0.02em; }}
  .hdr p {{ font-size: 11px; color: #64748b; margin-top: 2px; }}

  .ctrl {{
    padding: 10px 18px; border-bottom: 1px solid #1e293b;
    display: flex; flex-wrap: wrap; gap: 4px 14px;
  }}
  .ctrl label {{
    font-size: 11px; display: flex; align-items: center; gap: 5px;
    cursor: pointer; user-select: none;
  }}
  .ctrl input[type="checkbox"] {{ accent-color: #22c55e; width: 13px; height: 13px; }}

  .lgd {{ padding: 10px 18px; border-bottom: 1px solid #1e293b; }}
  .lgd-title {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 5px; }}
  .lgd-bar {{
    height: 10px; border-radius: 5px;
    background: linear-gradient(to right, {gradient_css});
  }}
  .lgd-labels {{
    display: flex; justify-content: space-between;
    font-size: 9px; color: #475569; margin-top: 3px;
  }}

  /* --- winner banner --- */
  #winner {{
    padding: 10px 18px; border-bottom: 1px solid #1e293b;
    background: linear-gradient(135deg, #052e16 0%, #0f1729 100%);
    cursor: pointer; transition: background 0.15s;
  }}
  #winner:hover {{ background: linear-gradient(135deg, #064e3b 0%, #0f1729 100%); }}
  #winner-label {{ font-size: 9px; color: #4ade80; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }}
  #winner-body {{ display: flex; align-items: baseline; gap: 10px; margin-top: 3px; }}
  #winner-id {{ font-size: 16px; color: #fff; font-weight: 700; }}
  #winner-score {{ font-size: 13px; color: #4ade80; font-weight: 600; }}
  #winner-sub {{ font-size: 10px; color: #64748b; margin-top: 1px; }}

  /* --- segment list --- */
  #seg-list {{ flex: 1; overflow-y: auto; }}
  .seg {{
    padding: 7px 18px; cursor: pointer; display: flex;
    align-items: center; gap: 8px; font-size: 12px;
    border-bottom: 1px solid rgba(255,255,255,0.03);
    transition: background 0.12s;
  }}
  .seg:hover {{ background: #1e293b; }}
  .seg.act {{ background: #1e3a5f; }}
  .seg.muted {{ opacity: 0.35; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; border: 1px solid rgba(255,255,255,0.1); }}
  .seg .rk {{ width: 26px; color: #475569; text-align: right; flex-shrink: 0; font-size: 11px; }}
  .seg .nm {{ flex: 1; color: #cbd5e1; }}
  .seg .sc {{ color: #64748b; font-size: 11px; font-variant-numeric: tabular-nums; }}
  .seg .tier {{
    font-size: 9px; padding: 1px 5px; border-radius: 3px;
    font-weight: 600; flex-shrink: 0; letter-spacing: 0.04em;
  }}
  .tA {{ background: #14532d; color: #86efac; }}
  .tB {{ background: #3f6212; color: #bef264; }}
  .tC {{ background: #713f12; color: #fcd34d; }}
  .tD {{ background: #7f1d1d; color: #fca5a5; }}
  .tX {{ background: #1e293b; color: #475569; }}

  /* --- detail panel --- */
  #detail {{
    background: #0c1322; border-top: 2px solid #22c55e;
    padding: 14px 18px; display: none;
  }}
  #detail h3 {{ font-size: 13px; color: #22c55e; margin-bottom: 10px; }}

  .brk {{ margin-bottom: 8px; }}
  .brk-row {{
    display: flex; align-items: center; gap: 6px;
    margin-bottom: 5px; font-size: 11px;
  }}
  .brk-label {{ width: 110px; color: #64748b; flex-shrink: 0; }}
  .brk-track {{ flex: 1; height: 8px; background: #1e293b; border-radius: 4px; overflow: hidden; }}
  .brk-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; min-width: 1px; }}
  .brk-val {{ width: 40px; text-align: right; color: #94a3b8; font-variant-numeric: tabular-nums; flex-shrink: 0; }}

  .brk-sep {{ border-top: 1px solid #1e293b; margin: 8px 0; }}
  .brk-total {{
    display: flex; justify-content: space-between;
    font-size: 11px; color: #94a3b8; padding: 2px 0;
  }}
  .brk-total span:last-child {{ color: #e2e8f0; font-weight: 600; }}

  .info {{ margin-top: 10px; }}
  .info-row {{
    display: flex; justify-content: space-between;
    font-size: 11px; padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.03);
  }}
  .info-row dt {{ color: #64748b; }}
  .info-row dd {{ color: #cbd5e1; font-variant-numeric: tabular-nums; }}

  .sta-lbl {{
    background: rgba(0,0,0,0.75) !important;
    border: none !important; color: white !important;
    font-size: 11px !important; font-weight: 600 !important;
    padding: 2px 7px !important; border-radius: 3px !important;
    box-shadow: none !important;
  }}
  .sta-lbl::before {{ display: none !important; }}
</style>
</head>
<body>

<div id="panel">
  <div class="hdr">
    <h1>Solar-Easiness Index</h1>
    <p>Strohgaeubahn &middot; Heimerdingen -- Korntal &middot; 81 segments</p>
  </div>

  <div class="ctrl">
    <label><input type="checkbox" id="ck-lsg" checked> Exclude LSG zones</label>
    <label><input type="checkbox" id="ck-sta" checked> Stations</label>
    <label><input type="checkbox" id="ck-sat"> Satellite</label>
  </div>

  <div class="lgd">
    <div class="lgd-title">SEI Score</div>
    <div class="lgd-bar"></div>
    <div class="lgd-labels"><span>0.0</span><span>0.25</span><span>0.50</span><span>0.75</span><span>1.0</span></div>
  </div>

  <div id="winner" onclick="pickWinner()">
    <div id="winner-label">BEST SEGMENT</div>
    <div id="winner-body">
      <span id="winner-id">--</span>
      <span id="winner-score">--</span>
    </div>
    <div id="winner-sub"></div>
  </div>

  <div id="seg-list"></div>

  <div id="detail">
    <h3 id="det-title"></h3>
    <div class="brk" id="det-brk"></div>
    <div class="info" id="det-info"></div>
  </div>
</div>

<div id="map"></div>

<script>
const S = {seg_json};
const ST = {sta_json};

function seiColor(v) {{
  v = Math.max(0, Math.min(1, v));
  let r, g, b;
  if (v < 0.5) {{
    const t = v / 0.5;
    r = 0.8 + t * 0.2; g = t * 0.75; b = 0;
  }} else {{
    const t = (v - 0.5) / 0.5;
    r = 1.0 - t; g = 0.75 + t * (0.7 - 0.75); b = 0;
  }}
  return '#' + [r,g,b].map(c => Math.round(c*255).toString(16).padStart(2,'0')).join('');
}}

// --- map ---
const map = L.map('map', {{ zoomControl: true }});
const tLight = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}@2x.png', {{
  attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 19
}}).addTo(map);
const tSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
  attribution: '&copy; Esri', maxZoom: 19
}});

const layers = {{}};
S.features.forEach(f => {{
  const ly = L.geoJSON(f, {{ style: {{ color: '#444', weight: 4, opacity: 0.5 }} }});
  ly.on('click', () => pick(f.properties.id));
  ly.addTo(map);
  layers[f.properties.id] = ly;
}});

const staLayer = L.geoJSON(ST, {{
  pointToLayer: (f, ll) => L.circleMarker(ll, {{
    radius: 6, color: '#1e293b', fillColor: '#fff', fillOpacity: 0.9, weight: 2
  }}),
  onEachFeature: (f, ly) => {{
    ly.bindTooltip(f.properties.name, {{
      permanent: true, direction: 'right', offset: [10, 0], className: 'sta-lbl'
    }});
  }}
}}).addTo(map);

map.fitBounds(L.featureGroup(Object.values(layers)).getBounds().pad(0.05));

// --- winner glow layer ---
let glowLayer = null;

// --- scoring ---
let scoreMap = {{}};
let winnerId = null;

function rescore() {{
  const exLSG = document.getElementById('ck-lsg').checked;
  const arr = S.features.map(f => {{
    const p = f.properties;
    let score = p.base * p.xpen;
    const excluded = exLSG && p.lsg;
    if (excluded) score = 0;
    return {{ id: p.id, score, excluded }};
  }});

  // rank non-excluded
  arr.filter(s => !s.excluded).sort((a, b) => b.score - a.score).forEach((s, i) => s.rank = i + 1);
  arr.filter(s => s.excluded).forEach(s => s.rank = null);

  // tier assignment
  const ne = arr.filter(s => !s.excluded);
  const n = ne.length;
  const sorted = [...ne].sort((a, b) => b.score - a.score);
  sorted.forEach((s, i) => {{
    const q = i / n;
    s.tier = q < 0.25 ? 'A' : q < 0.5 ? 'B' : q < 0.75 ? 'C' : 'D';
  }});
  arr.filter(s => s.excluded).forEach(s => s.tier = 'Excluded');

  scoreMap = Object.fromEntries(arr.map(s => [s.id, s]));

  // find winner
  const w = arr.find(s => s.rank === 1);
  winnerId = w ? w.id : null;

  paint();
  updateWinner();
}}

function paint() {{
  // update map segment styles
  S.features.forEach(f => {{
    const s = scoreMap[f.properties.id];
    const ly = layers[f.properties.id];
    const isWinner = f.properties.id === winnerId;
    ly.setStyle({{
      color: s.excluded ? '#555' : seiColor(s.score),
      weight: isWinner ? 7 : (s.excluded ? 3 : 5),
      opacity: s.excluded ? 0.3 : 0.85
    }});
    // bring winner to front
    if (isWinner) ly.bringToFront();
  }});

  // winner glow on map
  if (glowLayer) {{ map.removeLayer(glowLayer); glowLayer = null; }}
  if (winnerId) {{
    const wf = S.features.find(f => f.properties.id === winnerId);
    if (wf) {{
      glowLayer = L.geoJSON(wf, {{
        style: {{ color: '#ffffff', weight: 12, opacity: 0.45, lineCap: 'round' }}
      }}).addTo(map);
    }}
  }}

  // rebuild sidebar list
  const sorted = S.features.map(f => ({{ ...f.properties, ...scoreMap[f.properties.id] }}))
    .sort((a, b) => {{
      if (a.rank == null && b.rank == null) return 0;
      if (a.rank == null) return 1;
      if (b.rank == null) return -1;
      return a.rank - b.rank;
    }});

  const el = document.getElementById('seg-list');
  el.innerHTML = '';
  sorted.forEach(s => {{
    const div = document.createElement('div');
    div.className = 'seg' + (s.excluded ? ' muted' : '') + (s.id === activeSeg ? ' act' : '');
    div.dataset.id = s.id;
    const col = s.excluded ? '#555' : seiColor(s.score);
    const tc = 't' + (s.tier === 'Excluded' ? 'X' : s.tier);
    div.innerHTML = `
      <div class="dot" style="background:${{col}}"></div>
      <span class="rk">${{s.rank ? '#' + s.rank : '--'}}</span>
      <span class="nm">${{s.id}}</span>
      <span class="sc">${{s.excluded ? 'excl.' : s.score.toFixed(3)}}</span>
      <span class="tier ${{tc}}">${{s.tier === 'Excluded' ? 'LSG' : s.tier}}</span>
    `;
    div.addEventListener('click', () => pick(s.id));
    el.appendChild(div);
  }});
}}

function updateWinner() {{
  if (!winnerId) return;
  const s = scoreMap[winnerId];
  const p = S.features.find(f => f.properties.id === winnerId).properties;
  document.getElementById('winner-id').textContent = winnerId;
  document.getElementById('winner-score').textContent = 'SEI ' + s.score.toFixed(3);
  document.getElementById('winner-sub').textContent = 'Tier A  ·  ' + p.pvout + ' kWh/kWp/yr  ·  ' + p.bldg + ' m to grid  ·  ' + p.defl + '° deflection';
}}

function pickWinner() {{
  if (winnerId) pick(winnerId);
}}

// --- selection highlight ---
let activeSeg = null;
let selectLayer = null;

function pick(id) {{
  activeSeg = id;
  document.querySelectorAll('.seg.act').forEach(e => e.classList.remove('act'));
  const el = document.querySelector('[data-id="' + id + '"]');
  if (el) {{ el.classList.add('act'); el.scrollIntoView({{ block: 'nearest' }}); }}

  const ly = layers[id];
  if (ly) map.fitBounds(ly.getBounds().pad(8), {{ maxZoom: 15 }});

  // highlight selected segment with a white outline
  if (selectLayer) {{ map.removeLayer(selectLayer); selectLayer = null; }}
  const sf = S.features.find(f => f.properties.id === id);
  if (sf) {{
    selectLayer = L.geoJSON(sf, {{
      style: {{ color: '#ffffff', weight: 10, opacity: 0.7, lineCap: 'round' }}
    }}).addTo(map);
  }}

  const f = S.features.find(f => f.properties.id === id);
  if (!f) return;
  const p = f.properties;
  const s = scoreMap[id];

  // title
  const title = document.getElementById('det-title');
  let suffix = '';
  if (s.rank) suffix = ' (Rank #' + s.rank + ' / Tier ' + s.tier + ')';
  else if (s.excluded) suffix = ' (Excluded)';
  title.textContent = p.id + suffix;

  // score breakdown bars - show weighted contribution as share of base score
  const factors = [
    {{ label: 'Curvature', weight: p.wc, norm: p.cn, color: '#818cf8' }},
    {{ label: 'PVOUT', weight: p.wp, norm: p.pn, color: '#fbbf24' }},
    {{ label: 'Heat demand', weight: p.wh, norm: p.hn, color: '#f97316' }},
    {{ label: 'Building dist.', weight: p.wb, norm: p.bn, color: '#22d3ee' }},
    {{ label: 'Traffic', weight: p.wt, norm: p.tn, color: '#64748b' }},
  ];

  const contribs = factors.map(f => f.norm * f.weight);

  let brkHtml = '';
  factors.forEach((f, i) => {{
    const contrib = contribs[i];
    const barPct = (f.norm * 100).toFixed(0);
    const wPct = (f.weight * 100).toFixed(1);
    brkHtml += `
      <div class="brk-row">
        <span class="brk-label">${{f.label}} (${{wPct}}%)</span>
        <div class="brk-track"><div class="brk-fill" style="width:${{barPct}}%;background:${{f.color}}"></div></div>
        <span class="brk-val">${{f.norm.toFixed(2)}}</span>
      </div>`;
  }});
  brkHtml += '<div class="brk-sep"></div>';
  brkHtml += '<div class="brk-total"><span>Base score</span><span>' + p.base.toFixed(4) + '</span></div>';
  if (p.xing > 0) {{
    brkHtml += '<div class="brk-total"><span>&times; Crossing penalty (' + p.xing + ' crossing)</span><span>&times; ' + p.xpen.toFixed(3) + '</span></div>';
  }}
  brkHtml += '<div class="brk-total"><span>SEI Score</span><span>' + s.score.toFixed(4) + '</span></div>';
  document.getElementById('det-brk').innerHTML = brkHtml;

  // info grid
  const info = [
    ['PVOUT', p.pvout.toFixed(1) + ' kWh/kWp/yr'],
    ['Building dist.', p.bldg.toFixed(1) + ' m'],
    ['Deflection', p.defl.toFixed(2) + '&deg;'],
    ['Crossings', p.xing],
    ['Trains/day', p.trains],
    ['Heat demand', p.heat.toFixed(1) + ' kWh/m&sup2;/yr'],
    ['Near station', p.station ? 'Yes' : 'No'],
    ['In LSG', p.lsg ? 'Yes' : 'No'],
  ];
  document.getElementById('det-info').innerHTML = info.map(function(kv) {{
    return '<div class="info-row"><dt>' + kv[0] + '</dt><dd>' + kv[1] + '</dd></div>';
  }}).join('');

  document.getElementById('detail').style.display = 'block';
}}

// --- controls ---
document.getElementById('ck-lsg').addEventListener('change', rescore);
document.getElementById('ck-sta').addEventListener('change', function() {{
  this.checked ? staLayer.addTo(map) : map.removeLayer(staLayer);
}});
document.getElementById('ck-sat').addEventListener('change', function() {{
  if (this.checked) {{ map.removeLayer(tLight); tSat.addTo(map); }}
  else {{ map.removeLayer(tSat); tLight.addTo(map); }}
}});

// --- init ---
rescore();
if (winnerId) pick(winnerId);
</script>
</body>
</html>"""

    out_path.write_text(html)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    segments = gpd.read_file(PROCESSED / "segments_final.geojson")
    if segments.crs.to_epsg() != 25832:
        segments = segments.to_crs(25832)
    assert segments.crs.to_epsg() == 25832

    stations = gpd.read_file(PROCESSED / "stations.geojson")
    if stations.crs.to_epsg() != 25832:
        stations = stations.to_crs(25832)
    assert stations.crs.to_epsg() == 25832

    heatmap_dir = OUTPUTS / "heatmaps"
    heatmap_dir.mkdir(parents=True, exist_ok=True)

    # Static map
    png_path = heatmap_dir / "strohgaeu_heatmap_static.png"
    build_static_map(segments, stations, png_path)
    log.info(f"Output saved to: {png_path}")

    # Interactive HTML
    html_path = heatmap_dir / "strohgaeu_heatmap.html"
    build_interactive_html(segments, stations, html_path)
    log.info(f"Output saved to: {html_path}")

    # Top-1 breakdown
    non_excluded = segments[segments["excluded"] != True]
    top1 = non_excluded.loc[non_excluded["rank"].idxmin()]

    log.info(f"Top-1 segment: {top1['segment_id']}")
    log.info(f"  Centroid: ({top1['centroid_lon']:.4f}, {top1['centroid_lat']:.4f})")
    log.info(f"  SEI score: {top1['sei_score']:.4f}")

    for name, norm_col, weight_col in [
        ("pvout", "pvout_norm", "weight_pvout"),
        ("heat", "heat_norm", "weight_heat"),
        ("building", "building_norm", "weight_building"),
        ("curve", "curve_norm", "weight_curve"),
        ("traffic", "traffic_norm", "weight_traffic"),
    ]:
        val = top1[norm_col] * top1[weight_col]
        log.info(f"  {name}: norm={top1[norm_col]:.3f} x w={top1[weight_col]:.3f} = {val:.4f}")
    log.info(f"  sei_base={top1['sei_base']:.4f} x penalty={top1['crossing_penalty']:.3f}"
             f" = sei_score={top1['sei_score']:.4f}")


if __name__ == "__main__":
    main()

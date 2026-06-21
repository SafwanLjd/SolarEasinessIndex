"""
Script 01: Fetch OSM data for Strohgäubahn corridor
Input:  Overpass API (three queries)
Output: data/raw/osm/strohgaeu_named_ways.json  (cached raw response)
        data/raw/osm/buildings_corridor.json    (cached raw response)
        data/raw/osm/stations_corridor.json     (cached raw response)
        data/raw/osm/crossings_corridor.json    (cached raw response)
        data/processed/strohgaeu_line.geojson   (merged LineString, EPSG:25832)
        data/processed/buildings.geojson        (building centroids, EPSG:25832)
        data/processed/stations.geojson         (station/halt points, EPSG:25832)
        data/processed/crossings.geojson        (level crossing points, EPSG:25832)
"""

import json
import logging
import subprocess
import time
from pathlib import Path

import geopandas as gpd
import pyproj
from shapely.geometry import LineString, Point
from shapely.ops import substring

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

RAW       = Path("data/raw")
PROCESSED = Path("data/processed")


# ---------------------------------------------------------------------------
# Overpass API helper with mirror fallback
# ---------------------------------------------------------------------------

def fetch_overpass(query: str, cache_path: Path) -> dict:
    if cache_path.exists():
        log.info(f"Cache hit: {cache_path}")
        return json.loads(cache_path.read_text())
    log.info("Fetching from Overpass...")
    urls = [
        "https://z.overpass-api.de/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    data = None
    for url in urls:
        try:
            log.info(f"Trying {url}")
            result = subprocess.run(
                ["curl", "-s", "-X", "POST", url,
                 "--data-urlencode", f"data={query}"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode != 0:
                log.warning(f"curl failed for {url}")
                continue
            parsed = json.loads(result.stdout)
            if parsed.get("elements") is not None:
                data = parsed
                break
        except Exception as e:
            log.warning(f"Failed with {url}: {e}")
            time.sleep(5)
    if data is None:
        raise RuntimeError("All Overpass mirrors failed")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data))
    time.sleep(2)
    return data


# ---------------------------------------------------------------------------
# Fetch 1 - Railway line (named ways: Strohgäubahn)
# ---------------------------------------------------------------------------

def process_railway(data: dict) -> gpd.GeoDataFrame:
    nodes = {}
    ways = []

    for el in data["elements"]:
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
        elif el["type"] == "way":
            ways.append({
                "way_id": el["id"],
                "tags": el.get("tags", {}),
                "node_ids": el.get("nodes", []),
            })

    # Filter: exclude tunnels, service tracks, museum-only sections
    filtered = [
        w for w in ways
        if w["tags"].get("tunnel") != "yes"
        and "service" not in w["tags"]
        and "Museumsbahn" not in w["tags"].get("name", "")
    ]
    log.info(f"Ways after filter: {len(filtered)} of {len(ways)} total")

    # Build lookup: last_node -> way, first_node -> way
    last_node_map = {}   # last node id  -> way
    first_node_map = {}  # first node id -> way
    for w in filtered:
        first_node_map.setdefault(w["node_ids"][0], []).append(w)
        last_node_map.setdefault(w["node_ids"][-1], []).append(w)

    # Find starting way: its first node is not the last node of any other way
    start_way = None
    for w in filtered:
        first = w["node_ids"][0]
        predecessors = last_node_map.get(first, [])
        if all(p["way_id"] == w["way_id"] for p in predecessors):
            start_way = w
            break

    if start_way is None:
        start_way = filtered[0]
        log.warning("Could not determine unique start way; using first filtered way")

    # Chain ways into continuous sequence
    used = {start_way["way_id"]}
    chain = list(start_way["node_ids"])

    while True:
        tail = chain[-1]
        found = False
        for w in filtered:
            if w["way_id"] in used:
                continue
            if w["node_ids"][0] == tail:
                chain.extend(w["node_ids"][1:])
                used.add(w["way_id"])
                found = True
                break
            elif w["node_ids"][-1] == tail:
                reversed_nodes = list(reversed(w["node_ids"]))
                chain.extend(reversed_nodes[1:])
                used.add(w["way_id"])
                found = True
                break
        if not found:
            unused = [w for w in filtered if w["way_id"] not in used]
            if unused:
                gap_coord = nodes.get(tail, ("?", "?"))
                log.warning(
                    f"Gap at node {tail} ({gap_coord}); "
                    f"{len(unused)} ways remain unchained"
                )
            break

    coords = [nodes[nid] for nid in chain if nid in nodes]
    log.info(f"Line built from {len(coords)} nodes, {len(used)} ways chained")

    line = LineString(coords)
    gdf = gpd.GeoDataFrame(geometry=[line], crs="EPSG:4326")
    gdf = gdf.to_crs(25832)
    assert gdf.crs.to_epsg() == 25832, f"CRS wrong: {gdf.crs}"

    full_km = gdf.geometry.iloc[0].length / 1000
    log.info(f"Full chained line length: {full_km:.2f} km")

    # Trim at Heimerdingen station - the RB47 terminus.
    # The reference shapefile (VVS GTFS) confirms the route is ~16.25 km.
    full_line = gdf.geometry.iloc[0]
    # Heimerdingen station approx EPSG:25832 position
    t = pyproj.Transformer.from_crs(4326, 25832, always_xy=True)
    heim_x, heim_y = t.transform(8.98620, 48.85152)  # Heimerdingen station
    heim_chainage = full_line.project(Point(heim_x, heim_y))
    # Trim exactly at the station. Any stub segment past the last
    # full 200 m window is dropped by script 02 (< 50 m filter).
    trim_end = heim_chainage
    trimmed = substring(full_line, 0, trim_end)
    log.info(f"Trimmed at Heimerdingen (chainage {heim_chainage:.0f}m): {trimmed.length/1000:.2f} km")
    gdf = gpd.GeoDataFrame(geometry=[trimmed], crs=gdf.crs)

    length_km = gdf.geometry.iloc[0].length / 1000
    log.info(f"Final line length: {length_km:.2f} km")
    if length_km < 15 or length_km > 22:
        log.warning(f"Length {length_km:.2f} km outside expected range (15-22 km)")

    return gdf


# ---------------------------------------------------------------------------
# Fetch 2 - Building footprints (centroids via out center)
# ---------------------------------------------------------------------------

def process_buildings(data: dict) -> gpd.GeoDataFrame:
    points = []
    ids = []
    for el in data["elements"]:
        center = el.get("center")
        if center is None:
            continue
        points.append(Point(center["lon"], center["lat"]))
        ids.append(str(el["id"]))

    gdf = gpd.GeoDataFrame({"building_id": ids}, geometry=points, crs="EPSG:4326")
    gdf = gdf.to_crs(25832)
    assert gdf.crs.to_epsg() == 25832, f"CRS wrong: {gdf.crs}"

    log.info(f"Buildings extracted: {len(gdf)}")
    return gdf


# ---------------------------------------------------------------------------
# Fetch 3 - Station and halt nodes
# ---------------------------------------------------------------------------

def process_stations(data: dict) -> gpd.GeoDataFrame:
    rows = []
    for el in data["elements"]:
        if el["type"] != "node":
            continue
        tags = el.get("tags", {})
        rows.append({
            "station_id": str(el["id"]),
            "name": tags.get("name", ""),
            "railway_type": tags.get("railway", ""),
            "geometry": Point(el["lon"], el["lat"]),
        })

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    gdf = gdf.to_crs(25832)
    assert gdf.crs.to_epsg() == 25832, f"CRS wrong: {gdf.crs}"

    log.info(f"Stations/halts extracted: {len(gdf)}")
    for _, row in gdf.iterrows():
        log.info(f"  {row['name']} ({row['railway_type']})")

    return gdf


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    PROCESSED.mkdir(parents=True, exist_ok=True)

    # --- Fetch 1: Railway infrastructure ways named "Strohgäubahn" ---
    railway_query = """\
[out:json][timeout:120];
way["railway"="rail"]["name"~"Strohgäubahn"](48.82,8.88,48.95,9.15);
(._;>;);
out body;"""
    railway_data = fetch_overpass(railway_query, RAW / "osm" / "strohgaeu_named_ways.json")
    line_gdf = process_railway(railway_data)
    line_path = PROCESSED / "strohgaeu_line.geojson"
    line_gdf.to_file(line_path, driver="GeoJSON")
    log.info(f"Output saved to: {line_path}")

    # --- Fetch 2: Buildings ---
    buildings_query = """\
[out:json][timeout:90];
(
  way["building"](48.82,8.88,48.95,9.15);
  relation["building"]["type"="multipolygon"](48.82,8.88,48.95,9.15);
);
out center;"""
    buildings_data = fetch_overpass(buildings_query, RAW / "osm" / "buildings_corridor.json")
    buildings_gdf = process_buildings(buildings_data)
    buildings_path = PROCESSED / "buildings.geojson"
    buildings_gdf.to_file(buildings_path, driver="GeoJSON")
    log.info(f"Output saved to: {buildings_path}")

    # --- Fetch 3: Stations ---
    stations_query = """\
[out:json][timeout:30];
(
  node["railway"~"station|halt"](48.82,8.88,48.95,9.15);
);
out body;"""
    stations_data = fetch_overpass(stations_query, RAW / "osm" / "stations_corridor.json")
    stations_gdf = process_stations(stations_data)
    # Filter to stations within 500m of the Strohgäubahn line
    line_geom = line_gdf.geometry.iloc[0]
    stations_gdf["dist_to_line"] = stations_gdf.geometry.distance(line_geom)
    n_before = len(stations_gdf)
    stations_gdf = stations_gdf[stations_gdf["dist_to_line"] <= 500].drop(columns=["dist_to_line"]).reset_index(drop=True)
    log.info(f"Stations filtered by proximity to line: {n_before} -> {len(stations_gdf)}")
    stations_path = PROCESSED / "stations.geojson"
    stations_gdf.to_file(stations_path, driver="GeoJSON")
    log.info(f"Output saved to: {stations_path}")

    # --- Fetch 4: Level crossings ---
    crossings_query = """\
[out:json][timeout:30];
(
  node["railway"="level_crossing"](48.82,8.88,48.95,9.15);
);
out body;"""
    crossings_data = fetch_overpass(crossings_query, RAW / "osm" / "crossings_corridor.json")
    crossing_points = []
    crossing_ids = []
    for el in crossings_data["elements"]:
        if el["type"] != "node":
            continue
        crossing_points.append(Point(el["lon"], el["lat"]))
        crossing_ids.append(str(el["id"]))
    crossings_gdf = gpd.GeoDataFrame(
        {"crossing_id": crossing_ids}, geometry=crossing_points, crs="EPSG:4326"
    )
    crossings_gdf = crossings_gdf.to_crs(25832)
    assert crossings_gdf.crs.to_epsg() == 25832, f"CRS wrong: {crossings_gdf.crs}"
    # Filter to crossings within 30m of the Strohgäubahn line
    crossings_gdf["dist_to_line"] = crossings_gdf.geometry.distance(line_geom)
    n_before_c = len(crossings_gdf)
    crossings_gdf = crossings_gdf[crossings_gdf["dist_to_line"] <= 30].drop(
        columns=["dist_to_line"]
    ).reset_index(drop=True)
    log.info(f"Level crossings filtered by proximity to line: {n_before_c} -> {len(crossings_gdf)}")
    crossings_path = PROCESSED / "crossings.geojson"
    crossings_gdf.to_file(crossings_path, driver="GeoJSON")
    log.info(f"Output saved to: {crossings_path}")

    # --- Final summary ---
    log.info(f"Line CRS: {line_gdf.crs}  |  Bounds: {line_gdf.total_bounds}")
    log.info(f"Buildings CRS: {buildings_gdf.crs}  |  Bounds: {buildings_gdf.total_bounds}")
    log.info(f"Stations CRS: {stations_gdf.crs}  |  Bounds: {stations_gdf.total_bounds}")
    log.info(f"Crossings CRS: {crossings_gdf.crs}  |  Count: {len(crossings_gdf)}")


if __name__ == "__main__":
    main()

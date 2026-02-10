#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional

import gpxpy
import requests
import time

from .geo import haversine_m, bbox_of_points, expand_bbox, extract_gpx_points
from .models import (
    FeatureCollection,
    Feature,
    FeatureProperties,
    PointGeometry,
)


OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def overpass_query_bbox(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> str:
    """
    Query for nodes, ways, and relations:
      - natural=peak
      - tourism=alpine_hut
    in bbox (S,W,N,E).
    Uses 'out center' to get center coordinates for ways and relations.
    """
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    return f"""
[out:json][timeout:25];
(
  node["natural"="peak"]({bbox});
  way["natural"="peak"]({bbox});
  relation["natural"="peak"]({bbox});
  node["tourism"="alpine_hut"]({bbox});
  way["tourism"="alpine_hut"]({bbox});
  relation["tourism"="alpine_hut"]({bbox});
);
out center;
"""


def fetch_osm_features(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float, user_agent: str
) -> List[Dict[str, Any]]:
    """Call Overpass and return the raw 'elements' list."""
    q = overpass_query_bbox(min_lon, min_lat, max_lon, max_lat)
    headers = {
        "User-Agent": user_agent,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                OVERPASS_URL, data=q.encode("utf-8"), headers=headers, timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("elements", [])
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                print(f"[WARN] Overpass request failed (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(2 ** attempt)  # exponential backoff
            else:
                print(f"[ERROR] Overpass request failed after {max_retries} attempts: {e}")
    return []


@dataclass
class FilterConfig:
    distance_m: float = 500.0  # keep OSM features within this distance to any GPX point


def map_osm_element_to_feature(elem: Dict[str, Any]) -> Optional[Feature]:
    """
    Map an Overpass element (node, way, or relation) to a Feature.
    Supports peaks and alpine huts. Returns None for other kinds.
    For ways and relations, uses the center coordinates returned by 'out center'.
    """
    elem_type = elem.get("type")
    if elem_type not in ("node", "way", "relation"):
        return None

    # For nodes, coordinates are directly in lon/lat fields
    # For ways and relations, coordinates are in the center field
    if elem_type == "node":
        lon = elem.get("lon")
        lat = elem.get("lat")
    else:  # way or relation
        center = elem.get("center")
        if not center:
            return None
        lon = center.get("lon")
        lat = center.get("lat")

    if lon is None or lat is None:
        return None

    tags = elem.get("tags", {}) or {}
    if tags.get("natural") == "peak":
        kind = "peak"
    elif tags.get("tourism") == "alpine_hut":
        kind = "hut"
    else:
        return None

    name = tags.get("name") or (
        tags.get("ref") or f"{kind.capitalize()} {elem.get('id')}"
    )
    ele_m = None
    if "ele" in tags:
        try:
            ele_m = float(str(tags["ele"]).replace("m", "").strip())
        except Exception:
            ele_m = None
    source_id = f"{elem_type}/{elem.get('id')}"
    return Feature(
        geometry=PointGeometry(coordinates=[float(lon), float(lat)]),
        id=f"osm:{source_id}",
        properties=FeatureProperties(
            name=name,
            kind=kind,  # "peak" or "hut"
            ele_m=ele_m,
            source="osm",
            source_id=source_id,
            meta={"osm_tags": [f"{k}={v}" for k, v in sorted(tags.items())]},
        ),
    )


def filter_by_proximity(
    features: List[Feature],
    gpx_points: List[Tuple[float, float]],
    max_distance_m: float,
) -> List[Feature]:
    """Keep features where min distance to ANY GPX point <= max_distance_m."""
    if not features or not gpx_points:
        return []
    kept: List[Feature] = []
    for feat in features:
        lon, lat = feat.geometry.coordinates
        mind = min(haversine_m(lon, lat, glon, glat) for glon, glat in gpx_points)
        if mind <= max_distance_m:
            kept.append(feat)
    return kept


# ---------------------------
# Main flow (synchronous)
# ---------------------------


def gpx_to_features(
    gpx_path: str,
    margin_km: float = 2.0,
    distance_m: float = 500.0,
    user_agent: str = "waykit/1.0",
) -> FeatureCollection:
    # Parse GPX
    with open(gpx_path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    gpx_points = extract_gpx_points(gpx)
    if not gpx_points:
        return FeatureCollection(features=[])

    # Compute bbox + margin
    b = bbox_of_points(gpx_points)
    if b is None:
        return FeatureCollection(features=[])

    min_lon, min_lat, max_lon, max_lat = expand_bbox(b, margin_km)

    # Query OSM
    elements = fetch_osm_features(
        min_lon, min_lat, max_lon, max_lat, user_agent=user_agent
    )

    # Convert to Features (peaks and huts)
    osm_features = []
    for e in elements:
        f = map_osm_element_to_feature(e)
        if f is not None:
            osm_features.append(f)

    # Proximity filter
    kept = filter_by_proximity(osm_features, gpx_points, distance_m)

    return FeatureCollection(features=kept)


def gpx_files_to_features(
    gpx_paths: List[str],
    margin_km: float = 2.0,
    distance_m: float = 500.0,
    user_agent: str = "waykit/1.0",
) -> FeatureCollection:
    """
    Process multiple GPX files and return nearby features.
    Combines all points from all GPX files, computes a single bbox,
    and makes a single API call to Overpass.
    """
    all_gpx_points: List[Tuple[float, float]] = []

    # Parse all GPX files and collect points
    for gpx_path in gpx_paths:
        with open(gpx_path, "r", encoding="utf-8") as f:
            gpx = gpxpy.parse(f)
        points = extract_gpx_points(gpx)
        all_gpx_points.extend(points)

    if not all_gpx_points:
        return FeatureCollection(features=[])

    # Compute bbox + margin for all points
    b = bbox_of_points(all_gpx_points)
    if b is None:
        return FeatureCollection(features=[])

    min_lon, min_lat, max_lon, max_lat = expand_bbox(b, margin_km)

    # Query OSM once for the combined bbox
    elements = fetch_osm_features(
        min_lon, min_lat, max_lon, max_lat, user_agent=user_agent
    )

    # Convert to Features (peaks and huts)
    osm_features = []
    for e in elements:
        f = map_osm_element_to_feature(e)
        if f is not None:
            osm_features.append(f)

    # Proximity filter against all GPX points
    kept = filter_by_proximity(osm_features, all_gpx_points, distance_m)

    return FeatureCollection(features=kept)

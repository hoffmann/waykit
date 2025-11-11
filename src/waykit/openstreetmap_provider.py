#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple, Dict, Any, Optional

import requests
import gpxpy

from .models import (
    FeatureCollection,
    Feature,
    FeatureProperties,
    PointGeometry,
)

# ---------------------------
# Helpers
# ---------------------------


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters using the haversine formula."""
    from math import radians, sin, cos, asin, sqrt

    R = 6371000.0  # meters
    lon1, lat1, lon2, lat2 = map(radians, (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


def bbox_of_points(
    points: Iterable[Tuple[float, float]],
) -> Optional[Tuple[float, float, float, float]]:
    """Return (min_lon, min_lat, max_lon, max_lat) or None if empty."""
    min_lon = min_lat = float("inf")
    max_lon = max_lat = float("-inf")
    seen = False
    for lon, lat in points:
        seen = True
        if lon < min_lon:
            min_lon = lon
        if lat < min_lat:
            min_lat = lat
        if lon > max_lon:
            max_lon = lon
        if lat > max_lat:
            max_lat = lat
    return (min_lon, min_lat, max_lon, max_lat) if seen else None


def expand_bbox(
    b: Tuple[float, float, float, float], margin_km: float = 1.0
) -> Tuple[float, float, float, float]:
    """Expand bbox by ~margin_km (default 1 km). Rough degrees conversion near mid-lat."""
    min_lon, min_lat, max_lon, max_lat = b
    mid_lat = (min_lat + max_lat) / 2.0
    # ~1° lat ≈ 111 km; 1° lon ≈ 111 km * cos(lat)
    deg_lat = margin_km / 111.0
    from math import cos, radians

    deg_lon = margin_km / (111.0 * max(0.1, cos(radians(abs(mid_lat)))))
    return (min_lon - deg_lon, min_lat - deg_lat, max_lon + deg_lon, max_lat + deg_lat)


def extract_gpx_points(gpx: gpxpy.gpx.GPX) -> List[Tuple[float, float]]:
    """Collect all route & track points as (lon, lat)."""
    pts: List[Tuple[float, float]] = []

    for route in gpx.routes:
        for p in route.points:
            pts.append((p.longitude, p.latitude))

    for track in gpx.tracks:
        for seg in track.segments:
            for p in seg.points:
                pts.append((p.longitude, p.latitude))

    # If you want to include waypoints, uncomment:
    # for w in gpx.waypoints:
    #     pts.append((w.longitude, w.latitude))

    return pts


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
    try:
        resp = requests.post(
            OVERPASS_URL, data=q.encode("utf-8"), headers=headers, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("elements", [])
    except requests.RequestException as e:
        # In production you might log this or raise a custom error
        print(f"[ERROR] Overpass request failed: {e}")
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

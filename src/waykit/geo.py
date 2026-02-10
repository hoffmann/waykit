"""geo.py

Shared geographic utilities used by both the live Overpass provider and the
cached JSONL provider.
"""

from __future__ import annotations

from math import radians, sin, cos, asin, sqrt
from typing import Iterable, List, Optional, Tuple

import gpxpy


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters using the haversine formula."""
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

    return pts

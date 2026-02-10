"""cached_provider.py

Offline provider that resolves POIs near a GPX track from a bundled
JSONL export of OpenStreetMap data (e.g. alpine huts).

The JSONL file is loaded once and indexed into a :class:`SquareGridIndex`
for fast spatial pre-filtering.  Candidate features are then refined with
an exact haversine distance check.

Usage::

    from waykit.cached_provider import gpx_to_features

    fc = gpx_to_features("track.gpx", distance_m=500)
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import gpxpy

from .grid_index import SquareGridIndex
from .models import (
    Feature,
    FeatureCollection,
    FeatureProperties,
    PointGeometry,
)
from .geo import extract_gpx_points, haversine_m

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------

# Projection origin – central Alps.  Must stay constant so that cell IDs
# remain stable across runs.
_ORIGIN_LAT = 47.0
_ORIGIN_LON = 10.0

# Grid cell size in meters.  200 m is a good balance between index
# granularity and bucket count for hiking-scale queries.
_CELL_SIZE_M = 200.0

# Lazy-loaded singleton index.
_INDEX: Optional[SquareGridIndex[Feature]] = None


# ------------------------------------------------------------
# JSONL row → Feature
# ------------------------------------------------------------

def jsonl_row_to_feature(row: Dict[str, Any]) -> Feature:
    """Convert a single JSONL row from the cached OSM export to a Feature.

    Expected row keys: ``uri``, ``lat``, ``lon``, ``name``, ``ele``,
    ``type``, ``url``, ``tags``.
    """
    tags = row.get("tags", {}) or {}
    kind = "hut" if row.get("type") == "alpine_hut" else "other"

    ele_m: Optional[float] = None
    raw_ele = row.get("ele")
    if raw_ele is not None:
        try:
            ele_m = float(str(raw_ele).replace("m", "").strip())
        except (ValueError, TypeError):
            ele_m = None

    meta: Dict[str, Any] = {}
    if tags:
        meta["osm_tags"] = [f"{k}={v}" for k, v in sorted(tags.items())]
    url = row.get("url")
    if url:
        meta["url"] = url

    uri = row.get("uri", "")
    # uri looks like "osm:node:12345" — convert to source_id "node:12345"
    source_id = uri.removeprefix("osm:")

    return Feature(
        id=uri,
        geometry=PointGeometry(coordinates=[float(row["lon"]), float(row["lat"])]),
        properties=FeatureProperties(
            name=row.get("name") or f"Hut {source_id}",
            kind=kind,
            ele_m=ele_m,
            source="osm",
            source_id=source_id,
            meta=meta,
        ),
    )


# ------------------------------------------------------------
# Index loading
# ------------------------------------------------------------

def load_index(data_path: Optional[Path] = None) -> SquareGridIndex[Feature]:
    """Load the JSONL data file and build a spatial index.

    Args:
        data_path: Explicit path to a JSONL file.  When *None* (the default),
            the bundled ``data/alps-huts.jsonl`` inside the package is used.

    Returns:
        A populated :class:`SquareGridIndex` mapping grid cells to
        :class:`Feature` objects.
    """
    if data_path is not None:
        text = data_path.read_text(encoding="utf-8")
    else:
        ref = resources.files("waykit").joinpath("data/alps-huts.jsonl")
        text = ref.read_text(encoding="utf-8")

    index: SquareGridIndex[Feature] = SquareGridIndex(
        cell_size_m=_CELL_SIZE_M,
        origin_lat=_ORIGIN_LAT,
        origin_lon=_ORIGIN_LON,
    )
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        feature = jsonl_row_to_feature(row)
        lat = row["lat"]
        lon = row["lon"]
        index.insert(lat, lon, feature)

    return index


def get_index() -> SquareGridIndex[Feature]:
    """Return the lazily-loaded singleton index (bundled data)."""
    global _INDEX
    if _INDEX is None:
        _INDEX = load_index()
    return _INDEX


# ------------------------------------------------------------
# Query helpers
# ------------------------------------------------------------

def _collect_nearby_features(
    gpx_points: List[Tuple[float, float]],
    index: SquareGridIndex[Feature],
    distance_m: float,
) -> List[Feature]:
    """Return deduplicated features within *distance_m* of any GPX point.

    Uses the grid index as a pre-filter, then applies an exact haversine
    distance check.

    Args:
        gpx_points: List of ``(lon, lat)`` tuples from the GPX track.
        index: Populated spatial index.
        distance_m: Maximum distance in meters from any GPX point.

    Returns:
        Deduplicated list of nearby :class:`Feature` objects.
    """
    seen_ids: set[str] = set()
    kept: List[Feature] = []

    for glon, glat in gpx_points:
        # Grid index expects (lat, lon)
        candidates = index.candidates_near(glat, glon, radius_m=distance_m)
        for feat in candidates:
            if feat.id in seen_ids:
                continue
            flon, flat = feat.geometry.coordinates
            if haversine_m(flon, flat, glon, glat) <= distance_m:
                seen_ids.add(feat.id)
                kept.append(feat)

    return kept


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------

def gpx_to_features(
    gpx_path: str,
    distance_m: float = 500.0,
    data_path: Optional[Path] = None,
) -> FeatureCollection:
    """Return cached features near a GPX track.

    Args:
        gpx_path: Path to a GPX file.
        distance_m: Maximum distance in meters from the track to keep
            a feature.
        data_path: Optional explicit JSONL data file.  Uses the bundled
            data when *None*.

    Returns:
        A :class:`FeatureCollection` of nearby features.
    """
    with open(gpx_path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    gpx_points = extract_gpx_points(gpx)
    if not gpx_points:
        return FeatureCollection(features=[])

    index = load_index(data_path) if data_path else get_index()
    kept = _collect_nearby_features(gpx_points, index, distance_m)
    return FeatureCollection(features=kept)


def gpx_files_to_features(
    gpx_paths: List[str],
    distance_m: float = 500.0,
    data_path: Optional[Path] = None,
) -> FeatureCollection:
    """Return cached features near multiple GPX tracks.

    Args:
        gpx_paths: Paths to GPX files.
        distance_m: Maximum distance in meters from any track point.
        data_path: Optional explicit JSONL data file.

    Returns:
        A :class:`FeatureCollection` of nearby features.
    """
    all_points: List[Tuple[float, float]] = []
    for gpx_path in gpx_paths:
        with open(gpx_path, "r", encoding="utf-8") as f:
            gpx = gpxpy.parse(f)
        all_points.extend(extract_gpx_points(gpx))

    if not all_points:
        return FeatureCollection(features=[])

    index = load_index(data_path) if data_path else get_index()
    kept = _collect_nearby_features(all_points, index, distance_m)
    return FeatureCollection(features=kept)

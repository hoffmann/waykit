"""
grid_index.py

Minimal square-grid spatial index for geographic data (GPX routes + POIs).

Design goals:
- no external dependencies
- deterministic grid cell IDs
- lowercase alphanumeric encoding only
- reversible cell IDs
- suitable for Alps-scale hiking applications

The index is *not* a precise distance matcher.
It is a very fast PRE-FILTER that finds candidate POIs.
After querying, you should still run an exact distance-to-route check.

Author intent:
This behaves like a lightweight geohash/H3 replacement aligned to meters.
"""

from __future__ import annotations
from dataclasses import dataclass
from math import cos, floor, radians
from typing import Dict, Iterable, List, Tuple, TypeVar, Generic

# ------------------------------------------------------------
# Earth model
# ------------------------------------------------------------

# Mean Earth radius (meters)
EARTH_RADIUS_M = 6371008.8


# ------------------------------------------------------------
# Simple local projection (lat/lon -> meters)
# ------------------------------------------------------------

@dataclass(frozen=True)
class Point:
    """Projected local coordinates in meters relative to an origin.

    Produced by :func:`project_local_m` using an equirectangular
    approximation.  Immutable (frozen dataclass) so it can be safely
    stored inside the grid index without risk of accidental mutation.

    Attributes:
        x: East-west displacement from origin in meters (east is positive).
        y: North-south displacement from origin in meters (north is positive).
    """
    x: float
    y: float


def project_local_m(lat: float, lon: float, lat0: float, lon0: float) -> Point:
    """Convert WGS84 lat/lon to local meter coordinates via equirectangular projection.

    Uses a tangent-plane approximation where one degree of latitude is always
    ``EARTH_RADIUS_M * radians(1)`` meters and one degree of longitude is
    scaled by ``cos(lat0)`` to account for meridian convergence.

    Args:
        lat: Latitude of the point to project (decimal degrees).
        lon: Longitude of the point to project (decimal degrees).
        lat0: Latitude of the projection origin (decimal degrees).
        lon0: Longitude of the projection origin (decimal degrees).

    Returns:
        A :class:`Point` with *x* (east) and *y* (north) offsets in meters
        relative to ``(lat0, lon0)``.

    Note:
        Accuracy is very good for regional areas like the Alps (hundreds of
        km).  Not suitable for continent or global scale.
    """
    lat_r = radians(lat)
    lon_r = radians(lon)
    lat0_r = radians(lat0)
    lon0_r = radians(lon0)

    x = EARTH_RADIUS_M * (lon_r - lon0_r) * cos(lat0_r)
    y = EARTH_RADIUS_M * (lat_r - lat0_r)
    return Point(x, y)


# ------------------------------------------------------------
# Base36 encoding (lowercase alphanumeric only)
# ------------------------------------------------------------

ALPHABET36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def base36_encode(n: int) -> str:
    """Encode a non-negative integer to a lowercase base-36 string.

    Uses the alphabet ``0-9a-z`` (36 characters).  The result contains only
    lowercase alphanumeric characters, making it safe for filenames, URLs,
    and cell ID composition.

    Args:
        n: Non-negative integer to encode.

    Returns:
        Lowercase base-36 representation (e.g. ``0``, ``a``, ``10``).

    Raises:
        ValueError: If *n* is negative.
    """
    if n < 0:
        raise ValueError("base36 only supports non-negative integers")
    if n == 0:
        return "0"

    chars = []
    while n:
        n, r = divmod(n, 36)
        chars.append(ALPHABET36[r])
    return "".join(reversed(chars))


def base36_decode(s: str) -> int:
    """Decode a lowercase base-36 string back to an integer.

    Inverse of :func:`base36_encode`.

    Args:
        s: Base-36 encoded string (lowercase alphanumeric).

    Returns:
        The decoded non-negative integer.
    """
    n = 0
    for c in s:
        n = n * 36 + ALPHABET36.index(c)
    return n


# ------------------------------------------------------------
# ZigZag encoding (signed integer -> unsigned integer)
# Removes negative numbers while keeping reversibility
# ------------------------------------------------------------

def zigzag_encode(n: int) -> int:
    """Map a signed integer to a non-negative integer using ZigZag encoding.

    ZigZag maps signed values to unsigned ones so that values with small
    absolute magnitude have small encoded values, which in turn produce
    shorter base-36 strings::

        0 -> 0,  -1 -> 1,  1 -> 2,  -2 -> 3,  2 -> 4, ...

    Args:
        n: Signed integer (may be negative).

    Returns:
        Non-negative integer suitable for :func:`base36_encode`.
    """
    return (n << 1) ^ (n >> 63)


def zigzag_decode(n: int) -> int:
    """Decode a ZigZag-encoded non-negative integer back to a signed integer.

    Inverse of :func:`zigzag_encode`.

    Args:
        n: Non-negative ZigZag-encoded integer.

    Returns:
        Original signed integer.
    """
    return (n >> 1) ^ -(n & 1)


# ------------------------------------------------------------
# Cell ID encoding
# ------------------------------------------------------------

def encode_cell_id(cx: int, cy: int) -> str:
    """Convert integer grid coordinates into a compact, reversible cell ID string.

    The encoding pipeline is::

        signed int  ->  zigzag (unsigned)  ->  base36 string

    The two encoded components are length-prefixed and concatenated::

        <len(cx_b36)><cx_b36><len(cy_b36)><cy_b36>

    The result is a short, lowercase alphanumeric string with no separators,
    safe for use in filenames, URLs, and dictionary keys.

    Args:
        cx: Integer grid column (may be negative).
        cy: Integer grid row (may be negative).

    Returns:
        Compact alphanumeric cell ID (e.g. ``"1010"`` for the origin cell).
    """
    sx = base36_encode(zigzag_encode(cx))
    sy = base36_encode(zigzag_encode(cy))
    return f"{base36_encode(len(sx))}{sx}{base36_encode(len(sy))}{sy}"


def decode_cell_id(cell_id: str) -> Tuple[int, int]:
    """Decode a cell ID string back into integer grid coordinates ``(cx, cy)``.

    Inverse of :func:`encode_cell_id`.

    Args:
        cell_id: Alphanumeric cell ID produced by :func:`encode_cell_id`.

    Returns:
        Tuple of ``(cx, cy)`` signed grid coordinates.
    """
    i = 0

    lx = base36_decode(cell_id[i])
    i += 1
    sx = cell_id[i:i + lx]
    i += lx

    ly = base36_decode(cell_id[i])
    i += 1
    sy = cell_id[i:i + ly]

    cx = zigzag_decode(base36_decode(sx))
    cy = zigzag_decode(base36_decode(sy))
    return cx, cy


# ------------------------------------------------------------
# Grid math
# ------------------------------------------------------------

def cell_id_from_point(pt: Point, cell_size_m: float) -> Tuple[int, int]:
    """Compute the integer grid cell ``(cx, cy)`` that contains a projected point.

    Each axis is divided into uniform cells of *cell_size_m* meters.
    Cell indices are computed with ``floor(coordinate / cell_size_m)``, so
    the origin ``(0, 0)`` always falls in cell ``(0, 0)``.

    Args:
        pt: Projected point in meters (from :func:`project_local_m`).
        cell_size_m: Side length of each square grid cell in meters.

    Returns:
        Tuple of ``(cx, cy)`` integer cell coordinates.
    """
    return (int(floor(pt.x / cell_size_m)), int(floor(pt.y / cell_size_m)))


# ------------------------------------------------------------
# Spatial index
# ------------------------------------------------------------

T = TypeVar("T")


class SquareGridIndex(Generic[T]):
    """Minimal spatial index that buckets objects into a uniform square grid.

    Objects are inserted with their WGS-84 lat/lon position.  Internally each
    position is projected to local meters via :func:`project_local_m` and
    assigned to a grid cell.  Queries return *candidate* objects whose cells
    fall within a square neighbourhood of the query point.

    This is a **pre-filter**, not a precise distance index.  After calling
    :meth:`candidates_near` you should still perform an exact distance check
    (e.g. haversine) on the returned candidates.

    The index is generic over the item type ``T`` -- you can store any object
    (POI dicts, Feature models, plain strings, etc.).

    Example::

        idx = SquareGridIndex[str](cell_size_m=200, origin_lat=47.0, origin_lon=10.0)
        idx.insert(47.123, 10.456, "Rifugio Testa")
        hits = idx.candidates_near(47.124, 10.457, radius_m=500)
    """

    def __init__(self, cell_size_m: float, origin_lat: float, origin_lon: float):
        """Create a new grid index.

        Args:
            cell_size_m: Side length of each square grid cell in meters.
                Recommended 100-300 for hiking-scale applications.
            origin_lat: Latitude of the projection origin (decimal degrees).
                Must remain constant across runs to keep cell IDs stable.
            origin_lon: Longitude of the projection origin (decimal degrees).
                Must remain constant across runs to keep cell IDs stable.
        """
        self.cell_size_m = float(cell_size_m)
        self.origin_lat = float(origin_lat)
        self.origin_lon = float(origin_lon)

        # maps (cx,cy) -> [(Point,item), ...]
        self._grid: Dict[Tuple[int, int], List[Tuple[Point, T]]] = {}

    # --------------------------------------------------------

    def insert(self, lat: float, lon: float, item: T) -> str:
        """Insert an object at a geographic position.

        Args:
            lat: Latitude in decimal degrees.
            lon: Longitude in decimal degrees.
            item: The object to store.

        Returns:
            The encoded cell ID string for the cell the object was placed in.
        """
        pt = project_local_m(lat, lon, self.origin_lat, self.origin_lon)
        cx, cy = cell_id_from_point(pt, self.cell_size_m)
        self._grid.setdefault((cx, cy), []).append((pt, item))
        return encode_cell_id(cx, cy)

    # --------------------------------------------------------

    def bulk_insert(self, rows: Iterable[Tuple[float, float, T]]) -> None:
        """Insert multiple objects at once.

        Args:
            rows: Iterable of ``(lat, lon, item)`` tuples.
        """
        for lat, lon, item in rows:
            self.insert(lat, lon, item)

    # --------------------------------------------------------

    def candidates_near(self, lat: float, lon: float, radius_m: float) -> List[T]:
        """Return candidate objects within a square neighbourhood of a point.

        Searches all grid cells that could overlap with a circle of the given
        radius.  Because the search region is a square (not a circle), the
        result may include objects slightly beyond *radius_m* -- always apply
        an exact distance check on the returned candidates.

        Args:
            lat: Query latitude in decimal degrees.
            lon: Query longitude in decimal degrees.
            radius_m: Search radius in meters.

        Returns:
            List of candidate items (may contain false positives, never
            false negatives for the covered cells).
        """
        pt = project_local_m(lat, lon, self.origin_lat, self.origin_lon)
        cx, cy = cell_id_from_point(pt, self.cell_size_m)

        # how many cells outward must be searched
        r = int((radius_m + self.cell_size_m - 1) // self.cell_size_m)

        out: List[T] = []
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                bucket = self._grid.get((cx + dx, cy + dy))
                if not bucket:
                    continue
                out.extend(item for _pt, item in bucket)

        return out

    # --------------------------------------------------------

    def buckets(self) -> int:
        """Number of non-empty grid cells."""
        return len(self._grid)

    def __len__(self) -> int:
        """Total number of stored objects."""
        return sum(len(v) for v in self._grid.values())


# ------------------------------------------------------------
# Neighbor cell utilities
# ------------------------------------------------------------

def neighbors_square(cell_id: str, r: int) -> List[str]:
    """Return cell IDs in a square neighbourhood of a given cell.

    Includes the center cell itself.  The total number of returned cells
    is ``(2*r + 1) ** 2``:

    - ``r=0`` -> 1 cell (self only)
    - ``r=1`` -> 9 cells
    - ``r=2`` -> 25 cells

    Args:
        cell_id: Encoded cell ID (from :func:`encode_cell_id` or
            :meth:`SquareGridIndex.insert`).
        r: Radius in grid cells (non-negative integer).

    Returns:
        List of encoded cell ID strings covering the square neighbourhood.
    """
    cx, cy = decode_cell_id(cell_id)
    out = []
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            out.append(encode_cell_id(cx + dx, cy + dy))
    return out
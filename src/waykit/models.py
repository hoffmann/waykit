from __future__ import annotations

from typing import Literal, Union, List, Dict, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict

Scalar = Union[int, float, str]
ScalarOrList = Union[Scalar, List[Scalar]]

Kind = Literal["hut", "peak", "poi", "other"]


class PointGeometry(BaseModel):
    """RFC 7946-compatible 2D Point geometry."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["Point"] = "Point"
    coordinates: List[float] = Field(..., description="[lon, lat]")

    @field_validator("coordinates")
    @classmethod
    def validate_coords(cls, v: List[float]) -> List[float]:
        if len(v) != 2:
            raise ValueError("Point must have exactly 2 coordinates: [lon, lat].")
        lon, lat = v
        if not (-180.0 <= lon <= 180.0):
            raise ValueError("Longitude must be in [-180, 180].")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError("Latitude must be in [-90, 90].")
        return v


class FeatureProperties(BaseModel):
    """Minimal, stable properties structure."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    name: str
    kind: Kind
    ele_m: Optional[float] = Field(
        None, description="Elevation in meters. Omit if unknown."
    )
    # Raw identifier from the original data source, used for traceability or
    # re-fetching upstream data.
    source: str = Field(..., description="e.g. 'osm', 'swisstopo', 'custom'")
    source_id: str = Field(..., description="Stable identifier from the source")
    meta: Dict[str, ScalarOrList] = Field(default_factory=dict)


class Feature(BaseModel):
    """A single GeoJSON Feature."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["Feature"] = "Feature"
    # Global, stable identifier within the dataset — can be used for
    # deduplication, merging, and cross-referencing across sources.
    id: str = Field(..., description="Globally unique id, e.g. 'osm:node/12345'")
    geometry: PointGeometry
    properties: FeatureProperties


class FeatureCollection(BaseModel):
    """A GeoJSON FeatureCollection."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[Feature] = Field(default_factory=list)

    def by_kind(self, kind: Kind) -> List[Feature]:
        """Convenience helper to filter by kind."""
        return [f for f in self.features if f.properties.kind == kind]
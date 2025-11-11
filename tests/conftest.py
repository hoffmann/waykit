# conftest.py
import pytest
from waykit.models import (
    PointGeometry,
    FeatureProperties,
    Feature,
    FeatureCollection,
)

@pytest.fixture
def hut_feature() -> Feature:
    return Feature(
        id="osm:node/12345",
        geometry=PointGeometry(coordinates=[10.12345, 46.78901]),
        properties=FeatureProperties(
            name="Rifugio Testa",
            kind="hut",
            ele_m=2260,
            source="osm",
            source_id="node/12345",
            meta={"beds": 32, "services": ["meals", "booking"]},
        ),
    )

@pytest.fixture
def peak_feature() -> Feature:
    return Feature(
        id="swisstopo:spotheight:987654",
        geometry=PointGeometry(coordinates=[8.123, 46.987]),
        properties=FeatureProperties(
            name="Piz Example",
            kind="peak",
            ele_m=3187,
            source="swisstopo",
            source_id="spotheight:987654",
            meta={"prominence_m": 420, "isolation_km": 3.2},
        ),
    )

@pytest.fixture
def poi_feature() -> Feature:
    return Feature(
        id="custom:poi-001",
        geometry=PointGeometry(coordinates=[11.2222, 47.3333]),
        properties=FeatureProperties(
            name="Water Source at Alp Meadow",
            kind="poi",
            ele_m=1640,
            source="custom",
            source_id="poi-001",
            meta={"type": "spring", "reliability": "seasonal"},
        ),
    )

@pytest.fixture
def feature_collection(hut_feature, peak_feature, poi_feature) -> FeatureCollection:
    return FeatureCollection(features=[hut_feature, peak_feature, poi_feature])
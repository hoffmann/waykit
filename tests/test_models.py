# test_models.py
import json
import pytest
from pydantic import ValidationError
from waykit.models import (
    PointGeometry,
    FeatureProperties,
    Feature,
    FeatureCollection,
)

def test_create_feature_valid(hut_feature: Feature):
    assert hut_feature.type == "Feature"
    assert hut_feature.geometry.type == "Point"
    assert hut_feature.geometry.coordinates == [10.12345, 46.78901]
    assert hut_feature.properties.name == "Rifugio Testa"
    assert hut_feature.properties.kind == "hut"
    assert hut_feature.properties.schema_version == "1.0"

def test_featurecollection_round_trip(feature_collection: FeatureCollection):
    data = feature_collection.model_dump()
    fc2 = FeatureCollection.model_validate(data)
    assert len(fc2.features) == 3
    assert fc2.features[0].id == feature_collection.features[0].id

def test_2d_coordinates_enforced():
    # 3D should fail
    with pytest.raises(ValidationError):
        PointGeometry(coordinates=[10.0, 45.0, 1000.0])
    # 1D should fail
    with pytest.raises(ValidationError):
        PointGeometry(coordinates=[10.0])

def test_lon_lat_bounds_validation():
    with pytest.raises(ValidationError):
        PointGeometry(coordinates=[181.0, 45.0])  # invalid lon
    with pytest.raises(ValidationError):
        PointGeometry(coordinates=[10.0, -95.0])  # invalid lat
    # valid edges
    PointGeometry(coordinates=[-180.0, -90.0])
    PointGeometry(coordinates=[180.0, 90.0])

def test_meta_accepts_scalar_and_list():
    props = FeatureProperties(
        name="Test POI",
        kind="poi",
        source="custom",
        source_id="x1",
        meta={"a": 1, "b": "str", "c": [1, 2, 3], "d": ["x", "y"]},
    )
    assert props.meta["a"] == 1
    assert props.meta["c"] == [1, 2, 3]

def test_missing_elevation_allowed():
    f = Feature(
        id="custom:no-ele",
        geometry=PointGeometry(coordinates=[12.0, 47.0]),
        properties=FeatureProperties(
            name="No Elevation",
            kind="other",
            ele_m=None,
            source="custom",
            source_id="no-ele",
        ),
    )
    assert f.properties.ele_m is None

def test_extra_fields_forbidden():
    # Extra field in geometry
    with pytest.raises(ValidationError):
        PointGeometry(coordinates=[10.0, 45.0], extra_field=1)  # type: ignore

    # Extra field in properties
    with pytest.raises(ValidationError):
        FeatureProperties(
            name="X",
            kind="poi",
            source="s",
            source_id="id",
            meta={},
            unexpected="nope",  # type: ignore
        )

    # Extra field in Feature
    with pytest.raises(ValidationError):
        Feature(
            id="bad:1",
            geometry=PointGeometry(coordinates=[10.0, 45.0]),
            properties=FeatureProperties(
                name="X", kind="poi", source="s", source_id="id"
            ),
            bogus=True,  # type: ignore
        )

def test_by_kind_filtering(feature_collection: FeatureCollection):
    huts = feature_collection.by_kind("hut")
    peaks = feature_collection.by_kind("peak")
    assert len(huts) == 1
    assert all(f.properties.kind == "hut" for f in huts)
    assert len(peaks) == 1
    assert all(f.properties.kind == "peak" for f in peaks)

def test_model_dump_json_and_validate(feature_collection: FeatureCollection):
    json_str = feature_collection.model_dump_json(indent=2)
    assert '"FeatureCollection"' in json_str
    fc2 = FeatureCollection.model_validate_json(json_str)
    assert len(fc2.features) == 3

def test_file_io_roundtrip(tmp_path, feature_collection: FeatureCollection):
    p = tmp_path / "alps_features.geojson"
    p.write_text(feature_collection.model_dump_json(indent=2), encoding="utf-8")
    raw = p.read_text(encoding="utf-8")
    fc2 = FeatureCollection.model_validate_json(raw)
    assert [f.id for f in fc2.features] == [f.id for f in feature_collection.features]

def test_parse_from_minimal_json_string():
    # minimal, valid JSON string (one feature)
    json_str = json.dumps({
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "custom:poi-001",
                "geometry": {"type": "Point", "coordinates": [11.2222, 47.3333]},
                "properties": {
                    "schema_version": "1.0",
                    "name": "Water Source at Alp Meadow",
                    "kind": "poi",
                    "ele_m": 1640,
                    "source": "custom",
                    "source_id": "poi-001",
                    "meta": {"type": "spring", "reliability": "seasonal"}
                }
            }
        ]
    })
    fc = FeatureCollection.model_validate_json(json_str)
    assert fc.type == "FeatureCollection"
    assert len(fc.features) == 1
    f = fc.features[0]
    assert f.properties.name == "Water Source at Alp Meadow"
    assert f.geometry.coordinates == [11.2222, 47.3333]
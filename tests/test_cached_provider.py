import json
import pytest
from pathlib import Path

from waykit.cached_provider import (
    jsonl_row_to_feature,
    load_index,
    _collect_nearby_features,
    gpx_to_features,
    gpx_files_to_features,
)
from waykit.models import Feature, FeatureCollection

SAMPLE_ROW = {
    "uri": "osm:node:12345",
    "lat": 46.5,
    "lon": 7.5,
    "tags": {"name": "Cabane du Test", "ele": "2500", "tourism": "alpine_hut"},
    "type": "alpine_hut",
    "ele": "2500",
    "url": "https://example.com/hut",
    "name": "Cabane du Test",
}

TESTDATA = Path(__file__).parent.parent / "testdata"
DATA_DIR = Path(__file__).parent.parent / "src" / "waykit" / "data"


# ---- jsonl_row_to_feature ----

class TestJsonlRowToFeature:
    def test_basic_mapping(self):
        feat = jsonl_row_to_feature(SAMPLE_ROW)
        assert feat.id == "osm:node:12345"
        assert feat.properties.name == "Cabane du Test"
        assert feat.properties.kind == "hut"
        assert feat.properties.ele_m == 2500.0
        assert feat.properties.source == "osm"
        assert feat.properties.source_id == "osm:node:12345"
        assert feat.geometry.coordinates == [7.5, 46.5]

    def test_url_in_meta(self):
        feat = jsonl_row_to_feature(SAMPLE_ROW)
        assert feat.properties.meta["url"] == "https://example.com/hut"

    def test_osm_tags_in_meta(self):
        feat = jsonl_row_to_feature(SAMPLE_ROW)
        tags = feat.properties.meta["osm_tags"]
        assert isinstance(tags, list)
        assert any("tourism=alpine_hut" in t for t in tags)

    def test_missing_name_uses_fallback(self):
        row = {**SAMPLE_ROW, "name": None}
        feat = jsonl_row_to_feature(row)
        assert "node:12345" in feat.properties.name

    def test_missing_ele(self):
        row = {**SAMPLE_ROW, "ele": None}
        feat = jsonl_row_to_feature(row)
        assert feat.properties.ele_m is None

    def test_invalid_ele(self):
        row = {**SAMPLE_ROW, "ele": "unknown"}
        feat = jsonl_row_to_feature(row)
        assert feat.properties.ele_m is None

    def test_no_url(self):
        row = {**SAMPLE_ROW, "url": None}
        feat = jsonl_row_to_feature(row)
        assert "url" not in feat.properties.meta

    def test_no_tags(self):
        row = {**SAMPLE_ROW, "tags": None}
        feat = jsonl_row_to_feature(row)
        assert "osm_tags" not in feat.properties.meta


# ---- load_index ----

class TestLoadIndex:
    def test_load_bundled_data(self):
        index = load_index()
        assert len(index) > 0

    def test_load_custom_jsonl(self, tmp_path):
        jsonl_file = tmp_path / "test.jsonl"
        jsonl_file.write_text(
            json.dumps(SAMPLE_ROW) + "\n",
            encoding="utf-8",
        )
        index = load_index(data_path=jsonl_file)
        assert len(index) == 1

    def test_empty_file(self, tmp_path):
        jsonl_file = tmp_path / "empty.jsonl"
        jsonl_file.write_text("", encoding="utf-8")
        index = load_index(data_path=jsonl_file)
        assert len(index) == 0

    def test_multiple_rows(self, tmp_path):
        rows = [
            {**SAMPLE_ROW, "uri": f"osm:node:{i}", "lat": 46.5 + i * 0.01}
            for i in range(5)
        ]
        jsonl_file = tmp_path / "multi.jsonl"
        jsonl_file.write_text(
            "\n".join(json.dumps(r) for r in rows),
            encoding="utf-8",
        )
        index = load_index(data_path=jsonl_file)
        assert len(index) == 5


# ---- _collect_nearby_features ----

class TestCollectNearby:
    @pytest.fixture
    def small_index(self, tmp_path):
        rows = [
            {**SAMPLE_ROW, "uri": "osm:node:1", "lat": 46.500, "lon": 7.500, "name": "Near"},
            {**SAMPLE_ROW, "uri": "osm:node:2", "lat": 47.500, "lon": 8.500, "name": "Far"},
        ]
        jsonl_file = tmp_path / "test.jsonl"
        jsonl_file.write_text(
            "\n".join(json.dumps(r) for r in rows),
            encoding="utf-8",
        )
        return load_index(data_path=jsonl_file)

    def test_finds_nearby(self, small_index):
        # Query near the first point (lon, lat)
        gpx_points = [(7.500, 46.500)]
        results = _collect_nearby_features(gpx_points, small_index, distance_m=1000.0)
        names = [f.properties.name for f in results]
        assert "Near" in names

    def test_excludes_far(self, small_index):
        gpx_points = [(7.500, 46.500)]
        results = _collect_nearby_features(gpx_points, small_index, distance_m=1000.0)
        names = [f.properties.name for f in results]
        assert "Far" not in names

    def test_deduplicates(self, small_index):
        # Two nearby query points that would both find the same feature
        gpx_points = [(7.500, 46.500), (7.5001, 46.5001)]
        results = _collect_nearby_features(gpx_points, small_index, distance_m=1000.0)
        ids = [f.id for f in results]
        assert len(ids) == len(set(ids))

    def test_empty_points(self, small_index):
        results = _collect_nearby_features([], small_index, distance_m=1000.0)
        assert results == []


# ---- gpx_to_features / gpx_files_to_features ----

class TestGpxIntegration:
    @pytest.fixture
    def sample_gpx(self):
        """Return path to a real GPX file if available, else skip."""
        gpx_files = list(TESTDATA.glob("*.gpx"))
        if not gpx_files:
            pytest.skip("No GPX test files in testdata/")
        return str(gpx_files[0])

    def test_gpx_to_features_returns_collection(self, sample_gpx):
        fc = gpx_to_features(sample_gpx, distance_m=500.0)
        assert isinstance(fc, FeatureCollection)
        assert isinstance(fc.features, list)

    def test_gpx_files_to_features_returns_collection(self, sample_gpx):
        fc = gpx_files_to_features([sample_gpx], distance_m=500.0)
        assert isinstance(fc, FeatureCollection)
        assert isinstance(fc.features, list)

    def test_gpx_to_features_with_custom_data(self, sample_gpx, tmp_path):
        # Use a JSONL with a single far-away hut — should return no results
        row = {**SAMPLE_ROW, "lat": -45.0, "lon": 170.0}
        jsonl_file = tmp_path / "far.jsonl"
        jsonl_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
        fc = gpx_to_features(sample_gpx, distance_m=500.0, data_path=jsonl_file)
        assert len(fc.features) == 0

    def test_all_features_are_valid(self, sample_gpx):
        fc = gpx_to_features(sample_gpx, distance_m=2000.0)
        for feat in fc.features:
            assert feat.id
            assert feat.properties.name
            assert feat.properties.source == "osm"
            assert len(feat.geometry.coordinates) == 2

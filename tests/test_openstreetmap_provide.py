from waykit.openstreetmap_provider import (
    haversine_m,
    bbox_of_points,
    expand_bbox,
    extract_gpx_points,
    fetch_osm_features,
    map_osm_element_to_feature,
    filter_by_proximity,
    gpx_to_features,
)
from unittest.mock import patch, MagicMock


def test_haversine_m():
    # Test distance between two points
    distance = haversine_m(0, 0, 1, 1)
    assert abs(distance - 157249.38127194397) < 0.01


def test_bbox_of_points():
    points = [(0, 0), (1, 1), (-1, -1)]
    bbox = bbox_of_points(points)
    assert bbox == (-1, -1, 1, 1)


def test_expand_bbox():
    bbox = (0, 0, 1, 1)
    expanded = expand_bbox(bbox, margin_km=1)
    assert expanded


@patch('waykit.openstreetmap_provider.gpxpy.parse')
def test_extract_gpx_points(mock_parse):
    mock_gpx = MagicMock()
    mock_gpx.routes = [MagicMock(points=[MagicMock(longitude=0, latitude=0)])]
    mock_gpx.tracks = []
    mock_parse.return_value = mock_gpx

    points = extract_gpx_points(mock_gpx)
    assert points == [(0, 0)]


@patch('waykit.openstreetmap_provider.requests.post')
def test_fetch_osm_features(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {'elements': []}
    mock_post.return_value = mock_response

    features = fetch_osm_features(0, 0, 1, 1, "test-agent")
    assert features == []


def test_map_osm_element_to_feature():
    element = {
        "type": "node",
        "lon": 0,
        "lat": 0,
        "tags": {"natural": "peak", "name": "Test Peak"}
    }
    feature = map_osm_element_to_feature(element)
    assert feature is not None
    assert feature.properties.name == "Test Peak"


def test_filter_by_proximity():
    features = [MagicMock(geometry=MagicMock(coordinates=[0, 0]))]
    gpx_points = [(0, 0)]
    kept = filter_by_proximity(features, gpx_points, max_distance_m=500)
    assert len(kept) == 1


@patch('waykit.openstreetmap_provider.open')
@patch('waykit.openstreetmap_provider.fetch_osm_features')
@patch('waykit.openstreetmap_provider.extract_gpx_points')
def test_gpx_to_features(mock_extract, mock_fetch, mock_open):
    # Create a mock GPX object
    mock_gpx = MagicMock()
    mock_gpx.routes = [MagicMock(points=[MagicMock(longitude=0, latitude=0)])]
    mock_extract.return_value = [(0, 0)]
    mock_fetch.return_value = []

    # Mock the open function to return a valid GPX string
    mock_open.return_value.__enter__.return_value.read.return_value = '<gpx></gpx>'

    collection = gpx_to_features("dummy_path.gpx")
    assert collection is not None
    assert len(collection.features) == 0
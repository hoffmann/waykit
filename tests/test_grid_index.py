import pytest
from math import radians, cos

from waykit.grid_index import (
    EARTH_RADIUS_M,
    Point,
    project_local_m,
    base36_encode,
    base36_decode,
    zigzag_encode,
    zigzag_decode,
    encode_cell_id,
    decode_cell_id,
    cell_id_from_point,
    SquareGridIndex,
    neighbors_square,
)


# ---- Point dataclass ----

class TestPoint:
    def test_frozen(self):
        pt = Point(1.0, 2.0)
        with pytest.raises(AttributeError):
            pt.x = 3.0  # type: ignore

    def test_equality(self):
        assert Point(1.0, 2.0) == Point(1.0, 2.0)
        assert Point(1.0, 2.0) != Point(1.0, 3.0)


# ---- project_local_m ----

class TestProjectLocalM:
    def test_origin_maps_to_zero(self):
        pt = project_local_m(47.0, 10.0, 47.0, 10.0)
        assert pt.x == pytest.approx(0.0)
        assert pt.y == pytest.approx(0.0)

    def test_north_offset(self):
        """Moving 1 degree north should be ~111 km."""
        pt = project_local_m(48.0, 10.0, 47.0, 10.0)
        assert pt.x == pytest.approx(0.0)
        assert pt.y == pytest.approx(EARTH_RADIUS_M * radians(1.0), rel=1e-6)

    def test_east_offset(self):
        """Moving 1 degree east at lat 47 should be ~111 km * cos(47)."""
        pt = project_local_m(47.0, 11.0, 47.0, 10.0)
        expected_x = EARTH_RADIUS_M * radians(1.0) * cos(radians(47.0))
        assert pt.x == pytest.approx(expected_x, rel=1e-6)
        assert pt.y == pytest.approx(0.0)

    def test_south_and_west_are_negative(self):
        pt = project_local_m(46.0, 9.0, 47.0, 10.0)
        assert pt.x < 0
        assert pt.y < 0


# ---- base36 encoding ----

class TestBase36:
    def test_zero(self):
        assert base36_encode(0) == "0"
        assert base36_decode("0") == 0

    def test_single_digit(self):
        assert base36_encode(9) == "9"
        assert base36_encode(10) == "a"
        assert base36_encode(35) == "z"

    def test_multi_digit(self):
        assert base36_encode(36) == "10"
        assert base36_encode(37) == "11"

    def test_round_trip(self):
        for n in [0, 1, 35, 36, 100, 999, 123456789]:
            assert base36_decode(base36_encode(n)) == n

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            base36_encode(-1)

    def test_decode_known(self):
        assert base36_decode("10") == 36
        assert base36_decode("z") == 35
        assert base36_decode("a") == 10


# ---- zigzag encoding ----

class TestZigZag:
    def test_zero(self):
        assert zigzag_encode(0) == 0
        assert zigzag_decode(0) == 0

    def test_positive(self):
        assert zigzag_encode(1) == 2
        assert zigzag_encode(2) == 4

    def test_negative(self):
        assert zigzag_encode(-1) == 1
        assert zigzag_encode(-2) == 3

    def test_round_trip(self):
        for n in [0, 1, -1, 100, -100, 999999, -999999]:
            assert zigzag_decode(zigzag_encode(n)) == n

    def test_always_non_negative(self):
        for n in range(-50, 51):
            assert zigzag_encode(n) >= 0


# ---- cell ID encoding ----

class TestCellId:
    def test_origin_cell(self):
        cid = encode_cell_id(0, 0)
        assert decode_cell_id(cid) == (0, 0)

    def test_positive_coords(self):
        cid = encode_cell_id(5, 10)
        assert decode_cell_id(cid) == (5, 10)

    def test_negative_coords(self):
        cid = encode_cell_id(-3, -7)
        assert decode_cell_id(cid) == (-3, -7)

    def test_mixed_signs(self):
        cid = encode_cell_id(-10, 20)
        assert decode_cell_id(cid) == (-10, 20)

    def test_large_coords(self):
        cid = encode_cell_id(100000, -200000)
        assert decode_cell_id(cid) == (100000, -200000)

    def test_id_is_alphanumeric(self):
        cid = encode_cell_id(-42, 99)
        assert cid.isalnum()
        assert cid.islower() or cid.isdigit()

    def test_different_coords_produce_different_ids(self):
        ids = {encode_cell_id(x, y) for x in range(-5, 6) for y in range(-5, 6)}
        assert len(ids) == 121  # 11 * 11 unique cells


# ---- cell_id_from_point ----

class TestCellIdFromPoint:
    def test_origin(self):
        assert cell_id_from_point(Point(0.0, 0.0), 100.0) == (0, 0)

    def test_positive(self):
        assert cell_id_from_point(Point(150.0, 250.0), 100.0) == (1, 2)

    def test_negative(self):
        assert cell_id_from_point(Point(-50.0, -150.0), 100.0) == (-1, -2)

    def test_exact_boundary(self):
        assert cell_id_from_point(Point(100.0, 200.0), 100.0) == (1, 2)

    def test_just_below_boundary(self):
        assert cell_id_from_point(Point(99.99, 199.99), 100.0) == (0, 1)


# ---- SquareGridIndex ----

class TestSquareGridIndex:
    @pytest.fixture
    def alps_index(self):
        """Grid index centered on the Alps with 200m cells."""
        return SquareGridIndex(cell_size_m=200.0, origin_lat=47.0, origin_lon=10.0)

    def test_empty_index(self, alps_index):
        assert len(alps_index) == 0
        assert alps_index.buckets() == 0

    def test_insert_returns_cell_id(self, alps_index):
        cid = alps_index.insert(47.0, 10.0, "origin_poi")
        assert isinstance(cid, str)
        assert len(cid) > 0

    def test_insert_increments_len(self, alps_index):
        alps_index.insert(47.0, 10.0, "a")
        assert len(alps_index) == 1
        alps_index.insert(47.1, 10.1, "b")
        assert len(alps_index) == 2

    def test_same_location_same_cell(self, alps_index):
        cid1 = alps_index.insert(47.0, 10.0, "a")
        cid2 = alps_index.insert(47.0, 10.0, "b")
        assert cid1 == cid2
        assert alps_index.buckets() == 1
        assert len(alps_index) == 2

    def test_distant_points_different_cells(self, alps_index):
        alps_index.insert(47.0, 10.0, "a")
        alps_index.insert(48.0, 11.0, "b")
        assert alps_index.buckets() == 2

    def test_bulk_insert(self, alps_index):
        rows = [
            (47.0, 10.0, "a"),
            (47.1, 10.1, "b"),
            (47.2, 10.2, "c"),
        ]
        alps_index.bulk_insert(rows)
        assert len(alps_index) == 3

    def test_candidates_near_finds_inserted_item(self, alps_index):
        alps_index.insert(47.0, 10.0, "target")
        results = alps_index.candidates_near(47.0, 10.0, radius_m=500.0)
        assert "target" in results

    def test_candidates_near_finds_nearby_item(self, alps_index):
        # ~100m north of origin
        alps_index.insert(47.0009, 10.0, "nearby")
        results = alps_index.candidates_near(47.0, 10.0, radius_m=500.0)
        assert "nearby" in results

    def test_candidates_near_excludes_far_item(self, alps_index):
        # ~11km away
        alps_index.insert(47.1, 10.0, "far")
        results = alps_index.candidates_near(47.0, 10.0, radius_m=200.0)
        assert "far" not in results

    def test_candidates_near_empty_index(self, alps_index):
        results = alps_index.candidates_near(47.0, 10.0, radius_m=1000.0)
        assert results == []

    def test_candidates_returns_all_items_in_cell(self, alps_index):
        alps_index.insert(47.0, 10.0, "a")
        alps_index.insert(47.0, 10.0, "b")
        alps_index.insert(47.0, 10.0, "c")
        results = alps_index.candidates_near(47.0, 10.0, radius_m=100.0)
        assert set(results) == {"a", "b", "c"}

    def test_generic_type(self):
        """Index works with different item types."""
        idx = SquareGridIndex[int](cell_size_m=100.0, origin_lat=47.0, origin_lon=10.0)
        idx.insert(47.0, 10.0, 42)
        results = idx.candidates_near(47.0, 10.0, radius_m=500.0)
        assert results == [42]


# ---- neighbors_square ----

class TestNeighborsSquare:
    def test_r0_returns_self(self):
        cid = encode_cell_id(5, 5)
        result = neighbors_square(cid, r=0)
        assert result == [cid]

    def test_r1_returns_9_cells(self):
        cid = encode_cell_id(0, 0)
        result = neighbors_square(cid, r=1)
        assert len(result) == 9

    def test_r2_returns_25_cells(self):
        cid = encode_cell_id(0, 0)
        result = neighbors_square(cid, r=2)
        assert len(result) == 25

    def test_center_is_included(self):
        cid = encode_cell_id(3, 4)
        result = neighbors_square(cid, r=1)
        assert cid in result

    def test_all_neighbors_are_unique(self):
        cid = encode_cell_id(0, 0)
        result = neighbors_square(cid, r=2)
        assert len(result) == len(set(result))

    def test_neighbors_decode_correctly(self):
        cx, cy = 10, -5
        cid = encode_cell_id(cx, cy)
        result = neighbors_square(cid, r=1)
        decoded = [decode_cell_id(c) for c in result]
        expected = {(cx + dx, cy + dy) for dx in range(-1, 2) for dy in range(-1, 2)}
        assert set(decoded) == expected

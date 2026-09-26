import numpy as np
import pytest

from routefuel.geo import densify, haversine_miles, simplify


def test_haversine_matches_a_known_distance():
    assert haversine_miles(40.7128, -74.0060, 34.0522, -118.2437) == pytest.approx(2445, abs=5)


def test_densify_caps_segment_length_and_keeps_endpoints():
    lat, lon = densify(np.array([35.0, 35.0]), np.array([-100.0, -99.0]), 2.0)
    steps = haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    assert steps.max() <= 2.0
    assert (lat[0], lon[0], lat[-1], lon[-1]) == (35.0, -100.0, 35.0, -99.0)


def test_simplify_drops_collinear_points_and_keeps_corners():
    xy = np.array([[0, 0], [1, 0], [2, 0], [3, 0], [3, 1], [3, 2], [3.001, 3]], dtype=float)
    assert simplify(xy, 0.01).tolist() == [0, 3, 6]


def test_simplify_measures_distance_to_the_segment_for_routes_that_double_back():
    xy = np.array([[0, 0], [5, 0], [-1, 0]], dtype=float)
    assert simplify(xy, 0.5).tolist() == [0, 1, 2]

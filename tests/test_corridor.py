from decimal import Decimal

import pytest

from routefuel.corridor import find_candidates
from routefuel.domain import Point, Route, Station
from routefuel.stations import StationIndex


def station(id, lon, lat=35.0, price="3"):
    return Station(id, "S", "C", "TX", "A", Decimal(price), Point(lat, lon), id)


def test_candidates_are_ordered_by_route_mile_and_limited_to_the_corridor():
    route = Route((Point(35, -100), Point(35, -95), Point(35, -90)), 565)
    stations = StationIndex(
        (station(3, -91), station(1, -98), station(2, -96, 35.1), station(4, -92, 37))
    )
    candidates = find_candidates(route, stations, 12)
    assert [c.station.id for c in candidates] == [1, 2, 3]
    assert candidates[0].route_mile == pytest.approx(113, rel=0.01)
    assert candidates[1].offset_miles == pytest.approx(6.9, abs=0.2)


def test_long_straight_segment_does_not_hide_a_nearby_station():
    route = Route((Point(35, -100), Point(35, -90)), 565)
    candidates = find_candidates(route, StationIndex((station(1, -95, 35.05),)), 12)
    assert len(candidates) == 1
    assert candidates[0].route_mile == pytest.approx(282, rel=0.01)


def test_stations_behind_the_start_or_outside_the_corridor_are_excluded():
    route = Route((Point(35, -100), Point(35, -95)), 283)
    stations = StationIndex((station(1, -101), station(2, -98, 37)))
    assert find_candidates(route, stations, 12) == ()


def test_cheapest_station_near_a_point_prefers_price_then_distance():
    index = StationIndex(
        (
            station(1, -100.05, price="3.10"),
            station(2, -100.2, price="2.90"),
            station(3, -99, price="1"),
        )
    )
    chosen, distance = index.cheapest_near(Point(35, -100), 25)
    assert chosen.id == 2
    assert distance == pytest.approx(11.3, abs=0.2)
    assert index.cheapest_near(Point(40, -80), 25) is None
